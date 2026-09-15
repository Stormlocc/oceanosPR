"""Anonymous CDSE OData discovery for Sentinel-2 Level-1C products."""

from __future__ import annotations

import json
import math
import time as clock
from contextlib import nullcontext
from datetime import UTC, date, datetime, time
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from shapely.geometry import shape

from oceanos.aoi import AOI, validate_aoi
from oceanos.catalog.models import ProviderChecksums, SceneAsset, SceneMetadata
from oceanos.catalog.provider import SceneProvider, SceneProviderError

TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
L1C_COLLECTION = "sentinel-2-l1c"


def _datetime(value: datetime | str, *, end: bool = False) -> datetime:
    try:
        if isinstance(value, str):
            if len(value) == 10:
                return datetime.combine(date.fromisoformat(value), time.max if end else time.min, UTC)
            value = datetime.fromisoformat(value)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include a timezone")
        return value.astimezone(UTC)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid datetime {value!r}: use YYYY-MM-DD or an ISO datetime with timezone") from exc


def _odata_time(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None and "Retry-After" in response.headers:
        try:
            header = response.headers["Retry-After"]
            delay = float(header)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(header) - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = 0.5 * (2**attempt)
        return max(0, min(delay, 30))
    return 0.5 * (2**attempt)


class CdseODataProvider(SceneProvider):
    """Discover every L1C page or fail without returning partial results."""

    def __init__(
        self,
        catalogue_url: str = "https://catalogue.dataspace.copernicus.eu/odata/v1",
        download_url: str = "https://download.dataspace.copernicus.eu/odata/v1",
        *,
        timeout: float = 30,
        max_retries: int = 2,
        page_size: int = 100,
        client: httpx.Client | None = None,
    ) -> None:
        self.catalogue_url = self._root_url(catalogue_url, "catalogue_url")
        self.download_url = self._root_url(download_url, "download_url")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if not isinstance(max_retries, int) or not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be an integer between 0 and 5")
        if not isinstance(page_size, int) or not 1 <= page_size <= 10000:
            raise ValueError("page_size must be an integer between 1 and 10000")
        self.timeout = timeout
        self.max_retries = max_retries
        self.page_size = page_size
        self.client = client

    @staticmethod
    def _root_url(value: str, field: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError(f"{field} must be an HTTP(S) root URL without query or fragment")
        return value.rstrip("/")

    def search(
        self,
        aoi: AOI,
        start_datetime: datetime | str,
        end_datetime: datetime | str,
        collection: str = L1C_COLLECTION,
        cloud_cover_max: float | None = None,
    ) -> list[SceneMetadata]:
        validate_aoi(aoi)
        if collection != L1C_COLLECTION:
            raise ValueError(f"CdseODataProvider has a fixed {L1C_COLLECTION} collection")
        start = _datetime(start_datetime)
        end = _datetime(end_datetime, end=True)
        if start > end:
            raise ValueError("start_datetime must be before or equal to end_datetime")
        if cloud_cover_max is not None and (not math.isfinite(cloud_cover_max) or not 0 <= cloud_cover_max <= 100):
            raise ValueError("cloud_cover_max must be between 0 and 100")
        footprint = shape(aoi.to_geojson()["geometry"])
        product_type = (
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'S2MSI1C')"
        )
        filters = [
            "Collection/Name eq 'SENTINEL-2'", product_type,
            f"OData.CSC.Intersects(area=geography'SRID=4326;{footprint.wkt}')",
            f"ContentDate/Start ge {_odata_time(start)}", f"ContentDate/Start le {_odata_time(end)}",
        ]
        params = {
            "$filter": " and ".join(filters), "$expand": "Attributes",
            "$orderby": "ContentDate/Start", "$top": str(self.page_size),
        }
        url = f"{self.catalogue_url}/Products"
        scenes: dict[str, SceneMetadata] = {}
        visited: set[str] = set()
        context = nullcontext(self.client) if self.client is not None else httpx.Client()
        with context as client:
            while url is not None:
                key = str(httpx.URL(url, params=params)) if params is not None else str(httpx.URL(url))
                if key in visited:
                    raise SceneProviderError("CDSE pagination repeated a page URL")
                visited.add(key)
                response = self._request(client, url, params)
                params = None
                try:
                    document = response.json()
                except json.JSONDecodeError as exc:
                    raise SceneProviderError("CDSE response is not valid JSON") from exc
                if not isinstance(document, dict) or not isinstance(document.get("value"), list):
                    raise SceneProviderError("Invalid CDSE OData response: value must be a list")
                for record in document["value"]:
                    scene = self._scene(record)
                    if cloud_cover_max is None or (
                        scene.cloud_cover is not None and scene.cloud_cover <= cloud_cover_max
                    ):
                        scenes.setdefault(scene.scene_id, scene)
                next_link = document.get("@odata.nextLink")
                if next_link is not None and not isinstance(next_link, str):
                    raise SceneProviderError("Invalid CDSE OData response: @odata.nextLink must be a URL")
                url = urljoin(f"{self.catalogue_url}/", next_link) if next_link else None
        return sorted(scenes.values(), key=lambda scene: (scene.datetime, scene.scene_id))

    def _request(self, client: httpx.Client, url: str, params: dict[str, str] | None) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            response: httpx.Response | None = None
            try:
                response = client.get(url, params=params, timeout=self.timeout)
                if response.status_code == 200:
                    return response
                if response.status_code not in TRANSIENT_HTTP_STATUS or attempt == self.max_retries:
                    raise SceneProviderError(f"CDSE request failed with HTTP {response.status_code}")
            except httpx.HTTPError as exc:
                if attempt == self.max_retries:
                    raise SceneProviderError(f"CDSE request failed: {type(exc).__name__}") from exc
            clock.sleep(_retry_delay(response, attempt))
        raise AssertionError("unreachable")

    def _scene(self, record: Any) -> SceneMetadata:
        try:
            if not isinstance(record, dict):
                raise TypeError("product must be an object")
            attributes = {
                attribute["Name"]: attribute.get("Value")
                for attribute in record["Attributes"] if isinstance(attribute, dict) and "Name" in attribute
            }
            product_type = attributes.get("productType") or attributes.get("processingLevel")
            if product_type != "S2MSI1C" or attributes.get("processingLevel") not in {None, "S2MSI1C"}:
                raise SceneProviderError("input.not_l1c: CDSE returned a non-L1C product")
            name = record["Name"]
            if not isinstance(name, str) or not name.endswith(".SAFE"):
                raise ValueError("Name must end in .SAFE")
            platform_value = attributes.get("platformSerialIdentifier")
            platform = platform_value if platform_value in {"S2A", "S2B", "S2C"} else f"S2{platform_value}"
            relative_orbit = int(attributes["relativeOrbitNumber"])
            datatake = str(attributes["productGroupId"])
            match = __import__("re").fullmatch(r"G(S2[ABC])_(\d{8}T\d{6})_\d+_N\d{2}\.\d{2}", datatake)
            if match is None or match.group(1) != platform:
                raise ValueError("productGroupId does not match the platform")
            overpass_id = f"{platform}_{match.group(2)}_R{relative_orbit:03d}"
            checksums = {
                str(entry.get("Algorithm", "")).upper(): entry.get("Value")
                for entry in record.get("Checksum", []) if isinstance(entry, dict)
            }
            geometry = record["GeoFootprint"]
            bounds = shape(geometry).bounds
            source_id = str(record["Id"])
            return SceneMetadata(
                scene_id=name[:-5], collection=L1C_COLLECTION, platform=platform,
                datetime=record["ContentDate"]["Start"], geometry=geometry, bbox=bounds,
                cloud_cover=attributes.get("cloudCover"), source_catalog=self.catalogue_url,
                processing_level="Level-1C", processing_baseline=attributes.get("processorVersion"),
                relative_orbit=relative_orbit, datatake_id=datatake, overpass_id=overpass_id,
                mgrs_tile=attributes.get("tileId"), source_id=source_id,
                checksums=ProviderChecksums(md5=checksums.get("MD5"), blake3=checksums.get("BLAKE3")),
                online=record.get("Online"),
                assets={"product": SceneAsset(
                    href=f"{self.download_url}/Products({source_id})/$value",
                    media_type="application/zip", title=name, roles=["data"],
                    file_size=record.get("ContentLength"),
                )},
            )
        except SceneProviderError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise SceneProviderError(f"Invalid CDSE OData product: {exc}") from exc
