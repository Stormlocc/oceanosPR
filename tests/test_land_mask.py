"""LandMask (DA-1) is rasterized once per grid from OCEANOS coastline polygons."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import rasterio
from support.pipeline_env import FIXTURES, window_grid

from oceanos.processing import assert_aligned
from oceanos.processing.masks import ensure_land_mask, land_mask_paths, rasterize_land

AOI_ID = "aoi-la-parguera-0123456789ab"
COASTLINE = FIXTURES / "gshhg_clip.geojson"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Land-mask tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_rasterization_matches_phase1_land_pixel_count() -> None:
    land = rasterize_land(COASTLINE, window_grid(AOI_ID))
    assert land.shape == (256, 256)
    assert int(land.sum()) == 3434  # tests/fixtures/acolite/window.json geometric_counts.land_pixels


def test_mask_is_written_aligned_recorded_and_reused(tmp_path: Path) -> None:
    grid = window_grid(AOI_ID)
    record = ensure_land_mask(tmp_path, grid, COASTLINE)
    raster, document = land_mask_paths(tmp_path)

    assert_aligned(raster, grid.spec)
    assert record.grid_id == grid.grid_id and record.land_pixels == 3434
    assert document.is_file() and record.coastline_source.version == "2.3.7"
    with rasterio.open(raster) as dataset:
        assert dataset.dtypes[0] == "uint8" and int(dataset.read(1).sum()) == 3434
    modified = raster.stat().st_mtime_ns

    again = ensure_land_mask(tmp_path, grid, tmp_path / "coastline-not-needed.shp")
    assert again == record
    assert raster.stat().st_mtime_ns == modified


def test_mask_for_another_grid_is_rebuilt_and_missing_coastline_fails(tmp_path: Path) -> None:
    ensure_land_mask(tmp_path, window_grid(AOI_ID), COASTLINE)
    shifted = window_grid(AOI_ID, shift_columns=300).model_copy(update={"grid_id": "grid-ba9876543210"})

    rebuilt = ensure_land_mask(tmp_path, shifted, COASTLINE)
    assert rebuilt.grid_id == "grid-ba9876543210"

    with pytest.raises(FileNotFoundError):
        ensure_land_mask(tmp_path / "other", shifted, tmp_path / "missing.shp")
