"""Synthetic rasters verify geometry, resampling, nodata and exact alignment."""

import hashlib
import json
import socket
from pathlib import Path

import numpy as np
import pytest
import rasterio
import yaml
from pyproj import CRS as Projection
from rasterio.crs import CRS
from rasterio.transform import Affine, array_bounds, from_origin
from rasterio.warp import transform_bounds
from shapely.geometry import Polygon, box

from oceanos.aoi import AOI
from oceanos.catalog import LocalSceneCatalog, SceneAsset, SceneMetadata
from oceanos.ingestion import MaterializationError
from oceanos.ingestion.fetch import MaterializedAsset, SceneManifest
from oceanos.processing import (
    GridSpec,
    assert_aligned,
    build_grid,
    normalize_band,
    normalize_scene,
)

CRS_UTM = "EPSG:32619"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Normalization tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def write_raster(path, data, *, transform=None, crs=CRS_UTM, nodata=0, mask=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", count=1, width=data.shape[1], height=data.shape[0],
                       dtype=data.dtype, crs=crs, transform=transform or from_origin(500000, 200, 10, 10),
                       nodata=nodata) as dataset:
        dataset.write(data, 1)
        if mask is not None:
            dataset.write_mask(mask)
    return path


def aoi(geometry):
    return AOI("Synthetic AOI", geometry, Projection.from_user_input(CRS_UTM))


def grid(width=4, height=4, resolution=10, west=500000, north=200):
    transform = from_origin(west, north, resolution, resolution)
    return GridSpec(CRS.from_string(CRS_UTM), resolution, array_bounds(height, width, transform), width, height, transform)


def test_grid_same_crs_dimensions_transform_bounds_and_buffer(tmp_path):
    reference = write_raster(tmp_path / "B02.tif", np.ones((20, 20), dtype="uint16"))
    region = aoi(box(500021, 41, 500179, 179))
    target = build_grid(reference, region)
    assert target.crs == CRS.from_string(CRS_UTM)
    assert target.resolution == 10
    assert (target.width, target.height) == (16, 14)
    assert target.transform == Affine(10, 0, 500020, 0, -10, 180)
    assert target.bounds == (500020, 40, 500180, 180)
    expanded = build_grid(reference, region, buffer_m=10)
    assert expanded.bounds == (500010, 30, 500190, 190)
    assert (expanded.width, expanded.height) == (18, 16)
    fine = build_grid(reference, region, resolution=5)
    assert fine.resolution == 5
    assert (fine.width, fine.height) == (32, 28)
    assert fine.bounds == target.bounds


def test_grid_exact_reference_alignment_avoids_extra_border(tmp_path):
    reference = write_raster(tmp_path / "reference.tif", np.ones((20, 20), dtype="uint16"))
    target = build_grid(reference, aoi(box(500020, 40, 500180, 180)))
    assert target.bounds == (500020, 40, 500180, 180)
    assert target.width == 16
    assert target.height == 14


def test_same_crs_values_scale_offset_and_nodata(tmp_path):
    data = np.array([[0, 10, 20, 30], [40, 50, 60, 70], [80, 90, 100, 110], [120, 130, 140, 150]], dtype="uint16")
    source = write_raster(tmp_path / "source.tif", data)
    with rasterio.open(source, "r+") as src:
        src.scales = (0.0001,)
        src.offsets = (-0.1,)
    output = tmp_path / "normalized.tif"
    report = normalize_band(source, output, grid())
    assert_aligned(output, grid())
    with rasterio.open(output) as dataset:
        actual = dataset.read(1)
        assert np.isnan(dataset.nodata)
        assert np.isnan(actual[0, 0])
        np.testing.assert_array_equal(actual[1:], data[1:])
        assert dataset.scales == (0.0001,)
        assert dataset.offsets == (-0.1,)
        assert dataset.tags()["resampling_method"] == "bilinear"
        assert json.loads(dataset.tags()["native_resolution"]) == [10, 10]
    assert report["processing_resolution"] == 10


def test_bilinear_and_nearest_for_different_resolution(tmp_path):
    source = write_raster(tmp_path / "twenty.tif", np.array([[10, 20], [30, 40]], dtype="uint16"),
                          transform=from_origin(500000, 200, 20, 20))
    target = grid()
    continuous = tmp_path / "continuous.tif"
    categorical = tmp_path / "categorical.tif"
    report = normalize_band(source, continuous, target)
    category_report = normalize_band(source, categorical, target, categorical=True)
    assert report["native_resolution"] == [20, 20]
    assert report["processing_resolution"] == 10
    assert report["resampling_method"] == "bilinear"
    assert category_report["resampling_method"] == "nearest"
    with rasterio.open(continuous) as dataset:
        assert dataset.read(1)[1, 1] == pytest.approx(17.5)
    with rasterio.open(categorical) as dataset:
        assert set(np.unique(dataset.read(1))) == {10, 20, 30, 40}
    with pytest.raises(ValueError, match="Categories require nearest"):
        normalize_band(source, tmp_path / "invalid.tif", target, categorical=True, resampling_method="bilinear")
    assert_aligned(continuous, target)
    assert_aligned(categorical, target)


def test_source_different_crs_reprojects_to_same_grid(tmp_path):
    target = grid(width=20, height=20)
    west, south, east, north = transform_bounds(CRS_UTM, "EPSG:4326", *target.bounds)
    source = write_raster(tmp_path / "geographic.tif", np.full((20, 20), 100, dtype="uint16"), crs="EPSG:4326",
                          transform=from_origin(west, north, (east - west) / 20, (north - south) / 20))
    output = tmp_path / "projected.tif"
    normalize_band(source, output, target)
    assert_aligned(output, target)
    with rasterio.open(output) as dataset:
        assert dataset.read(1)[10, 10] == pytest.approx(100)
        assert dataset.tags()["native_resolution_units"] == "degree"
    new_grid = build_grid(source, aoi(box(500020, 40, 500180, 180)), target_crs="EPSG:3857")
    assert new_grid.crs == CRS.from_epsg(3857)
    assert new_grid.resolution == 10
    assert new_grid.width > 0 and new_grid.height > 0


def test_nodata_does_not_contaminate_bilinear_interpolation(tmp_path):
    source = write_raster(tmp_path / "source.tif", np.array([[0, 100], [100, 100]], dtype="uint16"),
                          transform=from_origin(500000, 200, 20, 20))
    output = tmp_path / "normalized.tif"
    normalize_band(source, output, grid())
    with rasterio.open(output) as dataset:
        data = dataset.read(1)
        assert np.isnan(data[0, 0])
        assert np.allclose(data[np.isfinite(data)], 100)


def test_zero_without_nodata_stays_valid_and_outside_coverage_is_masked(tmp_path):
    source = write_raster(tmp_path / "zeros.tif", np.zeros((4, 4), dtype="uint16"), nodata=None)
    output = tmp_path / "normalized.tif"
    target = grid(width=6, height=6, west=499990, north=210)
    normalize_band(source, output, target)
    with rasterio.open(output) as dataset:
        data = dataset.read(1)
        np.testing.assert_array_equal(data[1:5, 1:5], 0)
        assert np.isnan(data[0, :]).all()
        assert np.isnan(data[:, 0]).all()


def test_internal_mask_and_aoi_hole_are_respected(tmp_path):
    mask = np.full((4, 4), 255, dtype="uint8")
    mask[0, 0] = 0
    source = write_raster(tmp_path / "masked.tif", np.full((4, 4), 100, dtype="uint16"), nodata=None, mask=mask)
    polygon = Polygon(box(500000, 160, 500040, 200).exterior.coords,
                      [box(500010, 170, 500020, 180).exterior.coords])
    output = tmp_path / "normalized.tif"
    normalize_band(source, output, grid(), clip_geometry=polygon)
    with rasterio.open(output) as dataset:
        data = dataset.read(1)
        assert np.isnan(data[0, 0])
        assert np.isnan(data[2, 1])
        assert data[0, 1] == 100


@pytest.fixture
def materialized_scene(tmp_path):
    scene_id = "S2_SYNTHETIC"
    directory = tmp_path / "raw" / "sentinel2" / scene_id
    paths, records, assets = {}, {}, {}
    for band in ("B02", "B03", "B04", "B08", "B11"):
        resolution, size = (20, 10) if band == "B11" else (10, 20)
        path = write_raster(directory / f"{band}.tif", np.full((size, size), 100, dtype="uint16"),
                            transform=from_origin(500000, 200, resolution, resolution))
        url = f"https://assets.example/{band}.tif"
        assets[band] = SceneAsset(href=url, file_size=path.stat().st_size)
        records[band] = MaterializedAsset(
            asset_key=band, source_url=url, download_timestamp="2024-01-01T00:00:00Z",
            local_path=path.name, file_size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        paths[band] = path
    region = aoi(box(500020, 40, 500180, 180))
    scene = SceneMetadata(scene_id=scene_id, collection="sentinel-2-l2a", datetime="2024-01-01T00:00:00Z",
                          geometry=region.to_geojson()["geometry"], bbox=(0, 0, 1, 1), assets=assets,
                          source_catalog="https://catalog.example")
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    manifest = SceneManifest(scene_id=scene_id, status="complete", assets=records)
    (directory / "manifest.json").write_text(manifest.model_dump_json())
    return catalog, scene_id, region, paths


def test_critical_all_normalized_rasters_share_exact_grid(materialized_scene, tmp_path):
    catalog, scene_id, region, paths = materialized_scene
    raw_before = {band: path.read_bytes() for band, path in paths.items()}
    report = normalize_scene(catalog, scene_id, region, raw_dir=tmp_path / "raw", intermediate_dir=tmp_path / "intermediate")
    output = Path(report["output_directory"])
    signatures = []
    for band in paths:
        with rasterio.open(output / f"{band}.tif") as dataset:
            signatures.append((dataset.crs, dataset.transform, dataset.width, dataset.height, tuple(dataset.bounds)))
    assert all(signature == signatures[0] for signature in signatures)
    assert signatures[0] == (CRS.from_string(CRS_UTM), Affine(10, 0, 500020, 0, -10, 180), 16, 14, (500020, 40, 500180, 180))
    assert report["reference_band"] == "B02"
    assert report["bands"]["B11"]["native_resolution"] == [20, 20]
    assert report["output_size_bytes"] == sum(path.stat().st_size for path in output.glob("*.tif"))
    assert report["uncompressed_size_bytes"] == 16 * 14 * 5 * 4
    assert report["peak_process_memory_bytes"] > 0
    assert json.loads((output / "manifest.json").read_text()) == report
    assert raw_before == {band: path.read_bytes() for band, path in paths.items()}


def test_partial_or_corrupt_materialization_is_rejected(materialized_scene, tmp_path):
    catalog, scene_id, region, paths = materialized_scene
    paths["B11"].write_bytes(b"partial")
    with pytest.raises(MaterializationError, match="integrity"):
        normalize_scene(catalog, scene_id, region, raw_dir=tmp_path / "raw", intermediate_dir=tmp_path / "intermediate")
    assert not (tmp_path / "intermediate" / scene_id / "normalized").exists()


def test_failure_preserves_previous_aligned_set(materialized_scene, tmp_path, monkeypatch):
    catalog, scene_id, region, _paths = materialized_scene
    kwargs = {"raw_dir": tmp_path / "raw", "intermediate_dir": tmp_path / "intermediate"}
    result = normalize_scene(catalog, scene_id, region, **kwargs)
    output = Path(result["output_directory"])
    original = {path.name: path.read_bytes() for path in output.iterdir()}
    actual = normalize_band
    def fail_second(source, destination, grid, **kwargs):
        if source.name == "B03.tif":
            raise OSError("simulated disk failure")
        return actual(source, destination, grid, **kwargs)
    monkeypatch.setattr("oceanos.processing.normalize.normalize_band", fail_second)
    with pytest.raises(OSError):
        normalize_scene(catalog, scene_id, region, resolution=20, **kwargs)
    assert original == {path.name: path.read_bytes() for path in output.iterdir()}
    assert not list(output.parent.glob(".normalized-*"))


def test_cli_config_resolution_and_report(materialized_scene, tmp_path, capsys):
    from oceanos.__main__ import main
    catalog, scene_id, region, _paths = materialized_scene
    aoi_path = tmp_path / "aoi.geojson"
    region.save(aoi_path)
    config = yaml.safe_load((ROOT / "configs/mvp.yaml").read_text())
    config["data_root"] = str(tmp_path)
    config["catalog_dir"] = str(catalog.directory)
    config["aoi"] = {"name": "Synthetic", "path": str(aoi_path), "target_crs": CRS_UTM}
    config["normalization"] = {"target_resolution": 5, "buffer_m": 0, "continuous_resampling": "nearest"}
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    assert main(["process", "normalize", scene_id, "--config", str(config_path)]) == 0
    output = capsys.readouterr().out
    assert "32 x 28 pixels" in output
    assert "5.0 m" in output
    assert "Peak process RSS:" in output
    assert "Raster size on disk:" in output
    report = json.loads((tmp_path / "intermediate" / scene_id / "normalized/manifest.json").read_text())
    assert all(band["resampling_method"] == "nearest" for band in report["bands"].values())


@pytest.mark.parametrize("crs,resolution,buffer", [("EPSG:4326", 10, 0), (CRS_UTM, 0, 0), (CRS_UTM, 10, -1)])
def test_invalid_grid_settings(tmp_path, crs, resolution, buffer):
    source = write_raster(tmp_path / "reference.tif", np.ones((20, 20), dtype="uint16"))
    with pytest.raises(ValueError):
        build_grid(source, aoi(box(500020, 40, 500180, 180)), target_crs=crs, resolution=resolution, buffer_m=buffer)


def test_gridspec_rejects_inconsistent_bounds():
    with pytest.raises(ValueError, match="bounds"):
        GridSpec(CRS.from_string(CRS_UTM), 10, (0, 0, 1, 1), 4, 4, from_origin(500000, 200, 10, 10))
