"""Synthetic rasters verify geometry, resampling, nodata and exact alignment."""

import json
import socket

import numpy as np
import pytest
import rasterio
from pyproj import CRS as Projection
from rasterio.crs import CRS
from rasterio.transform import Affine, array_bounds, from_origin
from rasterio.warp import transform_bounds
from shapely.geometry import Polygon, box

from oceanos.aoi import AOI
from oceanos.processing import (
    GridSpec,
    assert_aligned,
    build_grid,
    normalize_band,
)

CRS_UTM = "EPSG:32619"


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


@pytest.mark.parametrize("crs,resolution,buffer", [("EPSG:4326", 10, 0), (CRS_UTM, 0, 0), (CRS_UTM, 10, -1)])
def test_invalid_grid_settings(tmp_path, crs, resolution, buffer):
    source = write_raster(tmp_path / "reference.tif", np.ones((20, 20), dtype="uint16"))
    with pytest.raises(ValueError):
        build_grid(source, aoi(box(500020, 40, 500180, 180)), target_crs=crs, resolution=resolution, buffer_m=buffer)


def test_gridspec_rejects_inconsistent_bounds():
    with pytest.raises(ValueError, match="bounds"):
        GridSpec(CRS.from_string(CRS_UTM), 10, (0, 0, 1, 1), 4, 4, from_origin(500000, 200, 10, 10))
