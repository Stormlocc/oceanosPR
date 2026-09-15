"""Tracer-bullet orchestration of one observation: A1 → A2 → P1–P8 under the writer lock."""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from rasterio.warp import transform_geom  # type: ignore[import-untyped]
from shapely.geometry import box, mapping  # type: ignore[import-untyped]

import oceanos
from oceanos.acolite import (
    InstallationProbe,
    RunVerifier,
    SettingsRenderer,
    SubprocessAcoliteRunner,
)
from oceanos.acolite.products import (
    ProductResolutionError,
    ancillary_type_for,
    resolve_product,
)
from oceanos.acolite.runner import ProcessOutcome
from oceanos.acolite.settings import limit_for_grid
from oceanos.aoi import load_aoi
from oceanos.catalog import LocalSceneCatalog, SceneMetadata
from oceanos.config import OceanosSettings
from oceanos.domain import (
    AcoliteInstallation,
    AcoliteParameterSet,
    AcolitePin,
    AcoliteProfile,
    AcoliteRunOutputs,
    AcquiredScene,
    AncillaryTier,
    ArtifactRef,
    ConformedLayer,
    DownstreamProfile,
    FailureCode,
    FailureRecord,
    FailureScope,
    LandMaskRef,
    LayerSource,
    OwnedSettings,
    ProductSet,
    ProvenanceAcolite,
    ProvenanceAncillary,
    ProvenanceOceanos,
    ProvenanceProduct,
    ProvenanceRecord,
    ProvenanceScene,
    ProvenanceTimestamps,
    PublicationProfile,
    PublishedAsset,
    Release,
    RunAttempt,
    RunState,
    StageName,
    StageResult,
    release_id,
    run_key,
)
from oceanos.pipeline.archive import ArchiveStore, AttemptsLedger, recover_stale_attempt
from oceanos.pipeline.plan import (
    build_input_set,
    group_overpasses,
    select_minimal_cover_with_scenes,
)
from oceanos.processing.grid import DeliveryGrid
from oceanos.processing.masks import (
    GSHHG_LAND_LAYER,
    LAND_MASK_VERSION,
    ensure_land_mask,
    read_land,
)
from oceanos.processing.normalize import ConformError, conform_layer
from oceanos.publishing import (
    BITFIELD_COG,
    CONTINUOUS_COG,
    build_item,
    current_release_id,
    publish_release,
    reconcile,
    write_cog,
)
from oceanos.publishing.release import FaultHook
from oceanos.storage import StorageLayout, WriterLock

L1C_COLLECTION = "sentinel-2-l1c"
CONTRACT_VERSION = "1"
# Brief assumption: final (reanalysis) ancillary data are used once a scene is this old.
FINAL_ANCILLARY_AFTER = timedelta(days=50)
# Phase 2 has no quality policy: the verdict is hard-coded usable (PLAN Phase 2).
TRACER_QUALITY_POLICY_VERSION = "0-hardcoded-usable"
NO_ANALYSIS_MASK_VERSION = "none"
PUBLICATION_PROFILE = PublicationProfile(
    version="0", continuous=CONTINUOUS_COG, bitfield=BITFIELD_COG,
    published_products=("tur_nechad2016", "l2_flags"),
)

AcquireFn = Callable[[SceneMetadata], AcquiredScene]
ProbeFn = Callable[[], AcoliteInstallation | FailureRecord]
RunAcoliteFn = Callable[[Path, Path, str, WriterLock], ProcessOutcome]


class PipelineError(RuntimeError):
    """One observation could not be published; carries the recorded failure."""

    def __init__(self, failure: FailureRecord) -> None:
        super().__init__(f"{failure.code.value}: {failure.message}")
        self.failure = failure


@dataclass(frozen=True)
class RunOneResult:
    status: Literal["published", "skipped"]
    run_key: str
    release_id: str
    release_dir: Path
    attempt_id: str | None


@dataclass
class RunOneDependencies:
    """External effects, substituted in tests (T24)."""

    acquire: AcquireFn
    probe: ProbeFn
    run_acolite: RunAcoliteFn
    git_sha: Callable[[], str]
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    verifier: RunVerifier = field(default_factory=RunVerifier)


def _project_git_sha() -> str:
    root = Path(oceanos.__file__).resolve().parents[2]
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()


def default_dependencies(settings: OceanosSettings, catalog: LocalSceneCatalog) -> RunOneDependencies:
    """Wire the real CDSE acquisition, installation probe and ACOLITE subprocess."""
    from oceanos.ingestion import acquire_scene
    from oceanos.ingestion.cdse_auth import CdseTokenClient

    token = CdseTokenClient(settings.scenes.identity_url)
    config = settings.acolite

    def acquire(scene: SceneMetadata) -> AcquiredScene:
        return acquire_scene(
            scene, settings.storage.raw, token_provider=token, catalog=catalog,
            max_retries=settings.scenes.max_retries,
        ).acquired

    def probe() -> AcoliteInstallation | FailureRecord:
        # The scratch tier may not exist before the first attempt; measure the disk it will use.
        settings.storage.work.mkdir(parents=True, exist_ok=True)
        return InstallationProbe().probe(
            pin=AcolitePin(release_tag=config.release_tag, commit_sha=config.commit_sha),
            root=config.root, python_executable=config.python_executable, launcher=config.launcher,
            luts_dir=config.luts_dir, external_dir=config.external_dir,
            netrc_path=Path.home() / ".netrc", disk_path=settings.storage.work,
            required_disk_bytes=10 * 1024**3,
        )

    def run_acolite(settings_path: Path, workspace: Path, runid: str, lock: WriterLock) -> ProcessOutcome:
        return SubprocessAcoliteRunner().run(
            python_executable=config.python_executable, launcher=config.launcher,
            settings_path=settings_path, workspace=workspace,
            timeout_seconds=config.timeout_seconds, runid=runid, lock=lock,
        )

    return RunOneDependencies(acquire=acquire, probe=probe, run_acolite=run_acolite, git_sha=_project_git_sha)


def _layout(settings: OceanosSettings) -> StorageLayout:
    storage = settings.storage
    return StorageLayout(
        raw=storage.raw, work=storage.work, archive=storage.archive, products=storage.products,
        superseded=storage.superseded, state=storage.state,
    )


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


def _failure(code: FailureCode, stage: StageName, message: str, evidence: list[str] | None = None,
             *, scope: FailureScope = FailureScope.OBSERVATION, retryable: bool = False) -> FailureRecord:
    return FailureRecord(
        code=code, scope=scope, stage=stage.value, message=message, evidence=evidence or [],
        retryable=retryable, occurred_at=datetime.now(UTC),
    )


class _AttemptRecorder:
    """Append every attempt transition to the ledger (DA #8)."""

    def __init__(self, ledger: AttemptsLedger, attempt: RunAttempt) -> None:
        self.ledger = ledger
        self.attempt = attempt
        self._stage_started = datetime.now(UTC)

    def begin(self) -> None:
        self._stage_started = datetime.now(UTC)

    def advance(self, stage: StageName, state: RunState, **detail: object) -> None:
        result = StageResult(
            stage=stage, status="ok", started_at=self._stage_started, ended_at=datetime.now(UTC),
            detail=dict(detail),
        )
        self.attempt = self.attempt.model_copy(update={"state": state, "stages": [*self.attempt.stages, result]})
        self.ledger.append(self.attempt)
        self.begin()

    def fail(self, stage: StageName, failure: FailureRecord) -> PipelineError:
        result = StageResult(
            stage=stage, status="failed", started_at=self._stage_started, ended_at=datetime.now(UTC),
            detail={"code": failure.code.value},
        )
        self.attempt = self.attempt.model_copy(update={
            "state": RunState.FAILED, "stages": [*self.attempt.stages, result], "failure": failure,
        })
        self.ledger.append(self.attempt)
        return PipelineError(failure)


def _tier(scene_datetime: datetime, now: datetime) -> AncillaryTier:
    return AncillaryTier.FINAL if now - scene_datetime >= FINAL_ANCILLARY_AFTER else AncillaryTier.PROVISIONAL


def run_one(
    settings: OceanosSettings, overpass_id: str, *, parameters: AcoliteParameterSet,
    products: ProductSet, force_reprocess: bool = False,
    dependencies: RunOneDependencies | None = None, fault: FaultHook | None = None,
) -> RunOneResult:
    """Publish one observation for ``overpass_id`` from a prior grid build and scene search."""
    layout = _layout(settings)
    aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
    grid_path = layout.grid_json(aoi.aoi_id)
    if not grid_path.is_file():
        raise ValueError(f"delivery grid missing; run `grid build` first: {grid_path}")
    grid = DeliveryGrid.load(grid_path)
    catalog = LocalSceneCatalog(settings.catalog_dir, collection_id=L1C_COLLECTION)
    groups = group_overpasses(catalog.search_local_catalog(collection=L1C_COLLECTION))
    if overpass_id not in groups:
        raise ValueError(f"overpass not in local catalog; run `scenes search` covering it first: {overpass_id}")
    deps = dependencies or default_dependencies(settings, catalog)
    publish_fault: FaultHook = fault or (lambda _: None)

    # A1 + A2: selection and verified acquisition are idempotent and precede the lock.
    coverage, selected = select_minimal_cover_with_scenes(groups[overpass_id], grid)
    acquired = [deps.acquire(scene) for scene in selected]
    input_set = build_input_set(overpass_id, acquired, coverage)

    now = deps.now()
    scene_datetime = min(scene.datetime for scene in selected)
    tier = _tier(scene_datetime, now)
    owned = OwnedSettings(
        limit=limit_for_grid(grid), merge_tiles=len(input_set.scenes) > 1,
        l2w_parameters=parameters.parameters, ancillary_type=ancillary_type_for(tier),
    )
    pin = AcolitePin(release_tag=settings.acolite.release_tag, commit_sha=settings.acolite.commit_sha)
    profile = AcoliteProfile(
        acolite=pin, settings=owned, parameter_set_version=parameters.version,
        grid_id=grid.grid_id, ancillary_tier=tier, contract_version=CONTRACT_VERSION,
    )
    observation_id = f"{aoi.aoi_id}/{overpass_id}"
    key = run_key(observation_id, input_set.input_set_id, profile.profile_id)

    ledger = AttemptsLedger(layout.state / "ledger" / "attempts.jsonl")
    current = current_release_id(layout, aoi.aoi_id, overpass_id)
    published_for_key = any(
        attempt.run_key == key and attempt.state is RunState.PUBLISHED for attempt in ledger.latest().values()
    )
    if published_for_key and current is not None and not force_reprocess:
        return RunOneResult(
            status="skipped", run_key=key, release_id=current,
            release_dir=layout.release_dir(aoi.aoi_id, overpass_id, current), attempt_id=None,
        )

    attempt_id = f"att-{now.strftime('%Y%m%dT%H%M%SZ')}-{key[4:12]}"
    lock = WriterLock(layout.writer_lock)
    recover_stale_attempt(lock=lock, ledger=ledger, staging=layout.work / "staging")
    with lock.hold(attempt_id):
        reconcile(layout, aoi.aoi_id, repair=True)
        current = current_release_id(layout, aoi.aoi_id, overpass_id)
        recorder = _AttemptRecorder(ledger, RunAttempt(
            attempt_id=attempt_id, run_key=key, state=RunState.PLANNED, host=socket.gethostname(),
            oceanos_version=oceanos.__version__, oceanos_git_sha=deps.git_sha(),
            acolite_exit_code=None, stages=[], failure=None,
        ))
        recorder.advance(StageName.PLAN, RunState.PLANNED, input_set_id=input_set.input_set_id,
                         acolite_profile_id=profile.profile_id, tier=tier.value)

        # P1 preflight: SAFE re-verification, then the installation probe.
        inputs: list[Path] = []
        for scene in input_set.scenes:
            archive = layout.raw / scene.archive.relpath
            if not archive.is_file() or _file_sha256(archive) != scene.archive.sha256:
                raise recorder.fail(StageName.PREFLIGHT, _failure(
                    FailureCode.CHECKSUM_MISMATCH, StageName.PREFLIGHT, "SAFE SHA-256 re-verification failed",
                    [scene.scene_id], retryable=True,
                ))
            inputs.append(archive)
        installation = deps.probe()
        if isinstance(installation, FailureRecord):
            raise recorder.fail(StageName.PREFLIGHT, installation)
        recorder.advance(StageName.PREFLIGHT, RunState.PREFLIGHTED)

        # P2 execute.
        workspace = layout.work_attempt_dir(attempt_id)
        settings_path = SettingsRenderer().write(
            workspace / "oceanos_settings.txt", owned, inputs=inputs, output=workspace,
            runid=attempt_id, grid=grid,
        )
        outcome = deps.run_acolite(settings_path, workspace, attempt_id, lock)
        recorder.attempt = recorder.attempt.model_copy(update={"acolite_exit_code": outcome.exit_code})
        recorder.advance(StageName.EXECUTE, RunState.EXECUTED, duration_seconds=outcome.duration_seconds)

        # P3 verify: success comes from artifacts and logs, never from the exit code.
        verified = deps.verifier.verify(
            workspace=workspace, attempt_id=attempt_id, platform=overpass_id[:3],  # type: ignore[arg-type]
            release_tag=pin.release_tag, parameters=parameters.parameters, outcome=outcome,
        )
        if isinstance(verified, FailureRecord):
            raise recorder.fail(StageName.VERIFY, verified)
        outputs: AcoliteRunOutputs = verified
        recorder.advance(StageName.VERIFY, RunState.VERIFIED)

        # P4 archive (irreversible, I2).
        archive_dir = ArchiveStore(layout).commit(
            aoi_id=aoi.aoi_id, overpass_id=overpass_id, attempt=recorder.attempt, profile=profile,
            input_set=input_set, installation=installation, workspace=workspace, outputs=outputs,
        )
        archived_at = datetime.now(UTC)
        recorder.advance(StageName.ARCHIVE, RunState.ARCHIVED, archive=archive_dir.relative_to(layout.archive).as_posix())

        downstream = DownstreamProfile(
            product_set_version=products.version, quality_policy_version=TRACER_QUALITY_POLICY_VERSION,
            land_mask_version=LAND_MASK_VERSION, analysis_mask_version=NO_ANALYSIS_MASK_VERSION,
            publication_profile_version=PUBLICATION_PROFILE.profile_id,
        )
        new_release_id = release_id(attempt_id, downstream.profile_id)
        staging_root = layout.work / "staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        conform_dir = Path(tempfile.mkdtemp(prefix=".conform-", dir=staging_root))
        release_staging = Path(tempfile.mkdtemp(prefix=".release-", dir=staging_root))
        try:
            # P5 conform.
            grid_dir = grid_path.parent
            land_mask = ensure_land_mask(grid_dir, grid, settings.acolite.external_dir / GSHHG_LAND_LAYER)
            land = read_land(grid_dir, grid)
            land_ref = LandMaskRef(version=land_mask.version, sha256=land_mask.raster.sha256)
            out_of_scene = next((1 << bit.bit for bit in outputs.flag_spec.bits if bit.name == "out_of_scene"), None)
            layers: list[tuple[ConformedLayer, str, float | None]] = []
            try:
                for spec in products.specs:
                    if spec.publish != "cog" or spec.product_key not in PUBLICATION_PROFILE.published_products:
                        continue
                    role, variable, wavelength = resolve_product(outputs, spec)
                    container_ref = outputs.l2w if role == "l2w" else outputs.l2r
                    container = archive_dir / Path(container_ref.relpath).name
                    masked = spec.land_masked and spec.kind != "bitfield"
                    layer = conform_layer(
                        container, variable, conform_dir / f"{spec.product_key}.tif", grid,
                        product_key=spec.product_key, kind=spec.kind, unit=spec.unit,
                        source=LayerSource(container_role=role, container_sha256=container_ref.sha256, variable=variable),
                        out_of_scene_value=out_of_scene if spec.kind == "bitfield" else None,
                        land=land if masked else None, land_mask=land_ref if masked else None,
                        tier_root=conform_dir,
                    )
                    layers.append((layer, variable, wavelength))
            except ProductResolutionError as exc:
                raise recorder.fail(StageName.CONFORM, _failure(
                    FailureCode.ACOLITE_MISSING_VARIABLE, StageName.CONFORM, str(exc)))
            except ConformError as exc:
                scope = FailureScope.BATCH if exc.code is FailureCode.GRID_MISALIGNED else FailureScope.OBSERVATION
                raise recorder.fail(StageName.CONFORM, _failure(exc.code, StageName.CONFORM, str(exc), scope=scope))
            recorder.advance(StageName.CONFORM, RunState.CONFORMED, layers=len(layers))

            # P6 assess: Phase 2 tracer verdict.
            recorder.advance(StageName.ASSESS, RunState.ASSESSED, verdict="usable", policy=TRACER_QUALITY_POLICY_VERSION)

            # P7 package.
            try:
                assets: list[PublishedAsset] = []
                for layer, _, wavelength in layers:
                    bitfield = layer.kind == "bitfield"
                    cog_profile = PUBLICATION_PROFILE.bitfield if bitfield else PUBLICATION_PROFILE.continuous
                    target = release_staging / f"{layer.product_key}.tif"
                    write_cog(conform_dir / layer.raster.relpath, target, cog_profile)
                    assets.append(PublishedAsset(
                        product_key=layer.product_key, href=target.name, sha256=_file_sha256(target),
                        size=target.stat().st_size, media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                        roles=("data",), unit=layer.unit, nodata=layer.nodata, data_type=layer.data_type,
                        overview_resampling=cog_profile.overview_resampling, center_wavelength_nm=wavelength,
                    ))
                settings_copy = release_staging / "settings_resolved.txt"
                shutil.copy2(archive_dir / "l2r_settings.txt", settings_copy)
                assets.append(PublishedAsset(
                    product_key="settings_resolved", href=settings_copy.name, sha256=_file_sha256(settings_copy),
                    size=settings_copy.stat().st_size, media_type="text/plain", roles=("metadata",),
                ))
                published_at = datetime.now(UTC)
                scene_meta = {scene.scene_id: scene for scene in selected}
                provenance = ProvenanceRecord(
                    observation_id=observation_id, release_id=new_release_id, attempt_id=attempt_id, run_key=key,
                    scenes=tuple(
                        ProvenanceScene(
                            scene_id=scene.scene_id, source_id=scene.source_id, sha256=scene.archive.sha256,
                            processing_baseline=scene_meta[scene.scene_id].processing_baseline,
                            platform=scene_meta[scene.scene_id].platform,
                        )
                        for scene in input_set.scenes
                    ),
                    acolite=ProvenanceAcolite(
                        release_tag=pin.release_tag, commit_sha=installation.observed_commit,
                        version_attribute=outputs.acolite_version_attr,
                        settings_user_sha256=outputs.settings_user.sha256,
                        settings_resolved_sha256=outputs.settings_resolved.sha256,
                    ),
                    oceanos=ProvenanceOceanos(
                        version=oceanos.__version__, git_sha=recorder.attempt.oceanos_git_sha,
                        acolite_profile_id=profile.profile_id, downstream_profile_id=downstream.profile_id,
                        publication_profile_id=PUBLICATION_PROFILE.profile_id,
                        product_set_version=products.version, quality_policy_version=TRACER_QUALITY_POLICY_VERSION,
                    ),
                    ancillary=ProvenanceAncillary(
                        type=outputs.ancillary.ancillary_type, tier=tier, uoz=outputs.ancillary.uoz,
                        uwv=outputs.ancillary.uwv, pressure=outputs.ancillary.pressure,
                    ),
                    glint_angle_deg=outputs.glint_angle_deg,
                    products=tuple(
                        ProvenanceProduct(
                            product_key=layer.product_key, acolite_variable=variable, unit=layer.unit,
                            s2_calibrated=next(spec.s2_calibrated for spec in products.specs if spec.product_key == layer.product_key),
                            caveat=next(spec.caveat for spec in products.specs if spec.product_key == layer.product_key),
                            source_sha256=layer.source.container_sha256,
                            grid_coverage_fraction=layer.grid_coverage_fraction, land_mask=layer.land_mask,
                        )
                        for layer, variable, _ in layers
                    ),
                    timestamps=ProvenanceTimestamps(
                        acquired=max(scene.verified_at for scene in input_set.scenes),
                        archived=archived_at, published=published_at,
                    ),
                )
                provenance_path = release_staging / "provenance.json"
                provenance_path.write_text(provenance.model_dump_json(indent=2) + "\n", encoding="utf-8")
                release = Release(
                    release_id=new_release_id, observation_id=observation_id, attempt_id=attempt_id, run_key=key,
                    downstream_profile_id=downstream.profile_id, tier=tier, visibility="public",
                    assets=tuple(assets), quality=None,
                    provenance=_artifact(provenance_path, release_staging, "provenance", "application/json"),
                    supersedes=current, created_at=published_at,
                )
                (release_staging / "release.json").write_text(release.model_dump_json(indent=2) + "\n", encoding="utf-8")
                geometry_4326 = transform_geom(grid.spec.crs, "EPSG:4326", mapping(box(*grid.spec.bounds)))
                lons = [point[0] for point in geometry_4326["coordinates"][0]]
                lats = [point[1] for point in geometry_4326["coordinates"][0]]
                scene_hrefs = (
                    item.get_self_href() if item is not None else None
                    for item in (catalog.get_stac_item(scene.scene_id) for scene in input_set.scenes)
                )
                scene_items = [Path(href) for href in scene_hrefs if href is not None]
                products_aoi_dir = layout.products / aoi.aoi_id
                item = build_item(
                    release=release, overpass_id=overpass_id, aoi_id=aoi.aoi_id, datetime_utc=scene_datetime,
                    geometry=dict(geometry_4326), bbox=(min(lons), min(lats), max(lons), max(lats)),
                    release_dir=layout.release_dir(aoi.aoi_id, overpass_id, new_release_id),
                    products_aoi_dir=products_aoi_dir, flag_spec=outputs.flag_spec,
                    acolite_software=f"{pin.release_tag}@{installation.observed_commit}",
                    oceanos_software=f"{oceanos.__version__}@{recorder.attempt.oceanos_git_sha}",
                    acolite_release_tag=pin.release_tag, status="usable", scene_item_paths=scene_items,
                )
                recorder.advance(StageName.PACKAGE, RunState.PACKAGED, release_id=new_release_id)

                # P8 publish.
                release_dir = publish_release(
                    layout=layout, aoi_id=aoi.aoi_id, overpass_id=overpass_id, release_id=new_release_id,
                    staged_dir=release_staging, item=item, supersedes=current, fault=publish_fault,
                )
            except OSError as exc:
                raise recorder.fail(StageName.PUBLISH, _failure(
                    FailureCode.PUBLISH_IO_ERROR, StageName.PUBLISH, f"{type(exc).__name__}: {exc}", retryable=True))
            recorder.advance(StageName.PUBLISH, RunState.PUBLISHED, release_id=new_release_id)
        finally:
            shutil.rmtree(conform_dir, ignore_errors=True)
            if release_staging.exists():
                shutil.rmtree(release_staging, ignore_errors=True)
    return RunOneResult(
        status="published", run_key=key, release_id=new_release_id, release_dir=release_dir, attempt_id=attempt_id,
    )


def check_releases(settings: OceanosSettings) -> None:
    """Read-only reconciliation at the start of a mutating command; refuses a broken state."""
    aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
    reconcile(_layout(settings), aoi.aoi_id, repair=False)


def latest_release_dir(settings: OceanosSettings, overpass_id: str) -> Path:
    """Return the current release directory recorded by the derived STAC Item."""
    layout = _layout(settings)
    aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
    reconcile(layout, aoi.aoi_id, repair=False)
    current = current_release_id(layout, aoi.aoi_id, overpass_id)
    if current is None:
        raise ValueError(f"no current release for overpass: {overpass_id}")
    return layout.release_dir(aoi.aoi_id, overpass_id, current)
