"""STAC remote is mocked at the HTTP boundary; no Internet or imagery."""

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from oceanos.aoi import load_aoi
from oceanos.catalog import (
    SceneMetadata,
    SceneProvider,
    SceneProviderError,
    SceneSearchResult,
    Sentinel2Provider,
)

FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = "https://catalog.example"


@pytest.fixture
def item():
    return json.loads((FIXTURES / "stac_item.json").read_text())


@pytest.fixture
def aoi():
    return load_aoi(FIXTURES / "aoi.geojson", target_crs="EPSG:3857")


def page(items, links=None):
    return {"type": "FeatureCollection", "features": items, "links": links or []}


def provider_for(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Sentinel2Provider(CATALOG, client=client, **kwargs)


def search(provider, aoi, **kwargs):
    return provider.search(aoi, "2024-01-01", "2024-01-02", "sentinel-2-l2a", **kwargs)


def test_zero_results_and_request_contract(aoi):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == "POST"
        assert str(request.url) == CATALOG + "/search"
        body = json.loads(request.content)
        assert body["collections"] == ["sentinel-2-l2a"]
        assert body["limit"] == 2
        assert body["datetime"] == "2024-01-01T00:00:00+00:00/2024-01-02T23:59:59.999999+00:00"
        assert "query" not in body
        assert "bbox" not in body
        assert body["intersects"]["coordinates"][0][2] == pytest.approx([1, 1])
        assert request.extensions["timeout"]["read"] == 7
        return httpx.Response(200, json=page([]))
    provider = provider_for(handler, timeout=7, page_size=2)
    assert isinstance(provider, SceneProvider)
    assert search(provider, aoi) == []
    assert len(calls) == 1


def test_one_scene_normalized_and_serialized(aoi, item, tmp_path):
    item["assets"]["red"]["file:size"] = 1234
    calls = []
    def handler(request):
        calls.append(request)
        assert json.loads(request.content)["query"] == {"eo:cloud_cover": {"lte": 20}}
        return httpx.Response(200, json=page([item]))
    scenes = search(provider_for(handler), aoi, cloud_cover_max=20)
    assert len(scenes) == 1
    scene = scenes[0]
    assert isinstance(scene, SceneMetadata)
    assert scene.scene_id == item["id"]
    assert scene.collection == "sentinel-2-l2a"
    assert scene.platform == "sentinel-2a"
    assert scene.datetime == datetime.fromisoformat("2024-01-01T14:30:00+00:00")
    assert scene.geometry.type == "Polygon"
    assert scene.bbox == (0, 0, 1, 1)
    assert scene.cloud_cover == 12.5
    assert scene.source_catalog == CATALOG
    assert scene.assets["red"].href == item["assets"]["red"]["href"]
    assert scene.assets["red"].media_type == item["assets"]["red"]["type"]
    assert scene.assets["red"].file_size == 1234
    path = tmp_path / "scenes.json"
    result = SceneSearchResult(scenes=scenes)
    result.save(path)
    assert SceneSearchResult.model_validate_json(path.read_text()) == result
    assert "provider:internal_value" not in path.read_text()
    assert "stac_version" not in path.read_text()
    assert len(calls) == 1  # No requests to asset URLs.


def test_multiple_pages_get_and_deduplication(aoi, item):
    second = deepcopy(item)
    second["id"] = "second"
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=page([item, item], [{"rel": "next", "href": "?token=two"}]))
        assert request.method == "GET"
        assert request.url.params["token"] == "two"
        assert not request.content
        return httpx.Response(200, json=page([item, second]))
    scenes = search(provider_for(handler), aoi)
    assert [s.scene_id for s in scenes] == [item["id"], "second"]
    assert len(calls) == 2


@pytest.mark.parametrize("merge", [True, False])
def test_post_pagination_and_empty_intermediate_page(aoi, item, merge):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=page([], [{
                "rel": "next", "href": "/search", "method": "POST", "merge": merge,
                "body": {"token": "two"}, "headers": {"X-Page": "two"},
            }]))
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body["token"] == "two"
        assert ("intersects" in body) is merge
        assert ("collections" in body) is merge
        assert request.headers["X-Page"] == "two"
        return httpx.Response(200, json=page([item]))
    assert len(search(provider_for(handler), aoi)) == 1
    assert len(calls) == 2


def test_pagination_cycle_is_error(aoi):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=page([], [{"rel": "next", "href": "/search"}]))
    with pytest.raises(SceneProviderError, match="repeated"):
        search(provider_for(handler), aoi)
    assert len(calls) == 2


def test_missing_optional_metadata(aoi, item):
    item["properties"] = {"datetime": "2024-01-01T10:30:00-04:00"}
    item.pop("assets")
    item.pop("links")
    scene = search(provider_for(lambda _: httpx.Response(200, json=page([item]))), aoi)[0]
    assert scene.platform is None
    assert scene.cloud_cover is None
    assert scene.assets == {}
    assert scene.datetime.isoformat() == "2024-01-01T14:30:00+00:00"


def test_optional_asset_metadata_and_relative_href(aoi, item):
    item["assets"] = {"red": {"href": "./red.tif"}}
    scene = search(provider_for(lambda _: httpx.Response(200, json=page([item]))), aoi)[0]
    asset = scene.assets["red"]
    assert asset.href == "https://catalog.example/collections/sentinel-2-l2a/items/red.tif"
    assert asset.media_type is None
    assert asset.title is None
    assert asset.roles == []


@pytest.mark.parametrize("status,attempts", [(400, 1), (401, 1), (404, 1), (429, 3), (500, 3), (503, 3)])
def test_remote_errors(aoi, monkeypatch, status, attempts):
    calls, sleeps = [], []
    monkeypatch.setattr("oceanos.catalog.sentinel2.clock.sleep", sleeps.append)
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="remote error")
    with pytest.raises(SceneProviderError, match=f"HTTP {status}"):
        search(provider_for(handler), aoi)
    assert len(calls) == attempts
    assert len(sleeps) == attempts - 1


def test_transient_error_retry_after_then_success(aoi, item, monkeypatch):
    sleeps, calls = [], []
    monkeypatch.setattr("oceanos.catalog.sentinel2.clock.sleep", sleeps.append)
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=page([item]))
    assert len(search(provider_for(handler), aoi)) == 1
    assert sleeps == [2]


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_failure_retries(aoi, monkeypatch, error):
    sleeps, calls = [], []
    monkeypatch.setattr("oceanos.catalog.sentinel2.clock.sleep", sleeps.append)
    def handler(request):
        calls.append(request)
        raise error("unavailable", request=request)
    with pytest.raises(SceneProviderError, match=error.__name__):
        search(provider_for(handler), aoi)
    assert len(calls) == 3
    assert sleeps == [0.5, 1]


def test_later_page_error_does_not_return_partial_success(aoi, item):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=page([item], [{"rel": "next", "href": "?page=2"}]))
        return httpx.Response(503)
    with pytest.raises(SceneProviderError):
        search(provider_for(handler, max_retries=0), aoi)


@pytest.mark.parametrize("payload", [None, [], {}, {"type": "FeatureCollection", "features": None}])
def test_malformed_response(aoi, payload):
    with pytest.raises(SceneProviderError):
        search(provider_for(lambda _: httpx.Response(200, content=json.dumps(payload))), aoi)


def test_non_json_response(aoi):
    with pytest.raises(SceneProviderError, match="not valid JSON"):
        search(provider_for(lambda _: httpx.Response(200, text="<html>error</html>")), aoi)


@pytest.mark.parametrize("missing", ["id", "collection", "geometry", "bbox", "properties"])
def test_missing_required_metadata_is_explicit_error(aoi, item, missing):
    item.pop(missing)
    with pytest.raises(SceneProviderError, match="Invalid STAC response"):
        search(provider_for(lambda _: httpx.Response(200, json=page([item]))), aoi)


@pytest.mark.parametrize("start,end,cloud", [
    ("2024-02-01", "2024-01-01", None),
    ("bad-date", "2024-01-01", None),
    ("2024-01-01T00:00:00", "2024-01-01", None),
    ("2024-01-01", "2024-01-01", -1),
    ("2024-01-01", "2024-01-01", 101),
    ("2024-01-01", "2024-01-01", float("nan")),
])
def test_invalid_search_inputs_do_not_request_network(aoi, start, end, cloud):
    def handler(request):
        pytest.fail("Invalid inputs must not reach HTTP")
    with pytest.raises(ValueError):
        provider_for(handler).search(aoi, start, end, "sentinel-2-l2a", cloud)
