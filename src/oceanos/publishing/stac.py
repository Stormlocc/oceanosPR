"""Derived static STAC (1.1.0) for published releases (contracts §4.4)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from oceanos.domain import FlagSpec, Release

STAC_VERSION = "1.1.0"
PROCESSING_EXTENSION = "https://stac-extensions.github.io/processing/v1.2.0/schema.json"
CLASSIFICATION_EXTENSION = "https://stac-extensions.github.io/classification/v2.0.0/schema.json"
EO_EXTENSION = "https://stac-extensions.github.io/eo/v2.0.0/schema.json"
ACOLITE_RELEASE_URL = "https://github.com/acolite/acolite/releases/tag/{tag}"


def stac_root(products_aoi_dir: Path) -> Path:
    return products_aoi_dir / "stac"


def item_path(products_aoi_dir: Path, overpass_id: str) -> Path:
    return stac_root(products_aoi_dir) / "items" / f"{overpass_id}.json"


def collection_id(aoi_id: str) -> str:
    return f"oceanos-{aoi_id}"


def _atomic_json(document: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _bitfields(flag_spec: FlagSpec) -> list[dict[str, Any]]:
    return [
        {
            "offset": bit.bit, "length": 1, "name": bit.name, "description": bit.meaning,
            "classes": [
                {"value": 0, "name": "not_set", "description": f"{bit.name} not set"},
                {"value": 1, "name": "set", "description": bit.meaning},
            ],
        }
        for bit in sorted(flag_spec.bits, key=lambda item: item.bit)
    ]


def build_item(
    *, release: Release, overpass_id: str, aoi_id: str, datetime_utc: datetime,
    geometry: dict[str, Any], bbox: tuple[float, float, float, float],
    release_dir: Path, products_aoi_dir: Path, flag_spec: FlagSpec,
    acolite_software: str, oceanos_software: str, acolite_release_tag: str,
    status: str, scene_item_paths: list[Path],
) -> dict[str, Any]:
    """Build the Item for the current release; every href is relative to the Item file."""
    location = item_path(products_aoi_dir, overpass_id)
    base = location.parent

    def relative(path: Path) -> str:
        return Path(os.path.relpath(path, base)).as_posix()

    assets: dict[str, Any] = {}
    for asset in release.assets:
        entry: dict[str, Any] = {
            "href": relative(release_dir / asset.href), "type": asset.media_type,
            "roles": list(asset.roles), "oceanos:sha256": asset.sha256,
        }
        if asset.data_type is not None:
            band: dict[str, Any] = {"data_type": asset.data_type}
            if asset.nodata is not None:
                band["nodata"] = asset.nodata
            if asset.unit is not None:
                band["unit"] = asset.unit
            if asset.center_wavelength_nm is not None:
                band["eo:center_wavelength"] = asset.center_wavelength_nm / 1000
            entry["bands"] = [band]
        if asset.overview_resampling is not None:
            entry["oceanos:overview_resampling"] = asset.overview_resampling
        if asset.product_key == "l2_flags":
            entry["classification:bitfields"] = _bitfields(flag_spec)
        assets[asset.product_key] = entry
    return {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        "stac_extensions": [PROCESSING_EXTENSION, CLASSIFICATION_EXTENSION, EO_EXTENSION],
        "id": overpass_id,
        "collection": collection_id(aoi_id),
        "geometry": geometry,
        "bbox": list(bbox),
        "properties": {
            "datetime": datetime_utc.isoformat().replace("+00:00", "Z"),
            "processing:software": {"acolite": acolite_software, "oceanos": oceanos_software},
            "processing:datetime": release.created_at.isoformat().replace("+00:00", "Z"),
            "processing:level": "L2W",
            "oceanos:status": status,
            "oceanos:tier": release.tier.value,
            "oceanos:release_id": release.release_id,
            "oceanos:run_key": release.run_key,
        },
        "assets": assets,
        "links": [
            {"rel": "root", "href": relative(stac_root(products_aoi_dir) / "catalog.json"), "type": "application/json"},
            {"rel": "parent", "href": relative(stac_root(products_aoi_dir) / "collection.json"), "type": "application/json"},
            {"rel": "collection", "href": relative(stac_root(products_aoi_dir) / "collection.json"), "type": "application/json"},
            {"rel": "alternate", "href": relative(release_dir / "release.json"), "type": "application/json"},
            {"rel": "processing-software", "href": ACOLITE_RELEASE_URL.format(tag=acolite_release_tag), "type": "text/html"},
            *(
                {"rel": "derived_from", "href": relative(path), "type": "application/geo+json"}
                for path in scene_item_paths
            ),
        ],
    }


def write_item(item: dict[str, Any], products_aoi_dir: Path, aoi_id: str) -> Path:
    """Atomically replace the Item, then refresh the catalog and collection that list it."""
    root = stac_root(products_aoi_dir)
    location = item_path(products_aoi_dir, item["id"])
    _atomic_json(item, location)
    items = sorted((root / "items").glob("*.json"))
    _atomic_json({
        "type": "Catalog", "stac_version": STAC_VERSION, "id": f"oceanos-catalog-{aoi_id}",
        "description": "OCEANOS PR derived releases", "links": [
            {"rel": "root", "href": "./catalog.json", "type": "application/json"},
            {"rel": "child", "href": "./collection.json", "type": "application/json"},
        ],
    }, root / "catalog.json")
    _atomic_json({
        "type": "Collection", "stac_version": STAC_VERSION, "id": collection_id(aoi_id),
        "description": "Current OCEANOS PR release per overpass", "license": "other",
        "extent": {"spatial": {"bbox": [item["bbox"]]}, "temporal": {"interval": [[None, None]]}},
        "links": [
            {"rel": "root", "href": "./catalog.json", "type": "application/json"},
            {"rel": "parent", "href": "./catalog.json", "type": "application/json"},
            *({"rel": "item", "href": f"./items/{path.name}", "type": "application/geo+json"} for path in items),
        ],
    }, root / "collection.json")
    return location


def read_item(products_aoi_dir: Path, overpass_id: str) -> dict[str, Any] | None:
    location = item_path(products_aoi_dir, overpass_id)
    if not location.is_file():
        return None
    document: dict[str, Any] = json.loads(location.read_text(encoding="utf-8"))
    return document
