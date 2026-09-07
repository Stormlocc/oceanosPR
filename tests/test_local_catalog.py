"""Local STAC persistence and reconstruction, with network access forbidden."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import socket

from jsonschema import Draft7Validator
from referencing import Registry, Resource
import pystac
from pystac.validation.local_validator import get_local_schema_cache
import pytest

from oceanos.aoi import load_aoi
from oceanos.catalog import (
    LocalCatalogError, LocalSceneCatalog, SceneAsset, SceneMetadata,
    SceneSearchResult, scene_from_stac_item, scene_to_stac_item,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Local STAC must never access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def scene():
    return SceneMetadata(
        scene_id="S2A_SYNTHETIC_20240101", collection="sentinel-2-l2a",
        platform="sentinel-2a", datetime="2024-01-01T14:30:00Z",
        geometry=load_aoi(ROOT / "tests/fixtures/aoi.geojson").to_geojson()["geometry"],
        bbox=(0, 0, 1, 1), cloud_cover=12.5, source_catalog="https://catalog.example",
        assets={"red": SceneAsset(
            href="https://assets.example/red.tif?token=preserve%2Fexactly",
            media_type="image/tiff", title="Red", roles=["data", "reflectance"],
        )},
    )


def snapshot(path):
    return {str(file.relative_to(path)): file.read_bytes() for file in path.rglob("*.json")}


def validate_core_documents(path):
    """Use PySTAC's bundled schemas and an offline registry, including refs."""
    cache = get_local_schema_cache()
    registry = Registry().with_resources((uri, Resource.from_contents(schema)) for uri, schema in cache.items())
    for file in path.rglob("*.json"):
        document = json.loads(file.read_text())
        kind = "item" if document["type"] == "Feature" else document["type"].lower()
        schema_uri = f'https://schemas.stacspec.org/v{document["stac_version"]}/{kind}-spec/json-schema/{kind}.json'
        Draft7Validator(cache[schema_uri], registry=registry).validate(document)


def test_empty_catalog_and_creation(tmp_path):
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    assert catalog.path.is_file()
    assert catalog.search_local_catalog() == []
    assert not catalog.scene_exists("missing")
    assert catalog.get_scene("missing") is None
    root = pystac.Catalog.from_file(str(catalog.path))
    collections = list(root.get_collections())
    assert len(collections) == 1
    assert collections[0].id == "sentinel-2-l2a"
    assert list(collections[0].get_items()) == []
    validate_core_documents(catalog.directory)


def test_add_scene_preserves_scientific_metadata_and_urls(tmp_path, scene):
    original = scene.model_dump_json()
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    assert catalog.add_scene(scene) is True
    assert catalog.scene_exists(scene.scene_id)
    assert catalog.get_scene(scene.scene_id) == scene
    assert scene.model_dump_json() == original
    item = catalog.get_stac_item(scene.scene_id)
    assert item.id == scene.scene_id
    assert item.collection_id == scene.collection
    assert item.geometry == scene.geometry.model_dump(mode="json")
    assert item.bbox == list(scene.bbox)
    assert item.datetime == scene.datetime
    assert item.properties["platform"] == scene.platform
    assert item.properties["eo:cloud_cover"] == scene.cloud_cover
    assert item.properties["oceanos:original_scene_id"] == scene.scene_id
    assert item.properties["oceanos:source_catalog"] == scene.source_catalog
    assert item.properties["oceanos:source_provider"] == "Sentinel2Provider"
    assert item.properties["oceanos:processing_status"] == "discovered"
    assert datetime.fromisoformat(item.properties["oceanos:ingested_at"]).tzinfo is not None
    assert item.assets["red"].href == scene.assets["red"].href
    assert any("eo/" in extension for extension in item.stac_extensions)
    assert not list(catalog.directory.rglob("*.tif"))
    validate_core_documents(catalog.directory)


def test_duplicate_is_noop_even_after_reload(tmp_path, scene):
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    before = snapshot(catalog.directory)
    assert catalog.add_scene(scene) is False
    assert LocalSceneCatalog(catalog.directory).add_scene(scene) is False
    assert snapshot(catalog.directory) == before
    assert len(catalog.search_local_catalog()) == 1
    root = pystac.Catalog.from_file(str(catalog.path))
    assert len(list(root.get_items(recursive=True))) == 1


def test_conflicting_duplicate_does_not_overwrite(tmp_path, scene):
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    before = snapshot(catalog.directory)
    changed = scene.model_copy(update={"cloud_cover": 99.0})
    with pytest.raises(LocalCatalogError, match="different metadata"):
        catalog.add_scene(changed)
    assert catalog.get_scene(scene.scene_id) == scene
    assert snapshot(catalog.directory) == before


def test_persistence_reload_and_portable_links(tmp_path, scene):
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    loaded = LocalSceneCatalog(catalog.directory)
    assert loaded.get_scene(scene.scene_id) == scene
    for file in catalog.directory.rglob("*.json"):
        for link in json.loads(file.read_text())["links"]:
            assert link["rel"] != "self"
            assert not Path(link["href"]).is_absolute()
    relocated = tmp_path / "relocated"
    shutil.copytree(catalog.directory, relocated)
    assert LocalSceneCatalog(relocated).get_scene(scene.scene_id) == scene
    # Reconstruct directly from the on-disk STAC Item, independently of the store.
    item_path = next(relocated.rglob("items/*.json"))
    assert scene_from_stac_item(pystac.Item.from_file(str(item_path))) == scene


def test_existing_instances_see_successive_updates(tmp_path, scene):
    first = LocalSceneCatalog(tmp_path / "catalog")
    second = LocalSceneCatalog(first.directory)
    first.add_scene(scene)
    another = scene.model_copy(update={"scene_id": "second"})
    second.add_scene(another)
    assert [s.scene_id for s in first.search_local_catalog()] == [scene.scene_id, "second"]


@pytest.mark.parametrize("optional", [False, True])
def test_conversion_roundtrip_with_multipolygon_and_optional_metadata(scene, optional):
    data = scene.model_dump(mode="json")
    data["geometry"] = {"type": "MultiPolygon", "coordinates": [data["geometry"]["coordinates"]]}
    if optional:
        data.update(platform=None, cloud_cover=None, assets={})
    scene = SceneMetadata.model_validate(data)
    ingested = datetime(2024, 2, 1, tzinfo=timezone.utc)
    item = scene_to_stac_item(scene, ingested_at=ingested, source_provider="test-provider")
    assert scene_from_stac_item(pystac.Item.from_dict(item.to_dict())) == scene
    assert item.properties["oceanos:source_provider"] == "test-provider"
    assert datetime.fromisoformat(item.properties["oceanos:ingested_at"]) == ingested


def test_multiple_original_collections_and_extents(tmp_path, scene):
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    later = scene.model_copy(update={"scene_id": "later", "datetime": datetime(2024, 2, 1, tzinfo=timezone.utc)})
    catalog.add_scene(later)
    other = scene.model_copy(update={"scene_id": "other", "collection": "sentinel-2-l1c"})
    catalog.add_scene(other)
    root = pystac.Catalog.from_file(str(catalog.path))
    collection = root.get_child(scene.collection)
    assert collection.extent.spatial.bboxes == [list(scene.bbox)]
    assert collection.extent.temporal.intervals == [[scene.datetime, later.datetime]]
    assert root.get_child(other.collection) is not None
    assert catalog.get_scene("other") == other
    validate_core_documents(catalog.directory)


def test_local_search_filters(tmp_path, scene):
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    catalog.add_scene(scene.model_copy(update={"scene_id": "unknown", "cloud_cover": None}))
    catalog.add_scene(scene.model_copy(update={"scene_id": "cloudy", "cloud_cover": 80.0}))
    assert len(catalog.search_local_catalog()) == 3
    assert catalog.search_local_catalog(cloud_cover_max=20) == [scene]
    assert catalog.search_local_catalog(platform="other") == []
    assert catalog.search_local_catalog(collection="other") == []
    assert len(catalog.search_local_catalog(start_datetime=scene.datetime, end_datetime=scene.datetime)) == 3
    assert catalog.search_local_catalog(start_datetime=datetime(2025, 1, 1, tzinfo=timezone.utc)) == []
    aoi = load_aoi(ROOT / "tests/fixtures/aoi.geojson", target_crs="EPSG:3857")
    assert len(catalog.search_local_catalog(aoi=aoi)) == 3
    from shapely.affinity import translate
    from oceanos.aoi import AOI
    moved = AOI("elsewhere", translate(aoi.geometry, xoff=1_000_000), aoi.crs)
    assert catalog.search_local_catalog(aoi=moved) == []
    with pytest.raises(ValueError):
        catalog.search_local_catalog(start_datetime=datetime(2024, 1, 1))


def test_arbitrary_ids_do_not_escape_catalog_directory(tmp_path, scene):
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    unusual = scene.model_copy(update={"scene_id": "../../outside", "collection": "../collection"})
    catalog.add_scene(unusual)
    assert catalog.get_scene(unusual.scene_id) == unusual
    assert not (tmp_path / "outside").exists()
    assert not (tmp_path / "collection").exists()


def test_corrupt_catalog_is_not_replaced(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text("{broken")
    with pytest.raises(LocalCatalogError, match="Cannot load"):
        LocalSceneCatalog(tmp_path)
    assert path.read_text() == "{broken"


def test_missing_item_file_is_error(tmp_path, scene):
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    next(catalog.directory.rglob("items/*.json")).unlink()
    with pytest.raises(LocalCatalogError):
        catalog.search_local_catalog()


def test_cli_add_duplicate_and_list(tmp_path, scene, capsys):
    from oceanos.__main__ import main
    input_file = tmp_path / "scenes.json"
    SceneSearchResult(scenes=[scene, scene]).save(input_file)
    directory = tmp_path / "catalog"
    config = str(ROOT / "configs/mvp.yaml")
    arguments = ["catalog", "add", str(input_file), "--catalog-dir", str(directory), "--config", config]
    assert main(arguments) == 0
    assert "Added: 1; already present: 1" in capsys.readouterr().out
    assert main(arguments) == 0
    assert "Added: 0; already present: 2" in capsys.readouterr().out
    assert main(["catalog", "list", "--catalog-dir", str(directory), "--config", config]) == 0
    assert scene.scene_id in capsys.readouterr().out
    assert LocalSceneCatalog(directory).get_scene(scene.scene_id) == scene


def test_cli_empty_and_invalid_input(tmp_path, capsys):
    from oceanos.__main__ import main
    directory = tmp_path / "catalog"
    assert main(["catalog", "list", "--catalog-dir", str(directory)]) == 0
    assert "0 scenes found." in capsys.readouterr().out
    input_file = tmp_path / "scenes.json"
    SceneSearchResult(scenes=[]).save(input_file)
    assert main(["catalog", "add", str(input_file), "--catalog-dir", str(directory)]) == 0
    assert "Added: 0; already present: 0" in capsys.readouterr().out
    before = snapshot(directory)
    input_file.write_text('{"raw_stac": true}')
    with pytest.raises(SystemExit) as error:
        main(["catalog", "add", str(input_file), "--catalog-dir", str(directory)])
    assert error.value.code == 1
    assert snapshot(directory) == before
