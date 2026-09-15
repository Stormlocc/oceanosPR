"""COG profiles, release contents, provenance and derived STAC for one published observation."""

from __future__ import annotations

import importlib.util
import json
import socket
from pathlib import Path

import numpy as np
import pytest
import rasterio
from support.pipeline_env import OVERPASS, ROOT, make_env

from oceanos.domain import ProvenanceRecord, Release
from oceanos.pipeline.run_one import run_one
from oceanos.publishing import BITFIELD_COG, CONTINUOUS_COG, write_cog
from oceanos.publishing.cog import overview_count


def _verify_release_module():
    spec = importlib.util.spec_from_file_location("verify_release", ROOT / "scripts/verify_release.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Publication tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def published(tmp_path: Path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    result = run_one(env.settings, OVERPASS, parameters=env.parameters, products=env.products, dependencies=env.dependencies())
    return env, result


def _write(path: Path, data: np.ndarray) -> Path:
    with rasterio.open(
        path, "w", driver="GTiff", count=1, width=data.shape[1], height=data.shape[0], dtype=data.dtype,
        crs="EPSG:32619", transform=rasterio.transform.from_origin(700000, 2000000, 10, 10),
    ) as dataset:
        dataset.write(data, 1)
    return path


def test_cog_profiles_force_overviews_and_keep_bitfield_values(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    continuous = _write(tmp_path / "c.tif", rng.random((300, 300), dtype="float32"))
    flags = _write(tmp_path / "f.tif", rng.choice(np.array([0, 1, 16, 33], dtype="int32"), size=(300, 300)))

    write_cog(continuous, tmp_path / "c_cog.tif", CONTINUOUS_COG)
    write_cog(flags, tmp_path / "f_cog.tif", BITFIELD_COG)

    with rasterio.open(tmp_path / "c_cog.tif") as dataset:
        assert dataset.overviews(1) and dataset.tags(ns="IMAGE_STRUCTURE")["PREDICTOR"] == "3"
    with rasterio.open(tmp_path / "f_cog.tif") as dataset:
        assert dataset.tags(ns="IMAGE_STRUCTURE")["PREDICTOR"] == "2"
        overview = dataset.read(1, out_shape=(150, 150))
        assert set(np.unique(overview)) <= {0, 1, 16, 33}
    assert overview_count(256, 256, 256) == 1 and overview_count(1602, 1125, 256) == 3
    with pytest.raises(ValueError):
        write_cog(flags, tmp_path / "wrong.tif", CONTINUOUS_COG)


def test_release_directory_contents_hashes_and_verifier(published) -> None:
    _, result = published
    names = sorted(path.name for path in result.release_dir.iterdir())
    assert names == ["l2_flags.tif", "provenance.json", "release.json", "settings_resolved.txt", "tur_nechad2016.tif"]

    release = Release.model_validate_json((result.release_dir / "release.json").read_text(encoding="utf-8"))
    assert release.release_id == result.release_id and release.visibility == "public"
    assert {asset.product_key for asset in release.assets} == {"tur_nechad2016", "l2_flags", "settings_resolved"}
    flags = next(asset for asset in release.assets if asset.product_key == "l2_flags")
    assert (flags.data_type, flags.overview_resampling, flags.nodata) == ("int32", "MODE", None)
    turbidity = next(asset for asset in release.assets if asset.product_key == "tur_nechad2016")
    assert (turbidity.unit, turbidity.nodata, turbidity.center_wavelength_nm) == ("FNU", "nan", 665.0)

    assert _verify_release_module().release_errors(result.release_dir) == []
    assert result.release_dir.stat().st_mode & 0o777 == 0o755
    assert all(path.stat().st_mode & 0o777 == 0o644 for path in result.release_dir.iterdir())


def test_provenance_records_lineage_and_land_mask(published) -> None:
    env, result = published
    provenance = ProvenanceRecord.model_validate_json((result.release_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance.run_key == result.run_key and provenance.attempt_id == result.attempt_id
    assert provenance.acolite.release_tag == "20260421.0"
    assert provenance.acolite.version_attribute == "20260421.0"
    assert [scene.source_id for scene in provenance.scenes] == ["uuid-a"]
    by_key = {product.product_key: product for product in provenance.products}
    assert by_key["tur_nechad2016"].land_mask is not None and by_key["l2_flags"].land_mask is None
    assert by_key["tur_nechad2016"].acolite_variable == "TUR_Nechad2016_665"
    assert str(env.root) not in (result.release_dir / "provenance.json").read_text(encoding="utf-8")
    assert str(env.root) not in (result.release_dir / "release.json").read_text(encoding="utf-8")


def test_stac_item_points_at_current_release_and_validates(published) -> None:
    env, result = published
    item_path = env.layout.products / env.aoi_id / "stac/items" / f"{OVERPASS}.json"
    item = json.loads(item_path.read_text(encoding="utf-8"))
    verifier = _verify_release_module()

    assert verifier.stac_item_errors(item) == []
    assert item["properties"]["oceanos:release_id"] == result.release_id
    assert item["properties"]["processing:level"] == "L2W"
    assert [bit["offset"] for bit in item["assets"]["l2_flags"]["classification:bitfields"]] == [0, 1, 2, 3, 4, 5, 6]
    assert item["assets"]["tur_nechad2016"]["bands"][0]["eo:center_wavelength"] == pytest.approx(0.665)
    assert "settings_resolved" in item["assets"] and item["assets"]["settings_resolved"]["roles"] == ["metadata"]
    for asset in item["assets"].values():
        assert not Path(asset["href"]).is_absolute()
        assert (item_path.parent / asset["href"]).resolve().is_file()
    rels = {link["rel"] for link in item["links"]}
    assert {"derived_from", "processing-software", "alternate", "collection"} <= rels

    broken = {**item, "properties": {**item["properties"], "datetime": "not a date"}}
    broken.pop("bbox")
    assert verifier.stac_item_errors({**broken, "stac_version": 11}) != []
