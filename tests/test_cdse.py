"""CDSE discovery tests use complete OData-shaped responses and no network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from oceanos.aoi import load_aoi
from oceanos.catalog import SceneProviderError, SceneSearchResult
from oceanos.catalog.cdse import CdseODataProvider

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = "https://catalogue.example/odata/v1"
DOWNLOAD = "https://download.example/odata/v1"


def product(*, name: str = "S2A_MSIL1C_20260702T150741_N0512_R082_T19QGV_X.SAFE", product_type: str = "S2MSI1C") -> dict:
    return {
        "Id": "06d74888-ff7c-48f7-9c08-3b064b18b58e",
        "Name": name,
        "ContentLength": 123,
        "Online": True,
        "Checksum": [
            {"Algorithm": "MD5", "Value": "0" * 32},
            {"Algorithm": "BLAKE3", "Value": "1" * 64},
        ],
        "ContentDate": {"Start": "2026-07-02T15:07:41.024000Z", "End": "2026-07-02T15:07:41.024000Z"},
        "GeoFootprint": {"type": "Polygon", "coordinates": [[[-67.2, 17.8], [-66.8, 17.8], [-66.8, 18.2], [-67.2, 18.2], [-67.2, 17.8]]]},
        "Attributes": [
            {"Name": "tileId", "Value": "19QGV"},
            {"Name": "cloudCover", "Value": 2.5},
            {"Name": "relativeOrbitNumber", "Value": 82},
            {"Name": "platformSerialIdentifier", "Value": "A"},
            {"Name": "processorVersion", "Value": "05.12"},
            {"Name": "productGroupId", "Value": "GS2A_20260702T150741_057594_N05.12"},
            {"Name": "processingLevel", "Value": product_type},
            {"Name": "productType", "Value": product_type},
        ],
    }


def provider(handler) -> CdseODataProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CdseODataProvider(CATALOGUE, DOWNLOAD, client=client, page_size=1, max_retries=0)


def test_maps_l1c_product_and_uses_fixed_anonymous_odata_query() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == "/odata/v1/Products"
        assert request.url.params["$expand"] == "Attributes"
        assert request.url.params["$orderby"] == "ContentDate/Start"
        assert "productType" in request.url.params["$filter"]
        assert "S2MSI1C" in request.url.params["$filter"]
        assert "OData.CSC.Intersects" in request.url.params["$filter"]
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"value": [product()]})

    scenes = provider(handler).search(load_aoi(ROOT / "tests/fixtures/aoi.geojson"), "2026-07-02", "2026-07-02")
    scene = scenes[0]
    assert scene.scene_id == "S2A_MSIL1C_20260702T150741_N0512_R082_T19QGV_X"
    assert scene.collection == "sentinel-2-l1c"
    assert scene.platform == "S2A"
    assert scene.processing_level == "Level-1C"
    assert scene.processing_baseline == "05.12"
    assert scene.relative_orbit == 82
    assert scene.datatake_id == "GS2A_20260702T150741_057594_N05.12"
    assert scene.overpass_id == "S2A_20260702T150741_R082"
    assert scene.mgrs_tile == "19QGV"
    assert scene.source_id == product()["Id"]
    assert scene.checksums.md5 == "0" * 32
    assert scene.checksums.blake3 == "1" * 64
    assert scene.assets["product"].file_size == 123
    assert scene.assets["product"].href == f"{DOWNLOAD}/Products({product()['Id']})/$value"
    assert len(calls) == 1


def test_complete_pagination_and_cycle_guard() -> None:
    calls = []

    def paged(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"value": [product()], "@odata.nextLink": f"{CATALOGUE}/Products?$skiptoken=two"})
        second = product(name="S2B_MSIL1C_20260705T150719_N0512_R082_T19QGV_X.SAFE")
        second["Id"] = "second"
        second["Attributes"][3]["Value"] = "B"
        second["Attributes"][5]["Value"] = "GS2B_20260705T150719_048728_N05.12"
        return httpx.Response(200, json={"value": [second]})

    result = provider(paged).search(load_aoi(ROOT / "tests/fixtures/aoi.geojson"), "2026-07-01", "2026-07-06")
    assert [scene.source_id for scene in result] == [product()["Id"], "second"]
    assert calls[1].url.params["$skiptoken"] == "two"

    cycle_calls = []

    def cyclic(request: httpx.Request) -> httpx.Response:
        cycle_calls.append(request)
        return httpx.Response(200, json={"value": [], "@odata.nextLink": f"{CATALOGUE}/Products?$skiptoken=loop"})

    with pytest.raises(SceneProviderError, match="repeated"):
        provider(cyclic).search(load_aoi(ROOT / "tests/fixtures/aoi.geojson"), "2026-07-01", "2026-07-06")
    assert len(cycle_calls) == 2


def test_non_l1c_response_aborts_the_whole_search() -> None:
    with pytest.raises(SceneProviderError, match=r"input\.not_l1c"):
        provider(lambda _: httpx.Response(200, json={"value": [product(product_type="S2MSI2A")]})).search(
            load_aoi(ROOT / "tests/fixtures/aoi.geojson"), "2026-07-02", "2026-07-02"
        )


def test_search_result_writes_1_1_and_accepts_legacy_1_0_fixture() -> None:
    legacy = json.loads((ROOT / "tests/fixtures/stac_item.json").read_text(encoding="utf-8"))
    legacy_result = SceneSearchResult.model_validate({"schema_version": "1.0", "scenes": [{
        "scene_id": legacy["id"], "collection": legacy["collection"],
        "datetime": legacy["properties"]["datetime"], "geometry": legacy["geometry"],
        "bbox": legacy["bbox"], "assets": {}, "source_catalog": "https://catalog.example",
    }]})
    assert legacy_result.schema_version == "1.0"
    assert SceneSearchResult(scenes=[]).model_dump(mode="json") == {"schema_version": "1.1", "scenes": []}
