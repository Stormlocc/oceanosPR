"""One-scene materialization, with synthetic streams and no network access."""

import hashlib
import json
from pathlib import Path
import socket

import httpx
import pytest

from oceanos.aoi import load_aoi
from oceanos.catalog import LocalCatalogError, LocalSceneCatalog, SceneAsset, SceneMetadata
from oceanos.ingestion import MVP_BANDS, MaterializationError, SceneManifest, fetch_scene

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = b"synthetic raster bytes for transfer tests"
KEYS = {"B02": "blue", "B03": "green", "B04": "red", "B08": "nir", "B11": "swir16"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Tests must not download real assets")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def scene():
    return SceneMetadata(
        scene_id="S2A_TEST_20240101", collection="sentinel-2-l2a", platform="sentinel-2a",
        datetime="2024-01-01T14:30:00Z", cloud_cover=12.5, source_catalog="https://catalog.example",
        geometry=load_aoi(ROOT / "tests/fixtures/aoi.geojson").to_geojson()["geometry"],
        bbox=(0, 0, 1, 1),
        assets={key: SceneAsset(href=f"https://assets.example/{key}.tif?original=query", file_size=len(PAYLOAD))
                for key in (*KEYS.values(), "nir08", "swir22", "scl", "thumbnail")},
    )


@pytest.fixture
def catalog(tmp_path, scene):
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    return catalog


def directory(tmp_path, scene):
    return tmp_path / "raw" / "sentinel2" / scene.scene_id


def manifest_path(tmp_path, scene):
    return directory(tmp_path, scene) / "manifest.json"


def mock_client(calls):
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=PAYLOAD, headers={"Content-Length": str(len(PAYLOAD))})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_default_bands_manifest_and_catalog(catalog, scene, tmp_path):
    calls = []
    original = catalog.get_scene(scene.scene_id)
    with mock_client(calls) as client:
        result = fetch_scene(catalog, scene.scene_id, tmp_path / "raw", client=client)
    assert result.status == "complete"
    assert set(result.assets) == set(MVP_BANDS)
    assert len(calls) == 5
    assert {request.url.path for request in calls} == {f"/{key}.tif" for key in KEYS.values()}
    assert all(request.method == "GET" for request in calls)
    assert all(request.headers["Accept-Encoding"] == "identity" for request in calls)
    assert all(request.extensions["timeout"]["read"] == 60 for request in calls)
    persisted = SceneManifest.model_validate_json(manifest_path(tmp_path, scene).read_text())
    assert persisted == result
    for band, record in result.assets.items():
        assert record.asset_key == KEYS[band]
        assert record.source_url == scene.assets[KEYS[band]].href
        assert record.file_size == len(PAYLOAD)
        assert record.sha256 == hashlib.sha256(PAYLOAD).hexdigest()
        assert record.download_timestamp.tzinfo is not None
        assert record.local_path == f"{band}.tif"
        assert (directory(tmp_path, scene) / record.local_path).read_bytes() == PAYLOAD
    assert not list(directory(tmp_path, scene).glob("*.part"))
    item = LocalSceneCatalog(catalog.directory).get_stac_item(scene.scene_id)
    assert item.properties["oceanos:materialization_status"] == "complete"
    assert item.properties["oceanos:processing_status"] == "materialized"
    assert item.properties["oceanos:manifest_path"] == str(manifest_path(tmp_path, scene))
    for band, key in KEYS.items():
        assert item.assets[key].href == scene.assets[key].href
        assert item.assets[key].extra_fields["oceanos:local_path"] == str(directory(tmp_path, scene) / f"{band}.tif")
    assert "oceanos:local_path" not in item.assets["nir08"].extra_fields
    assert catalog.get_scene(scene.scene_id) == original
    assert catalog.add_scene(original) is False


def test_existing_verified_files_are_idempotent(catalog, scene, tmp_path):
    calls = []
    with mock_client(calls) as client:
        first = fetch_scene(catalog, scene.scene_id, tmp_path / "raw", client=client)
        files = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
        second = fetch_scene(LocalSceneCatalog(catalog.directory), scene.scene_id, tmp_path / "raw", client=client)
    assert len(calls) == 5
    assert first == second
    assert files == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}


def test_existing_without_manifest_is_not_trusted(catalog, scene, tmp_path):
    directory(tmp_path, scene).mkdir(parents=True)
    destination = directory(tmp_path, scene) / "B02.tif"
    destination.write_bytes(b"X" * len(PAYLOAD))  # Even the same size is insufficient.
    calls = []
    with mock_client(calls) as client:
        result = fetch_scene(catalog, scene.scene_id, tmp_path / "raw", bands=["B02"], client=client)
    assert len(calls) == 1
    assert destination.read_bytes() == PAYLOAD
    assert result.status == "partial"


@pytest.mark.parametrize("corruption", [b"truncated", b"X" * len(PAYLOAD)])
def test_corrupt_file_is_downloaded_again(catalog, scene, tmp_path, corruption):
    calls = []
    with mock_client(calls) as client:
        fetch_scene(catalog, scene.scene_id, tmp_path / "raw", client=client)
        (directory(tmp_path, scene) / "B02.tif").write_bytes(corruption)
        result = fetch_scene(catalog, scene.scene_id, tmp_path / "raw", client=client)
    assert len(calls) == 6
    assert result.status == "complete"
    assert (directory(tmp_path, scene) / "B02.tif").read_bytes() == PAYLOAD


class InterruptedStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b"partial"
        raise httpx.ReadError("interrupted")


def test_interrupted_download_never_publishes_partial_file(catalog, scene, tmp_path):
    def handler(request):
        return httpx.Response(200, stream=InterruptedStream(), headers={"Content-Length": str(len(PAYLOAD))})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MaterializationError, match="transfer failed"):
            fetch_scene(catalog, scene.scene_id, tmp_path / "raw", bands=["B02"], client=client)
    assert not (directory(tmp_path, scene) / "B02.tif").exists()
    assert not list(directory(tmp_path, scene).glob("*.part"))
    manifest = SceneManifest.model_validate_json(manifest_path(tmp_path, scene).read_text())
    assert manifest.assets == {}
    assert manifest.status == "failed"
    assert manifest.failures["B02"].asset_key == "blue"
    assert manifest.failures["B02"].source_url == scene.assets["blue"].href
    item = catalog.get_stac_item(scene.scene_id)
    assert item.properties["oceanos:materialization_status"] == "failed"
    assert "oceanos:local_path" not in item.assets["blue"].extra_fields
    calls = []
    with mock_client(calls) as client:
        result = fetch_scene(catalog, scene.scene_id, tmp_path / "raw", bands=["B02"], client=client)
    assert len(calls) == 1
    assert result.failures == {}
    assert (directory(tmp_path, scene) / "B02.tif").read_bytes() == PAYLOAD


def test_interruption_retains_completed_bands_for_retry(catalog, scene, tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == "/green.tif":
            return httpx.Response(200, stream=InterruptedStream())
        return httpx.Response(200, content=PAYLOAD)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MaterializationError):
            fetch_scene(catalog, scene.scene_id, tmp_path / "raw", client=client)
    result = SceneManifest.model_validate_json(manifest_path(tmp_path, scene).read_text())
    assert list(result.assets) == ["B02"]
    assert result.status == "partial"
    with mock_client(calls) as client:
        result = fetch_scene(catalog, scene.scene_id, tmp_path / "raw", client=client)
    assert result.status == "complete"
    assert len(calls) == 6  # One good + one interrupted + four remaining.


def test_missing_asset_preflight_prevents_any_download(scene, tmp_path):
    del scene.assets["swir16"]
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    calls = []
    with mock_client(calls) as client:
        with pytest.raises(MaterializationError, match="no asset for band B11"):
            fetch_scene(catalog, scene.scene_id, tmp_path / "raw", client=client)
    assert not calls
    assert not directory(tmp_path, scene).exists()


def test_missing_scene_does_not_download(catalog, tmp_path):
    calls = []
    with mock_client(calls) as client:
        with pytest.raises(MaterializationError, match="does not exist"):
            fetch_scene(catalog, "missing", tmp_path / "raw", client=client)
    assert not calls


def test_exact_band_keys_are_supported(scene, tmp_path):
    scene.assets = {band: scene.assets[key] for band, key in KEYS.items()}
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    calls = []
    with mock_client(calls) as client:
        result = fetch_scene(catalog, scene.scene_id, tmp_path / "raw", bands=["B02", "B02"], client=client)
    assert len(calls) == 1
    assert result.assets["B02"].asset_key == "B02"


@pytest.mark.parametrize("kind", ["short", "long", "header_conflict", "partial_http", "missing_length", "empty"])
def test_size_and_full_response_checks(scene, tmp_path, kind):
    # Independently verify Content-Length even without file:size in the catalog.
    if kind in {"short", "long", "missing_length", "empty"}:
        scene.assets["blue"].file_size = None
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    catalog.add_scene(scene)
    headers = {"Content-Length": str(len(PAYLOAD))}
    content = PAYLOAD
    if kind == "short":
        content = PAYLOAD[:-3]
    elif kind == "long":
        content += b"extra"
    elif kind == "header_conflict":
        headers["Content-Length"] = str(len(PAYLOAD) + 1)
    elif kind == "missing_length":
        headers = {}
    elif kind == "empty":
        content, headers = b"", {}
    def handler(request):
        return httpx.Response(206 if kind == "partial_http" else 200, stream=httpx.ByteStream(content), headers=headers)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        if kind == "missing_length":
            result = fetch_scene(catalog, scene.scene_id, tmp_path / "raw", bands=["B02"], client=client)
            assert result.assets["B02"].file_size == len(PAYLOAD)
        else:
            with pytest.raises(MaterializationError):
                fetch_scene(catalog, scene.scene_id, tmp_path / "raw", bands=["B02"], client=client)
            assert not (directory(tmp_path, scene) / "B02.tif").exists()
            assert not list(directory(tmp_path, scene).glob("*.part"))


def test_final_path_is_only_published_after_success(catalog, scene, tmp_path):
    destination = directory(tmp_path, scene) / "B02.tif"
    class ObservedStream(httpx.SyncByteStream):
        def __iter__(self):
            assert not destination.exists()
            assert list(destination.parent.glob("*.part"))
            yield PAYLOAD[:10]
            assert not destination.exists()
            yield PAYLOAD[10:]
            assert not destination.exists()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=ObservedStream()))) as client:
        fetch_scene(catalog, scene.scene_id, tmp_path / "raw", bands=["B02"], client=client)
    assert destination.read_bytes() == PAYLOAD


def test_lost_catalog_update_is_recovered_without_download(catalog, scene, tmp_path, monkeypatch):
    original = catalog.record_materialization
    def failing(scene_id, **kwargs):
        if kwargs["status"] == "complete":
            raise LocalCatalogError("simulated catalog write failure")
        return original(scene_id, **kwargs)
    monkeypatch.setattr(catalog, "record_materialization", failing)
    calls = []
    with mock_client(calls) as client:
        with pytest.raises(LocalCatalogError):
            fetch_scene(catalog, scene.scene_id, tmp_path / "raw", client=client)
        assert SceneManifest.model_validate_json(manifest_path(tmp_path, scene).read_text()).status == "complete"
        monkeypatch.setattr(catalog, "record_materialization", original)
        fetch_scene(catalog, scene.scene_id, tmp_path / "raw", client=client)
    assert len(calls) == 5
    assert catalog.get_stac_item(scene.scene_id).properties["oceanos:materialization_status"] == "complete"


def test_stale_unrequested_file_does_not_keep_complete_status(catalog, scene, tmp_path):
    calls = []
    with mock_client(calls) as client:
        fetch_scene(catalog, scene.scene_id, tmp_path / "raw", client=client)
        (directory(tmp_path, scene) / "B11.tif").unlink()
        result = fetch_scene(catalog, scene.scene_id, tmp_path / "raw", bands=["B02"], client=client)
    assert len(calls) == 5
    assert result.status == "partial"
    item = catalog.get_stac_item(scene.scene_id)
    assert item.properties["oceanos:materialization_status"] == "partial"
    assert "oceanos:local_path" not in item.assets["swir16"].extra_fields


@pytest.mark.parametrize("bands", [[], ["B8A"], ["B12"], ["SCL"]])
def test_rejects_unrequested_extra_bands(catalog, scene, tmp_path, bands):
    with pytest.raises(ValueError):
        fetch_scene(catalog, scene.scene_id, tmp_path / "raw", bands=bands)
    assert not directory(tmp_path, scene).exists()


def test_fetch_cli(catalog, scene, tmp_path, monkeypatch, capsys):
    from oceanos.__main__ import main
    calls = []
    with mock_client(calls) as client:
        monkeypatch.setattr("oceanos.__main__.fetch_scene", lambda *a, **kw: fetch_scene(*a, client=client, **kw))
        args = ["scenes", "fetch", scene.scene_id, "--bands", "B02", "B03", "--timeout", "8",
                "--catalog-dir", str(catalog.directory), "--raw-dir", str(tmp_path / "raw")]
        assert main(args) == 0
        assert main(args) == 0
    assert len(calls) == 2
    assert all(request.extensions["timeout"]["read"] == 8 for request in calls)
    output = capsys.readouterr().out
    assert "B02 (blue)" in output
    assert "MVP materialization: partial" in output
    assert "manifest.json" in output
