"""T6: a usable observation publishes every product; an unusable one publishes a restricted release."""

from __future__ import annotations

import importlib.util
import json
import socket
import warnings
from pathlib import Path

import pytest
import rasterio
from support.pipeline_env import FIXTURES, OVERPASS, ROOT, make_env

from oceanos.domain import QualityReport, Release
from oceanos.pipeline import downstream
from oceanos.pipeline.run_one import run_one

COG_PRODUCTS = {"tur_nechad2016", "spm_nechad2016", "chl_re_gons740", "fai", "fait", "ndvi", "l2_flags", "true_colour"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Visibility tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _verifier():
    spec = importlib.util.spec_from_file_location("verify_release", ROOT / "scripts/verify_release.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _data_assets(release_dir: Path) -> set[str]:
    release = Release.model_validate_json((release_dir / "release.json").read_text(encoding="utf-8"))
    return {asset.product_key for asset in release.assets if "metadata" not in asset.roles}


def test_usable_variant_publishes_all_eight_cog_products(tmp_path: Path, monkeypatch) -> None:
    env = make_env(tmp_path, monkeypatch)
    result = run_one(env.settings, OVERPASS, **env.configs(), dependencies=env.dependencies())

    assert result.visibility == "public"
    assert _data_assets(result.release_dir) == COG_PRODUCTS
    with rasterio.open(result.release_dir / "true_colour.tif") as dataset:
        assert (dataset.count, dataset.dtypes[0], dataset.overviews(1) != []) == (3, "uint8", True)
    assert _verifier().release_errors(result.release_dir) == []


def test_cloudy_variant_publishes_a_restricted_release(tmp_path: Path, monkeypatch) -> None:
    """The Phase 1 ``cloudy/`` crop holds only l2_flags and turbidity, so it cannot yield the full product
    set; its real cloud flags (cirrus over ~95 % of the window) replace the success run's flags at P5."""
    env = make_env(tmp_path, monkeypatch)
    cloudy_l2w = next((FIXTURES / "cloudy").glob("*_L2W.nc"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with rasterio.open(f'NETCDF:"{cloudy_l2w}":l2_flags') as dataset:
            cloudy_flags = dataset.read(1)
    real_conform = downstream.conform_layer

    def conform_with_cloudy_flags(*args, **kwargs):
        layer = real_conform(*args, **kwargs)
        if kwargs.get("product_key") == "l2_flags":
            path = kwargs["tier_root"] / layer.raster.relpath
            with rasterio.open(path, "r+") as dataset:
                dataset.write(cloudy_flags.astype("int32"), 1)
        return layer

    monkeypatch.setattr(downstream, "conform_layer", conform_with_cloudy_flags)
    result = run_one(env.settings, OVERPASS, **env.configs(), dependencies=env.dependencies())

    assert result.visibility == "restricted"
    assert _data_assets(result.release_dir) == {"true_colour", "l2_flags"}
    assert not (result.release_dir / "tur_nechad2016.tif").exists()
    report = QualityReport.model_validate_json((result.release_dir / "quality.json").read_text(encoding="utf-8"))
    assert report.verdict.value == "unusable" and "quality.below_valid_fraction" in report.reasons
    series = json.loads((result.release_dir / "series.json").read_text(encoding="utf-8"))["rows"]
    assert series and all(row["statistics"] is None and row["status"] == "no_usable_observation" for row in series)
    item = json.loads((env.layout.products / env.aoi_id / "stac/items" / f"{OVERPASS}.json").read_text(encoding="utf-8"))
    assert item["properties"]["oceanos:status"] == "no_usable_observation"
    assert item["properties"]["oceanos:visibility"] == "restricted"
    assert set(item["assets"]) == {"true_colour", "l2_flags", "settings_resolved"}
    assert _verifier().release_errors(result.release_dir) == []
