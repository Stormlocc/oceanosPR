"""P5–P8 from an archived attempt: conform, assess, package, publish (DA-4 re-entry point)."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import numpy as np
import rasterio  # type: ignore[import-untyped]
from rasterio.warp import transform_geom  # type: ignore[import-untyped]
from shapely.geometry import box, mapping  # type: ignore[import-untyped]

import oceanos
from oceanos.acolite.products import (
    ProductResolutionError,
    residual_swir_variable,
    resolve_product,
    surface_reflectance_bands,
)
from oceanos.catalog import LocalSceneCatalog, SceneMetadata
from oceanos.config import OceanosSettings
from oceanos.domain import (
    AcoliteProfile,
    AcoliteRunOutputs,
    AnalysisMaskRef,
    ArtifactRef,
    ConformedLayer,
    DownstreamProfile,
    FailureCode,
    FailureRecord,
    FailureScope,
    InputSet,
    LandMaskRef,
    LayerSource,
    ObservationStatus,
    ProductSet,
    ProductSpec,
    ProvenanceAcolite,
    ProvenanceAncillary,
    ProvenanceOceanos,
    ProvenanceProduct,
    ProvenanceRecord,
    ProvenanceScene,
    ProvenanceTimestamps,
    PublicationProfile,
    PublishedAsset,
    QualityPolicy,
    QualityReport,
    Release,
    RunState,
    StageName,
    UsabilityVerdict,
    release_id,
)
from oceanos.processing.grid import DeliveryGrid
from oceanos.processing.masks import (
    LAND_MASK_VERSION,
    ensure_analysis_mask,
    ensure_land_mask,
    product_analysis,
    read_analysis_layers,
    read_land,
)
from oceanos.processing.normalize import ConformError, conform_layer
from oceanos.processing.quality import (
    ProductLayer,
    QualityInputs,
    assess,
    valid_flag_pixels,
)
from oceanos.publishing import (
    publish_release,
    write_cog,
    write_true_colour,
)
from oceanos.publishing.release import FaultHook
from oceanos.publishing.stac import build_item
from oceanos.storage import StorageLayout
from oceanos.timeseries import WHOLE_AOI_ZONE, zone_series

BATHYMETRY_GLOB = "bathymetry/cudem/ncei19_*.tif"
USABLE_LABEL = (
    "Satellite-derived estimates from Sentinel-2 MSI with ACOLITE; not validated against in-situ "
    "measurements for La Parguera. Read each product's caveat."
)
RESTRICTED_LABEL = "No usable observation: display and pixel flags only; science layers withheld by the quality policy."
RESTRICTED_PRODUCTS = ("true_colour", "l2_flags")
COG_MEDIA = "image/tiff; application=geotiff; profile=cloud-optimized"
OVERPASS_PLATFORMS = {"S2A", "S2B", "S2C"}

StageHook = Callable[..., None]
FailHook = Callable[[StageName, FailureRecord], Exception]


class PipelineError(RuntimeError):
    """One observation could not be published; carries the recorded failure."""

    def __init__(self, failure: FailureRecord) -> None:
        super().__init__(f"{failure.code.value}: {failure.message}")
        self.failure = failure


def reference_data(settings: OceanosSettings) -> list[Path]:
    """OCEANOS-owned CUDEM elevation tiles under ``acolite.external_dir`` (land mask and bathymetry)."""
    return sorted(settings.acolite.external_dir.glob(BATHYMETRY_GLOB))


def downstream_profile(products: ProductSet, policy: QualityPolicy, publication: PublicationProfile) -> DownstreamProfile:
    return DownstreamProfile(
        product_set_version=products.version, quality_policy_version=policy.version,
        land_mask_version=LAND_MASK_VERSION, analysis_mask_version=_analysis_mask_version(products, policy),
        publication_profile_version=publication.profile_id,
    )


def _analysis_mask_version(products: ProductSet, policy: QualityPolicy) -> str:
    cuts = {spec.product_key: spec.shallow_exclusion_m for spec in products.specs}
    canonical = json.dumps({"buffer": policy.coastal_buffer_m, "cuts": cuts}, sort_keys=True)
    return f"1-{sha256(canonical.encode()).hexdigest()[:12]}"


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, root: Path, role: str, media_type: str) -> ArtifactRef:
    return ArtifactRef(
        role=role, relpath=path.relative_to(root).as_posix(), sha256=_file_sha256(path),
        size=path.stat().st_size, media_type=media_type,
    )


def _failure(code: FailureCode, stage: StageName, message: str, *, scope: FailureScope = FailureScope.OBSERVATION,
             retryable: bool = False, evidence: list[str] | None = None) -> FailureRecord:
    return FailureRecord(code=code, scope=scope, stage=stage.value, message=message, evidence=evidence or [],
                         retryable=retryable, occurred_at=datetime.now(UTC))


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as dataset:
        return np.asarray(dataset.read(1))


@dataclass
class DownstreamInputs:
    settings: OceanosSettings
    layout: StorageLayout
    aoi_id: str
    overpass_id: str
    grid: DeliveryGrid
    grid_dir: Path
    catalog: LocalSceneCatalog
    attempt_id: str
    run_key: str
    oceanos_git_sha: str
    profile: AcoliteProfile
    input_set: InputSet
    installation_commit: str
    outputs: AcoliteRunOutputs
    archived_at: datetime
    scene_datetime: datetime
    products: ProductSet
    policy: QualityPolicy
    publication: PublicationProfile
    current_release_id: str | None


@dataclass(frozen=True)
class DownstreamResult:
    release_id: str
    release_dir: Path
    report: QualityReport


def publish_downstream(
    inputs: DownstreamInputs, *, advance: StageHook | None = None, fail: FailHook | None = None,
    fault: FaultHook | None = None,
) -> DownstreamResult:
    """Run P5–P8 for one archived attempt under an already-held writer lock."""
    layout, grid, outputs, products, policy, publication = (
        inputs.layout, inputs.grid, inputs.outputs, inputs.products, inputs.policy, inputs.publication,
    )
    stage = advance or (lambda *args, **kwargs: None)

    def raise_failure(stage_name: StageName, failure: FailureRecord) -> PipelineError:
        return fail(stage_name, failure) if fail is not None else PipelineError(failure)  # type: ignore[return-value]

    platform = inputs.overpass_id[:3]
    if platform not in OVERPASS_PLATFORMS:
        raise ValueError(f"unsupported platform in overpass id: {inputs.overpass_id}")
    observation_id = f"{inputs.aoi_id}/{inputs.overpass_id}"
    downstream = downstream_profile(products, policy, publication)
    new_release_id = release_id(inputs.attempt_id, downstream.profile_id)
    specs = {spec.product_key: spec for spec in products.specs}
    published = [specs[key] for key in publication.published_products]
    science = [spec for spec in published if spec.kind in {"continuous", "binary"}]

    staging_root = layout.work / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    conform_dir = Path(tempfile.mkdtemp(prefix=".conform-", dir=staging_root))
    release_staging = Path(tempfile.mkdtemp(prefix=".release-", dir=staging_root))
    try:
        # P5 conform.
        bathymetry = reference_data(inputs.settings)
        land_mask = ensure_land_mask(inputs.grid_dir, grid, bathymetry)
        land = read_land(inputs.grid_dir, grid)
        land_ref = LandMaskRef(version=land_mask.version, sha256=land_mask.raster.sha256)
        analysis_mask = ensure_analysis_mask(
            inputs.grid_dir, grid, bathymetry_paths=bathymetry,
            coastal_buffer_m=policy.coastal_buffer_m, min_analysis_pixels=policy.min_analysis_pixels,
            shallow_exclusion_m={spec.product_key: spec.shallow_exclusion_m for spec in science},
        )
        coastal_buffer, depth = read_analysis_layers(inputs.grid_dir, grid)
        out_of_scene = next((1 << bit.bit for bit in outputs.flag_spec.bits if bit.name == "out_of_scene"), None)
        archive_root = layout.archive

        def container(role: str) -> tuple[Path, str]:
            ref = outputs.l2w if role == "l2w" else outputs.l2r
            return archive_root / ref.relpath, ref.sha256

        layers: dict[str, tuple[ConformedLayer, str | tuple[str, ...], float | None]] = {}
        try:
            for spec in published:
                if spec.kind == "display":
                    continue
                role, variable, wavelength = resolve_product(outputs, spec)
                path, digest = container(role)
                masked = spec.land_masked and spec.kind != "bitfield"
                layer = conform_layer(
                    path, variable, conform_dir / f"{spec.product_key}.tif", grid,
                    product_key=spec.product_key, kind=spec.kind, unit=spec.unit,
                    source=LayerSource(container_role=role, container_sha256=digest, variable=variable),
                    out_of_scene_value=out_of_scene if spec.kind == "bitfield" else None,
                    land=land if masked else None, land_mask=land_ref if masked else None, tier_root=conform_dir,
                )
                layers[spec.product_key] = (layer, variable, wavelength)
            rgb_paths: tuple[Path, Path, Path] | None = None
            rgb_variables: tuple[str, str, str] | None = None
            if "true_colour" in publication.published_products and publication.true_colour is not None:
                rgb_variables = surface_reflectance_bands(outputs, platform, publication.true_colour.bands)  # type: ignore[arg-type]
                l2r_path, l2r_digest = container("l2r")
                rgb = []
                for index, variable in enumerate(rgb_variables):
                    conform_layer(
                        l2r_path, variable, conform_dir / f"rgb_{index}.tif", grid, product_key=f"rgb_{index}",
                        kind="continuous", unit="1",
                        source=LayerSource(container_role="l2r", container_sha256=l2r_digest, variable=variable),
                        tier_root=conform_dir,
                    )
                    rgb.append(conform_dir / f"rgb_{index}.tif")
                rgb_paths = (rgb[0], rgb[1], rgb[2])
            swir_values: np.ndarray | None = None
            swir_variable = residual_swir_variable(outputs, platform)  # type: ignore[arg-type]
            if swir_variable is not None:
                l2w_path, l2w_digest = container("l2w")
                conform_layer(
                    l2w_path, swir_variable, conform_dir / "swir_rhow.tif", grid, product_key="swir_rhow",
                    kind="continuous", unit="1",
                    source=LayerSource(container_role="l2w", container_sha256=l2w_digest, variable=swir_variable),
                    tier_root=conform_dir,
                )
                swir_values = _read(conform_dir / "swir_rhow.tif")
        except ProductResolutionError as exc:
            raise raise_failure(StageName.CONFORM, _failure(
                FailureCode.ACOLITE_MISSING_VARIABLE, StageName.CONFORM, str(exc),
                evidence=[f"l2w={outputs.l2w.relpath}", f"l2r={outputs.l2r.relpath}"]))
        except ConformError as exc:
            scope = FailureScope.BATCH if exc.code is FailureCode.GRID_MISALIGNED else FailureScope.OBSERVATION
            raise raise_failure(StageName.CONFORM, _failure(
                exc.code, StageName.CONFORM, str(exc), scope=scope,
                evidence=[f"grid_id={grid.grid_id}", f"l2w={outputs.l2w.relpath}"]))
        stage(StageName.CONFORM, RunState.CONFORMED, layers=len(layers))

        # P6 assess.
        flags_layer = layers["l2_flags"][0]
        flags = _read(conform_dir / flags_layer.raster.relpath)
        water = ~coastal_buffer
        analyses = {spec.product_key: product_analysis(coastal_buffer, depth, spec.shallow_exclusion_m) for spec in science}
        arrays = {spec.product_key: _read(conform_dir / layers[spec.product_key][0].raster.relpath) for spec in science}
        quality_inputs = QualityInputs(
            observation_id=observation_id, attempt_id=inputs.attempt_id, flags=flags, flag_spec=outputs.flag_spec,
            water=water,
            products={
                spec.product_key: ProductLayer(
                    values=arrays[spec.product_key], analysis=analyses[spec.product_key],
                    gates_verdict=spec.kind == "continuous" and not spec.masked_by_acolite,
                )
                for spec in science
            },
            grid_coverage_fraction=flags_layer.grid_coverage_fraction, aerosol=outputs.aerosol,
            ancillary=outputs.ancillary, glint_angle_deg=outputs.glint_angle_deg, swir_rhow=swir_values, policy=policy,
        )
        report = assess(quality_inputs)
        usable = report.verdict is UsabilityVerdict.USABLE
        stage(StageName.ASSESS, RunState.ASSESSED, verdict=report.verdict.value, reasons=list(report.reasons))

        # P7 package.
        try:
            visible = [spec for spec in published if usable or spec.product_key in RESTRICTED_PRODUCTS]
            assets: list[PublishedAsset] = []
            for spec in visible:
                target = release_staging / f"{spec.product_key}.tif"
                if spec.kind == "display":
                    if rgb_paths is None or publication.true_colour is None or publication.display is None:
                        continue
                    write_true_colour(rgb_paths, conform_dir / "true_colour.tif", publication.true_colour)
                    write_cog(conform_dir / "true_colour.tif", target, publication.display)
                    assets.append(PublishedAsset(
                        product_key=spec.product_key, href=target.name, sha256=_file_sha256(target),
                        size=target.stat().st_size, media_type=COG_MEDIA, roles=("visual",), data_type="uint8",
                        overview_resampling=publication.display.overview_resampling,
                    ))
                    continue
                layer, _, wavelength = layers[spec.product_key]
                cog = publication.bitfield if spec.kind == "bitfield" else publication.continuous
                write_cog(conform_dir / layer.raster.relpath, target, cog)
                assets.append(PublishedAsset(
                    product_key=spec.product_key, href=target.name, sha256=_file_sha256(target),
                    size=target.stat().st_size, media_type=COG_MEDIA, roles=("data",), unit=layer.unit,
                    nodata=layer.nodata, data_type=layer.data_type, overview_resampling=cog.overview_resampling,
                    center_wavelength_nm=wavelength,
                ))
            settings_copy = release_staging / "settings_resolved.txt"
            shutil.copy2(archive_root / outputs.settings_resolved.relpath, settings_copy)
            assets.append(PublishedAsset(
                product_key="settings_resolved", href=settings_copy.name, sha256=_file_sha256(settings_copy),
                size=settings_copy.stat().st_size, media_type="text/plain", roles=("metadata",),
            ))

            quality_path = release_staging / "quality.json"
            quality_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
            valid = valid_flag_pixels(flags, outputs.flag_spec, policy.cloud_dilation_px)
            rows = zone_series(
                zone_id=WHOLE_AOI_ZONE, zone=np.ones(flags.shape, dtype=bool), observation_id=observation_id,
                observed_at=inputs.scene_datetime,
                products={spec.product_key: (arrays[spec.product_key], analyses[spec.product_key], spec.unit) for spec in science},
                valid=valid, status=report.status, release_id=new_release_id, tier=inputs.profile.ancillary_tier,
            )
            series_path = release_staging / "series.json"
            series_path.write_text(
                json.dumps({"schema_version": "1.0", "rows": [row.model_dump(mode="json") for row in rows]},
                           indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )

            published_at = datetime.now(UTC)
            scenes = {scene.scene_id: inputs.catalog.get_scene(scene.scene_id) for scene in inputs.input_set.scenes}
            provenance = _provenance(
                inputs, observation_id, new_release_id, downstream, report, layers, rgb_variables, specs,
                analysis_ref=AnalysisMaskRef(version=analysis_mask.version, sha256=_file_sha256(inputs.grid_dir / "analysis_mask.json")),
                scenes=scenes, published_at=published_at, usable=usable,
            )
            provenance_path = release_staging / "provenance.json"
            provenance_path.write_text(provenance.model_dump_json(indent=2) + "\n", encoding="utf-8")
            release = Release(
                release_id=new_release_id, observation_id=observation_id, attempt_id=inputs.attempt_id,
                run_key=inputs.run_key, downstream_profile_id=downstream.profile_id, tier=inputs.profile.ancillary_tier,
                visibility="public" if usable else "restricted", assets=tuple(assets),
                quality=_artifact(quality_path, release_staging, "quality", "application/json"),
                provenance=_artifact(provenance_path, release_staging, "provenance", "application/json"),
                supersedes=inputs.current_release_id, created_at=published_at,
            )
            (release_staging / "release.json").write_text(release.model_dump_json(indent=2) + "\n", encoding="utf-8")

            geometry = transform_geom(grid.spec.crs, "EPSG:4326", mapping(box(*grid.spec.bounds)))
            lons = [point[0] for point in geometry["coordinates"][0]]
            lats = [point[1] for point in geometry["coordinates"][0]]
            scene_hrefs = (
                item.get_self_href() if item is not None else None
                for item in (inputs.catalog.get_stac_item(scene.scene_id) for scene in inputs.input_set.scenes)
            )
            gating = [quality.valid_fraction for quality in report.products if quality.gates_verdict]
            item = build_item(
                release=release, overpass_id=inputs.overpass_id, aoi_id=inputs.aoi_id, datetime_utc=inputs.scene_datetime,
                geometry=dict(geometry), bbox=(min(lons), min(lats), max(lons), max(lats)),
                release_dir=layout.release_dir(inputs.aoi_id, inputs.overpass_id, new_release_id),
                products_aoi_dir=layout.products / inputs.aoi_id, flag_spec=outputs.flag_spec,
                acolite_software=f"{inputs.profile.acolite.release_tag}@{inputs.installation_commit}",
                oceanos_software=f"{oceanos.__version__}@{inputs.oceanos_git_sha}",
                acolite_release_tag=inputs.profile.acolite.release_tag, status=report.status.value,
                scene_item_paths=[Path(href) for href in scene_hrefs if href is not None],
                valid_fraction=min(gating) if gating else None,
                scientific_label=provenance.scientific_label,
            )
            stage(StageName.PACKAGE, RunState.PACKAGED, release_id=new_release_id)

            # P8 publish.
            release_dir = publish_release(
                layout=layout, aoi_id=inputs.aoi_id, overpass_id=inputs.overpass_id, release_id=new_release_id,
                staged_dir=release_staging, item=item, supersedes=inputs.current_release_id,
                fault=fault or (lambda _: None),
            )
        except OSError as exc:
            raise raise_failure(StageName.PUBLISH, _failure(
                FailureCode.PUBLISH_IO_ERROR, StageName.PUBLISH, f"{type(exc).__name__}: {exc}", retryable=True,
                evidence=[f"release_id={new_release_id}", f"path={getattr(exc, 'filename', None)}"]))
        stage(StageName.PUBLISH, RunState.PUBLISHED, release_id=new_release_id, visibility=release.visibility)
        return DownstreamResult(release_id=new_release_id, release_dir=release_dir, report=report)
    finally:
        shutil.rmtree(conform_dir, ignore_errors=True)
        if release_staging.exists():
            shutil.rmtree(release_staging, ignore_errors=True)


def _provenance(
    inputs: DownstreamInputs, observation_id: str, new_release_id: str, downstream: DownstreamProfile,
    report: QualityReport, layers: dict[str, tuple[ConformedLayer, str | tuple[str, ...], float | None]],
    rgb_variables: tuple[str, str, str] | None, specs: dict[str, ProductSpec], *, analysis_ref: AnalysisMaskRef,
    scenes: dict[str, SceneMetadata | None], published_at: datetime, usable: bool,
) -> ProvenanceRecord:
    outputs = inputs.outputs
    products: list[ProvenanceProduct] = []
    for key, (layer, variable, _) in layers.items():
        spec = specs[key]
        products.append(ProvenanceProduct(
            product_key=key, acolite_variable=variable, unit=layer.unit, s2_calibrated=spec.s2_calibrated,
            caveat=spec.caveat, source_sha256=layer.source.container_sha256,
            grid_coverage_fraction=layer.grid_coverage_fraction, land_mask=layer.land_mask,
            shallow_exclusion_m=spec.shallow_exclusion_m,
        ))
    if rgb_variables is not None and "true_colour" in specs:
        spec = specs["true_colour"]
        products.append(ProvenanceProduct(
            product_key="true_colour", acolite_variable=rgb_variables, unit=None, s2_calibrated=False,
            caveat=spec.caveat, source_sha256=outputs.l2r.sha256,
            grid_coverage_fraction=layers["l2_flags"][0].grid_coverage_fraction, land_mask=None,
        ))
    return ProvenanceRecord(
        observation_id=observation_id, release_id=new_release_id, attempt_id=inputs.attempt_id, run_key=inputs.run_key,
        scenes=tuple(
            ProvenanceScene(
                scene_id=scene.scene_id, source_id=scene.source_id, sha256=scene.archive.sha256,
                processing_baseline=metadata.processing_baseline if metadata is not None else None,
                platform=metadata.platform if metadata is not None else None,
            )
            for scene in inputs.input_set.scenes
            for metadata in (scenes.get(scene.scene_id),)
        ),
        acolite=ProvenanceAcolite(
            release_tag=inputs.profile.acolite.release_tag, commit_sha=inputs.installation_commit,
            version_attribute=outputs.acolite_version_attr, settings_user_sha256=outputs.settings_user.sha256,
            settings_resolved_sha256=outputs.settings_resolved.sha256,
        ),
        oceanos=ProvenanceOceanos(
            version=oceanos.__version__, git_sha=inputs.oceanos_git_sha, acolite_profile_id=inputs.profile.profile_id,
            downstream_profile_id=downstream.profile_id, publication_profile_id=inputs.publication.profile_id,
            product_set_version=inputs.products.version, quality_policy_version=inputs.policy.version,
        ),
        ancillary=ProvenanceAncillary(
            type=outputs.ancillary.ancillary_type, tier=inputs.profile.ancillary_tier, uoz=outputs.ancillary.uoz,
            uwv=outputs.ancillary.uwv, pressure=outputs.ancillary.pressure,
        ),
        glint_angle_deg=outputs.glint_angle_deg,
        products=tuple(products),
        timestamps=ProvenanceTimestamps(
            acquired=max(scene.verified_at for scene in inputs.input_set.scenes),
            archived=inputs.archived_at, published=published_at,
        ),
        analysis_mask=analysis_ref,
        quality_verdict=report.verdict,
        derivations=(
            "glint_angle_deg: OCEANOS specular-geometry derivation from L2R scene-mean sza/vza/raa",
            "land mask: CUDEM elevation > 0 m on the delivery grid (OCEANOS); water products NaN on land",
            "grid conformance: copy onto the delivery grid, no resampling",
        ),
        scientific_label=USABLE_LABEL if usable else RESTRICTED_LABEL,
    )


def load_archived_outputs(layout: StorageLayout, aoi_id: str, overpass_id: str, attempt_id: str) -> dict[str, object]:
    """Read the authoritative run manifest of one archived attempt."""
    manifest_path = layout.archive_attempt_dir(aoi_id, overpass_id, attempt_id) / "run-manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"archived attempt has no run manifest: {manifest_path}")
    document: dict[str, object] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return document


def archived_at(layout: StorageLayout, aoi_id: str, overpass_id: str, attempt_id: str) -> datetime:
    manifest_path = layout.archive_attempt_dir(aoi_id, overpass_id, attempt_id) / "run-manifest.json"
    return datetime.fromtimestamp(manifest_path.stat().st_mtime, UTC)


__all__ = [
    "BATHYMETRY_GLOB", "DownstreamInputs", "DownstreamResult", "ObservationStatus", "PipelineError",
    "downstream_profile", "load_archived_outputs", "publish_downstream", "reference_data",
]
