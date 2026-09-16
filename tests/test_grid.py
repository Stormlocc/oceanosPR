"""AOI identity and the scene-independent delivery grid are deterministic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin

from oceanos.aoi import load_aoi
from oceanos.processing.grid import DeliveryGrid, GridSpec, build_delivery_grid

ROOT = Path(__file__).resolve().parents[1]


def test_delivery_grid_is_stable_and_anchored_to_ten_metre_lines(tmp_path: Path) -> None:
    aoi = load_aoi(ROOT / "configs/aoi/la_parguera_mvp.geojson", name="La Parguera — MVP example")
    first = build_delivery_grid(aoi)
    second = build_delivery_grid(aoi)
    assert first.grid_id == second.grid_id
    assert first.aoi_id == second.aoi_id == aoi.aoi_id
    assert first.spec.crs.to_epsg() == 32619
    assert first.spec.resolution == 10
    assert first.anchor == (0, 0)
    assert all(value % 10 == 0 for value in first.spec.bounds)
    path = tmp_path / "grid.json"
    first.save(path)
    assert DeliveryGrid.load(path) == first
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["grid_id"] == first.grid_id
    assert document["schema_version"] == "1.0"


def test_aoi_id_changes_with_geometry_not_projection() -> None:
    source = load_aoi(ROOT / "tests/fixtures/aoi.geojson", name="Test AOI")
    projected = load_aoi(ROOT / "tests/fixtures/aoi.geojson", name="Test AOI", target_crs="EPSG:3857")
    assert source.aoi_id == projected.aoi_id


def test_gridspec_rejects_inconsistent_bounds() -> None:
    with pytest.raises(ValueError, match="bounds"):
        GridSpec(CRS.from_string("EPSG:32619"), 10, (0, 0, 1, 1), 4, 4, from_origin(500000, 200, 10, 10))
