"""Sentinel-2 discovery using STAC Item Search and the Query extension."""

from __future__ import annotations

import json
import math
import time as clock
from contextlib import nullcontext
from datetime import UTC, date, datetime, time
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx
from pyproj import CRS
from shapely.geometry import shape

from oceanos.aoi import AOI, validate_aoi
from oceanos.catalog.models import SceneMetadata
from oceanos.catalog.provider import SceneProvider, SceneProviderError


def _datetime(value: datetime | str, *, end: bool = False) -> datetime:
    try:
        if isinstance(value, str):
            if len(value) == 10:
                return datetime.combine(
                    date.fromisoformat(value), time.max if end else time.min, UTC
                )
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include a timezone")
        return value.astimezone(UTC)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid datetime {value!r}: use YYYY-MM-DD or an ISO datetime with timezone") from exc


class Sentinel2Provider(SceneProvider):
    """Search a STAC catalog supporting POST /search.

    ``client`` is an optional caller-owned HTTPX client (useful for mocking).
    Each request has a timeout; transient failures have bounded retries. Only
    search pages are requested, never asset URLs. No partial list is returned
    if any page or required item metadata is invalid.
    """

    def __init__(
        self,
        catalog_url: str = "https://earth-search.aws.element84.com/v1",
        *,
        timeout: float = 30,
        max_retries: int = 2,
        page_size: int = 100,
        client: httpx.Client | None = None,
    ) -> None:
        parsed = urlsplit(catalog_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("catalog_url must be an HTTP(S) catalog root URL without query or fragment")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if not isinstance(max_retries, int) or not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be an integer between 0 and 5")
        if not isinstance(page_size, int) or not 1 <= page_size <= 10000:
            raise ValueError("page_size must be an integer between 1 and 10000")
        self.catalog_url = catalog_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.page_size = page_size
        self._client = client

    def search(
        self,
        aoi: AOI,
        start_datetime: datetime | str,
        end_datetime: datetime | str,
        collection: str,
        cloud_cover_max: float | None = None,
    ) -> list[SceneMetadata]:
        start, end = _datetime(start_datetime), _datetime(end_datetime, end=True)
        if start > end:
            raise ValueError("start_datetime must be before or equal to end_datetime")
        if not collection.strip():
            raise ValueError("collection must not be blank")
        if cloud_cover_max is not None and not 0 <= cloud_cover_max <= 100:
            raise ValueError("cloud_cover_max must be between 0 and 100")
        original_body = {
            "collections": [collection],
            "intersects": aoi.to_geojson()["geometry"],
            "datetime": f"{start.isoformat()}/{end.isoformat()}",
            "limit": self.page_size,
        }
        if cloud_cover_max is not None:
            original_body["query"] = {"eo:cloud_cover": {"lte": cloud_cover_max}}
        original_headers = {"Accept": "application/geo+json, application/json"}
        method, url, body, headers = "POST", self.catalog_url + "/search", original_body, original_headers
        seen_requests: set[str] = set()
        scenes: dict[str, SceneMetadata] = {}
        context = nullcontext(self._client) if self._client is not None else httpx.Client()
        with context as client:
            while True:
                signature = json.dumps([method, url, body, headers], sort_keys=True)
                if signature in seen_requests:
                    raise SceneProviderError("STAC pagination repeated a request; results are incomplete")
                seen_requests.add(signature)
                page, page_url = self._request(client, method, url, body, headers)
                try:
                    if page["type"] != "FeatureCollection" or not isinstance(page["features"], list):
                        raise ValueError("Expected a STAC FeatureCollection with a features list")
                    for item in page["features"]:
                        scene = self._normalize(item, page_url)
                        scenes.setdefault(scene.scene_id, scene)
                    links = page.get("links", [])
                    if not isinstance(links, list) or not all(isinstance(link, dict) for link in links):
                        raise ValueError("Invalid STAC links")
                    next_link = next((link for link in links if link.get("rel") == "next"), None)
                    if next_link is None:
                        break
                    href = next_link["href"]
                    if not isinstance(href, str) or not href:
                        raise ValueError("Invalid next link href")
                    url = urljoin(page_url, href)
                    if urlsplit(url).scheme not in ("http", "https"):
                        raise ValueError("Next link must use HTTP(S)")
                    method = next_link.get("method", "GET").upper()
                    if method not in ("GET", "POST"):
                        raise ValueError("Only GET and POST pagination are supported")
                    body = next_link.get("body", {})
                    headers = next_link.get("headers", {})
                    if not isinstance(body, dict) or not isinstance(headers, dict):
                        raise TypeError("Next link body and headers must be objects")
                    if not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
                        raise ValueError("Next link headers must contain strings")
                    if next_link.get("merge", False):
                        body = {**original_body, **body}
                        headers = {**original_headers, **headers}
                    if method == "GET":
                        body = None
                except (KeyError, TypeError, ValueError, AttributeError) as exc:
                    raise SceneProviderError(f"Invalid STAC response from {page_url}: {exc}") from exc
        return list(scenes.values())

    def _request(self, client, method, url, body, headers):
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                response = client.request(
                    method, url, json=body, headers=headers, timeout=self.timeout,
                    follow_redirects=True,
                )
                response.raise_for_status()
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                retryable = response is None or response.status_code in {408, 429, 500, 502, 503, 504}
                if not retryable or attempt == self.max_retries:
                    detail = f"HTTP {response.status_code}" if response is not None else type(exc).__name__
                    raise SceneProviderError(f"STAC request failed at {url}: {detail} after {attempt + 1} attempt(s)") from exc
                delay = 0.5 * 2**attempt
                retry_after = response.headers.get("Retry-After") if response is not None else None
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        try:
                            delay = (parsedate_to_datetime(retry_after) - datetime.now(UTC)).total_seconds()
                        except (ValueError, TypeError, OverflowError):
                            pass
                clock.sleep(min(30, max(0, delay)))
                continue
            try:
                return response.json(), str(response.url)
            except ValueError as exc:
                raise SceneProviderError(f"STAC response is not valid JSON: {url}") from exc
        raise AssertionError("unreachable")

    def _normalize(self, item: dict, page_url: str) -> SceneMetadata:
        """Confine all STAC-specific property names to this adapter."""
        if item["type"] != "Feature":
            raise ValueError("STAC item must be a Feature")
        properties = item["properties"]
        item_url = next(
            (urljoin(page_url, link["href"]) for link in item.get("links", []) if link.get("rel") == "self"),
            page_url,
        )
        assets = {}
        for key, asset in (item.get("assets") or {}).items():
            href = asset["href"]
            if not isinstance(href, str) or not href.strip():
                raise ValueError("Asset href must not be blank")
            assets[key] = {
                "href": urljoin(item_url, href),
                "media_type": asset.get("type"),
                "title": asset.get("title"),
                "roles": asset.get("roles") or [],
                "file_size": asset.get("file:size"),
            }
        scene = SceneMetadata(
            scene_id=item["id"], collection=item["collection"],
            platform=properties.get("platform"), datetime=properties["datetime"],
            geometry=item["geometry"], bbox=item["bbox"],
            cloud_cover=properties.get("eo:cloud_cover"), assets=assets,
            source_catalog=self.catalog_url,
        )
        validate_aoi(AOI(scene.scene_id, shape(scene.geometry.model_dump()), CRS.from_epsg(4326)))
        return scene
