"""P5 conformance copies archived NetCDF layers onto the delivery grid without resampling."""

from __future__ import annotations

import socket
import warnings
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
import rasterio
from support.pipeline_env import FIXTURES, window_grid

from oceanos.domain import FailureCode, LandMaskRef, LayerSource
from oceanos.processing import ConformError, assert_aligned, conform_layer
from oceanos.processing.masks import rasterize_land

AOI_ID = "aoi-la-parguera-0123456789ab"
L2W = FIXTURES / "success/S2A_MSI_2026_07_02_15_08_19_T19QGV_L2W.nc"
TURBIDITY = "TUR_Nechad2016_665"
OUT_OF_SCENE = 16
SOURCE = LayerSource(container_role="l2w", container_sha256="0" * 64, variable=TURBIDITY)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Conformance tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _source(variable: str) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with rasterio.open(f'NETCDF:"{L2W}":{variable}') as dataset:
            return dataset.read(1, masked=True)


def _continuous(destination: Path, grid, **kwargs):
    return conform_layer(
        L2W, TURBIDITY, destination, grid, product_key="tur_nechad2016", kind="continuous",
        unit="FNU", source=SOURCE, tier_root=destination.parent, **kwargs,
    )


def _flags(destination: Path, grid):
    return conform_layer(
        L2W, "l2_flags", destination, grid, product_key="l2_flags", kind="bitfield", unit=None,
        source=SOURCE.model_copy(update={"variable": "l2_flags"}), out_of_scene_value=OUT_OF_SCENE,
        tier_root=destination.parent,
    )


def test_aligned_water_product_is_copied_and_nan_on_every_land_pixel(tmp_path: Path) -> None:
    grid = window_grid(AOI_ID)
    land = rasterize_land(FIXTURES / "gshhg_clip.geojson", grid)
    reference = LandMaskRef(version="1", sha256="1" * 64)
    layer = _continuous(tmp_path / "tur.tif", grid, land=land, land_mask=reference)

    assert_aligned(tmp_path / "tur.tif", grid.spec)
    with rasterio.open(tmp_path / "tur.tif") as dataset:
        values = dataset.read(1)
        assert dataset.dtypes[0] == "float32" and np.isnan(dataset.nodata)
        assert dataset.units[0] == "FNU"
    source = _source(TURBIDITY).astype("float32").filled(np.nan)
    assert np.isnan(values[land]).all()
    water = ~land
    np.testing.assert_array_equal(values[water], source[water])
    assert layer.grid_coverage_fraction == 1.0 and layer.method == "copy"
    assert layer.land_mask == reference and layer.raster.relpath == "tur.tif"
    assert layer.raster.sha256 == sha256((tmp_path / "tur.tif").read_bytes()).hexdigest()


def test_bitfield_is_copied_exactly_and_never_land_masked(tmp_path: Path) -> None:
    grid = window_grid(AOI_ID)
    layer = _flags(tmp_path / "l2_flags.tif", grid)

    with rasterio.open(tmp_path / "l2_flags.tif") as dataset:
        assert dataset.dtypes[0] == "int32"
        np.testing.assert_array_equal(dataset.read(1), _source("l2_flags").filled(OUT_OF_SCENE))
    assert layer.land_mask is None and layer.nodata is None
    with pytest.raises(ValueError, match="never land-masked"):
        conform_layer(
            L2W, "l2_flags", tmp_path / "x.tif", grid, product_key="l2_flags", kind="bitfield", unit=None,
            source=SOURCE, out_of_scene_value=OUT_OF_SCENE, land=np.zeros((256, 256), bool), tier_root=tmp_path,
        )


def test_partial_extent_uses_nan_and_out_of_scene_flag_and_records_coverage(tmp_path: Path) -> None:
    grid = window_grid(AOI_ID, shift_columns=10)
    continuous = _continuous(tmp_path / "tur.tif", grid)
    flags = _flags(tmp_path / "l2_flags.tif", grid)

    with rasterio.open(tmp_path / "tur.tif") as dataset:
        values = dataset.read(1)
    with rasterio.open(tmp_path / "l2_flags.tif") as dataset:
        bits = dataset.read(1)
    assert np.isnan(values[:, 246:]).all()
    assert (bits[:, 246:] == OUT_OF_SCENE).all()
    np.testing.assert_array_equal(bits[:, :246], _source("l2_flags").filled(OUT_OF_SCENE)[:, 10:])
    assert continuous.grid_coverage_fraction == flags.grid_coverage_fraction == 246 / 256


def test_misaligned_and_disjoint_sources_fail_with_grid_codes(tmp_path: Path) -> None:
    with pytest.raises(ConformError) as misaligned:
        _continuous(tmp_path / "tur.tif", window_grid(AOI_ID, shift_metres=5))
    assert misaligned.value.code is FailureCode.GRID_MISALIGNED

    with pytest.raises(ConformError) as disjoint:
        _continuous(tmp_path / "tur.tif", window_grid(AOI_ID, shift_columns=400))
    assert disjoint.value.code is FailureCode.GRID_NO_INTERSECTION
    assert not (tmp_path / "tur.tif").exists()
