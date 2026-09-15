"""LandMask (DA-1, amended at the DA-6 review): CUDEM elevation > 0 m, built once per grid."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import rasterio
from support.pipeline_env import BATHYMETRY, window_grid

from oceanos.processing import assert_aligned
from oceanos.processing.masks import (
    elevation_on_grid,
    ensure_land_mask,
    land_from_elevation,
    land_mask_paths,
)

AOI_ID = "aoi-la-parguera-0123456789ab"
# CUDEM-derived land in the Phase 1 fixture window; GSHHG gave 3434 (window.json) because its
# coastline is displaced ≈ 380 m south here.
FIXTURE_LAND_PIXELS = 539


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Land-mask tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_land_is_positive_cudem_elevation_on_the_grid() -> None:
    elevation = elevation_on_grid([BATHYMETRY], window_grid(AOI_ID))
    land = land_from_elevation(elevation)
    assert land.shape == (256, 256)
    assert int(land.sum()) == FIXTURE_LAND_PIXELS
    assert (elevation[land] > 0).all() and (elevation[~land] <= 0).all()


def test_mask_is_written_aligned_recorded_and_reused(tmp_path: Path) -> None:
    grid = window_grid(AOI_ID)
    record = ensure_land_mask(tmp_path, grid, [BATHYMETRY])
    raster, document = land_mask_paths(tmp_path)

    assert_aligned(raster, grid.spec)
    assert record.grid_id == grid.grid_id and record.land_pixels == FIXTURE_LAND_PIXELS
    assert document.is_file() and "CUDEM" in record.coastline_source.dataset
    assert record.coastline_source.version == "2022v2" and record.version == "2"
    with rasterio.open(raster) as dataset:
        assert dataset.dtypes[0] == "uint8" and int(dataset.read(1).sum()) == FIXTURE_LAND_PIXELS
    modified = raster.stat().st_mtime_ns

    again = ensure_land_mask(tmp_path, grid, [tmp_path / "tiles-not-needed.tif"])
    assert again == record
    assert raster.stat().st_mtime_ns == modified


def test_mask_for_another_grid_is_rebuilt_and_missing_tiles_fail(tmp_path: Path) -> None:
    ensure_land_mask(tmp_path, window_grid(AOI_ID), [BATHYMETRY])
    shifted = window_grid(AOI_ID, shift_columns=10).model_copy(update={"grid_id": "grid-ba9876543210"})

    rebuilt = ensure_land_mask(tmp_path, shifted, [BATHYMETRY])
    assert rebuilt.grid_id == "grid-ba9876543210"

    with pytest.raises(FileNotFoundError):
        ensure_land_mask(tmp_path / "other", shifted, [tmp_path / "missing.tif"])
