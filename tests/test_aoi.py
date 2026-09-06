"""AOI behavior using synthetic geometries only."""

import json
from pathlib import Path

import pytest
from pyproj import CRS
from shapely.geometry import Polygon

from oceanos.aoi import AOI, AOIError, get_bounds, load_aoi, reproject_aoi, validate_aoi

FIXTURE = Path(__file__).parent / "fixtures" / "aoi.geojson"


def write_geojson(tmp_path, document):
    path = tmp_path / "aoi.geojson"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_valid_polygon_and_bounds():
    aoi = load_aoi(FIXTURE)
    assert aoi.name == "Synthetic test square"
    assert aoi.crs == CRS.from_epsg(4326)
    assert aoi.geometry.geom_type == "Polygon"
    assert validate_aoi(aoi) is True
    assert get_bounds(aoi) == (0, 0, 1, 1)


def test_multipolygon(tmp_path):
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0, 0], [1, 0], [1, 1], [0, 0]]],
            [[[2, 2], [3, 2], [3, 3], [2, 2]]],
        ],
    }
    aoi = load_aoi(write_geojson(tmp_path, geometry), name="Islands")
    assert aoi.geometry.geom_type == "MultiPolygon"
    assert len(aoi.geometry.geoms) == 2
    assert get_bounds(aoi) == (0, 0, 3, 3)
    assert load_aoi(write_geojson(tmp_path, aoi.to_geojson())).geometry.equals(aoi.geometry)


def test_reprojection_and_serialization(tmp_path):
    original = load_aoi(FIXTURE)
    projected = reproject_aoi(original, "EPSG:3857")
    assert projected.crs == CRS.from_epsg(3857)
    assert get_bounds(projected) == pytest.approx((0, 0, 111319.490793, 111325.142866))
    assert get_bounds(original) == (0, 0, 1, 1)
    assert projected.name == original.name
    restored = reproject_aoi(projected, "EPSG:4326")
    assert restored.geometry.equals_exact(original.geometry, tolerance=1e-9)
    output = tmp_path / "serialized.geojson"
    projected.save(output)
    loaded = load_aoi(output)
    assert loaded.crs == CRS.from_epsg(4326)
    assert loaded.name == original.name
    assert loaded.geometry.equals_exact(original.geometry, tolerance=1e-9)
    assert load_aoi(FIXTURE, target_crs="EPSG:3857").geometry.equals(projected.geometry)


def test_invalid_geometry(tmp_path):
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
    with pytest.raises(AOIError, match="Self-intersection"):
        load_aoi(write_geojson(tmp_path, geometry))
    with pytest.raises(AOIError, match="Self-intersection"):
        validate_aoi(AOI("invalid", Polygon(geometry["coordinates"][0]), CRS.from_epsg(4326)))


@pytest.mark.parametrize("document", [
    {"type": "Point", "coordinates": [0, 0]},
    {"type": "Polygon", "coordinates": []},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 91], [0, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 0, 1]]]},
    {"type": "Feature", "properties": {}, "geometry": None},
    {"type": "FeatureCollection", "features": []},
    {"type": "Polygon", "crs": {}, "coordinates": []},
    [],
    None,
])
def test_rejects_invalid_inputs(tmp_path, document):
    with pytest.raises(AOIError):
        load_aoi(write_geojson(tmp_path, document))


def test_nonfinite_coordinates():
    aoi = AOI("infinite", Polygon([(0, 0), (1, 0), (float("inf"), 1), (0, 0)]), CRS.from_epsg(4326))
    with pytest.raises(AOIError, match="finite"):
        validate_aoi(aoi)


def test_single_feature_collection(tmp_path):
    feature = json.loads(FIXTURE.read_text())
    path = write_geojson(tmp_path, {"type": "FeatureCollection", "features": [feature]})
    assert load_aoi(path).geometry.equals(load_aoi(FIXTURE).geometry)
    path = write_geojson(tmp_path, {"type": "FeatureCollection", "features": [feature, feature]})
    with pytest.raises(AOIError, match="exactly one"):
        load_aoi(path)


def test_missing_file(tmp_path):
    with pytest.raises(AOIError, match="does not exist"):
        load_aoi(tmp_path / "missing.geojson")


def test_malformed_json(tmp_path):
    path = tmp_path / "broken.geojson"
    path.write_text("{broken")
    with pytest.raises(AOIError, match="Could not read"):
        load_aoi(path)


def test_invalid_crs():
    with pytest.raises(AOIError, match="reproject"):
        reproject_aoi(load_aoi(FIXTURE), "not-a-crs")
