"""Manual only: python -m pytest --run-integration tests/integration -q."""

from pathlib import Path

import pytest
from shapely.geometry import shape

from oceanos.aoi import load_aoi, reproject_aoi
from oceanos.catalog import SceneMetadata, SceneSearchResult, Sentinel2Provider
from oceanos.config import load_config

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_real_sentinel2_catalog(tmp_path):
    settings = load_config(ROOT / "configs/mvp.yaml")
    aoi = load_aoi(settings.aoi.path)
    provider = Sentinel2Provider(settings.scenes.catalog_url, page_size=1, timeout=30)
    scenes = provider.search(aoi, "2024-01-01", "2024-01-10", settings.scenes.collection)
    assert scenes, "Expected Sentinel-2 coverage of La Parguera during this historical window"
    assert len({scene.scene_id for scene in scenes}) == len(scenes)
    geographic = reproject_aoi(aoi, "EPSG:4326").geometry
    for scene in scenes:
        assert isinstance(scene, SceneMetadata)
        assert scene.collection == settings.scenes.collection
        assert scene.assets
        assert shape(scene.geometry.model_dump()).intersects(geographic)
        assert "2024-01-01" <= scene.datetime.date().isoformat() <= "2024-01-10"
    SceneSearchResult(scenes=scenes).save(tmp_path / "scenes.json")
