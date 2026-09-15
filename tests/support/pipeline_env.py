"""Offline one-observation environment: fixture grid, cataloged scene and fake effects."""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import yaml
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from oceanos.aoi import load_aoi
from oceanos.catalog import LocalSceneCatalog, SceneMetadata
from oceanos.config import (
    OceanosSettings,
    load_acolite_parameter_set,
    load_config,
    load_product_set,
    load_publication_profile,
    load_quality_policy,
)
from oceanos.domain import (
    AcoliteInstallation,
    AcquiredScene,
    ArtifactRef,
    FailureRecord,
)
from oceanos.pipeline.run_one import RunOneDependencies
from oceanos.processing.grid import DeliveryGrid, GridSpec
from oceanos.storage import StorageLayout
from support.fake_acolite import FakeAcoliteRunner

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/acolite"
OVERPASS = "S2A_20260702T150741_R082"
SCENE_ID = "S2A_MSIL1C_20260702T150741_N0512_R082_T19QGV_20260702T214456"
PIN_COMMIT = "f73cbe73887c2b114d9d3c70865effee73871525"
BATHYMETRY = ROOT / "tests/fixtures/bathymetry/cudem_window.tif"


def window_grid(aoi_id: str, *, shift_columns: int = 0, shift_metres: float = 0) -> DeliveryGrid:
    window = json.loads((FIXTURES / "window.json").read_text(encoding="utf-8"))
    bounds = window["projected_bounds"]
    west = bounds["west"] + shift_columns * 10 + shift_metres
    north = bounds["north"]
    width, height = window["width"], window["height"]
    transform = from_origin(west, north, 10, 10)
    return DeliveryGrid(
        grid_id="grid-0123456789ab", aoi_id=aoi_id,
        spec=GridSpec(CRS.from_epsg(32619), 10.0, (west, north - height * 10, west + width * 10, north), width, height, transform),
        anchor=(0, 0), buffer_m=0, created_at=datetime(2026, 9, 15, tzinfo=UTC),
    )


def scene() -> SceneMetadata:
    return SceneMetadata(
        scene_id=SCENE_ID, collection="sentinel-2-l1c", platform="S2A", datetime="2026-07-02T15:07:41Z",
        geometry=mapping(box(-68, 17, -66, 19)), bbox=(-68, 17, -66, 19), cloud_cover=2,
        source_catalog="https://catalogue.example", processing_level="Level-1C", processing_baseline="05.12",
        relative_orbit=82, datatake_id="GS2A_20260702T150741_057594_N05.12", overpass_id=OVERPASS,
        mgrs_tile="19QGV", source_id="uuid-a", online=True,
    )


@dataclass
class PipelineEnv:
    root: Path
    config: Path
    settings: OceanosSettings
    layout: StorageLayout
    aoi_id: str
    grid: DeliveryGrid
    variant: str = "success"
    permissive_glint: bool = False
    calls: dict = field(default_factory=lambda: {"acquire": 0, "acolite": 0})

    @property
    def parameters(self):
        return load_acolite_parameter_set(ROOT / "configs/acolite_parameters.yaml")

    @property
    def products(self):
        return load_product_set(ROOT / "configs/products.yaml", self.parameters)

    @property
    def policy(self):
        policy = load_quality_policy(ROOT / "configs/quality.yaml", self.products)
        if self.permissive_glint:
            # The success fixture is the glint-affected scene A window; relax only the residual-glint gates.
            policy = policy.model_copy(update={
                "version": "test-permissive-glint", "max_negative_rhos_fraction": 1.0, "max_residual_swir_rhow": 1.0,
            })
        return policy

    @property
    def publication(self):
        return load_publication_profile(ROOT / "configs/publication.yaml", self.products)

    def configs(self) -> dict:
        return {"parameters": self.parameters, "products": self.products, "policy": self.policy,
                "publication": self.publication}

    def dependencies(self) -> RunOneDependencies:
        clock = itertools.count()
        start = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)

        def acquire(source: SceneMetadata) -> AcquiredScene:
            self.calls["acquire"] += 1
            content = f"fake SAFE for {source.scene_id}".encode()
            digest = sha256(content).hexdigest()
            relpath = f"sentinel2-l1c/{digest}/{source.scene_id}.zip"
            path = self.layout.raw / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return AcquiredScene(
                scene_id=source.scene_id, source_id=source.source_id or "source",
                archive=ArtifactRef(role="source", relpath=relpath, sha256=digest, size=len(content), media_type="application/zip"),
                provider_md5_verified=True, safe_members_verified=True, verified_at=start,
            )

        def probe() -> AcoliteInstallation | FailureRecord:
            return AcoliteInstallation(
                root="/opt/acolite", python_executable="/opt/acolite/python", observed_commit=PIN_COMMIT,
                config_version_line="version=20260421.0", luts_present={"S2A_MSI", "S2B_MSI", "S2C_MSI"},
                gshhg_present=True, credentials_present=True, free_disk_bytes=10**12,
            )

        def run_acolite(settings_path: Path, workspace: Path, runid: str, lock):
            self.calls["acolite"] += 1
            assert settings_path.is_file()
            return FakeAcoliteRunner(FIXTURES, self.variant).run(workspace, runid=runid)

        return RunOneDependencies(
            acquire=acquire, probe=probe, run_acolite=run_acolite, git_sha=lambda: "b" * 40,
            now=lambda: start + timedelta(seconds=next(clock)),
        )


def make_env(tmp_path: Path, monkeypatch) -> PipelineEnv:
    config = yaml.safe_load((ROOT / "configs/mvp.yaml").read_text(encoding="utf-8"))
    config["data_root"] = str(tmp_path / "data")
    config["catalog_dir"] = str(tmp_path / "catalog")
    config["aoi"]["path"] = str(ROOT / "configs/aoi/la_parguera_mvp.geojson")
    config["acolite"]["external_dir"] = str(FIXTURES)
    path = tmp_path / "mvp.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    for name in ("acolite_parameters.yaml", "products.yaml", "quality.yaml", "publication.yaml"):
        (tmp_path / name).write_text((ROOT / "configs" / name).read_text(encoding="utf-8"), encoding="utf-8")
    # Offline reference data: a CUDEM crop of the fixture window (land mask and bathymetry).
    monkeypatch.setattr("oceanos.pipeline.downstream.reference_data", lambda settings: [BATHYMETRY])
    settings = load_config(path)
    layout = StorageLayout(
        raw=settings.storage.raw, work=settings.storage.work, archive=settings.storage.archive,
        products=settings.storage.products, superseded=settings.storage.superseded, state=settings.storage.state,
    )
    aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
    grid = window_grid(aoi.aoi_id)
    grid.save(layout.grid_json(aoi.aoi_id))
    LocalSceneCatalog(settings.catalog_dir, collection_id="sentinel-2-l1c").add_scene(scene())
    return PipelineEnv(tmp_path, path, settings, layout, aoi.aoi_id, grid)
