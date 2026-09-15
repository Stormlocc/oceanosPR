"""Verify one published release directory offline.

Usage: uv run python scripts/verify_release.py RELEASE_DIR

Checks that every GeoTIFF is a tiled COG with at least one overview, that ``l2_flags``
overview values are a subset of its full-resolution values, that every asset matches
the SHA-256 in ``release.json``, and that the derived STAC Item validates against the
schemas vendored under ``tests/fixtures/stac-schemas/``.
"""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from jsonschema import Draft7Validator
from referencing import Registry, Resource

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = PROJECT_ROOT / "tests/fixtures/stac-schemas"
ITEM_SCHEMA = "https://schemas.stacspec.org/v1.1.0/item-spec/json-schema/item.json"


def _local_schema(uri: str) -> Resource:
    path = SCHEMA_ROOT / uri.split("://", 1)[1].split("#", 1)[0]
    if not path.is_file():
        raise LookupError(f"schema not vendored: {uri}")
    return Resource.from_contents(json.loads(path.read_text(encoding="utf-8")))


def stac_item_errors(item: dict[str, Any]) -> list[str]:
    """Validate an Item against STAC 1.1.0 core plus each declared extension, offline."""
    registry: Registry = Registry(retrieve=_local_schema)  # type: ignore[call-arg]
    errors: list[str] = []
    for uri in (ITEM_SCHEMA, *item.get("stac_extensions", [])):
        schema = _local_schema(uri).contents
        validator = Draft7Validator(schema, registry=registry)
        errors.extend(f"{uri}: {error.message}" for error in validator.iter_errors(item))
    return errors


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_errors(release_dir: Path) -> list[str]:
    errors: list[str] = []
    release = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
    for asset in release["assets"]:
        path = release_dir / asset["href"]
        if not path.is_file():
            errors.append(f"missing asset: {asset['href']}")
        elif _sha256(path) != asset["sha256"]:
            errors.append(f"sha256 mismatch: {asset['href']}")
    provenance = release_dir / release["provenance"]["relpath"]
    if not provenance.is_file() or _sha256(provenance) != release["provenance"]["sha256"]:
        errors.append("provenance.json missing or sha256 mismatch")

    for tif in sorted(release_dir.glob("*.tif")):
        with rasterio.open(tif) as dataset:
            # GDAL writes LAYOUT=COG only for the COG driver, which always writes tiled TIFFs.
            block_height, block_width = dataset.block_shapes[0]
            tiled = block_width < dataset.width or (block_width == block_height and block_width in {256, 512})
            if dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") != "COG" or not tiled:
                errors.append(f"not a tiled COG: {tif.name}")
            factors = dataset.overviews(1)
            if not factors:
                errors.append(f"no overviews: {tif.name}")
            if tif.stem == "l2_flags" and factors:
                full = set(np.unique(dataset.read(1)).tolist())
                for factor in factors:
                    shape = (max(1, dataset.height // factor), max(1, dataset.width // factor))
                    overview = set(np.unique(dataset.read(1, out_shape=shape)).tolist())
                    if not overview <= full:
                        errors.append(f"l2_flags overview x{factor} invents values: {sorted(overview - full)}")

    products_aoi_dir = release_dir.parents[2]
    overpass_id = release_dir.parent.name
    item_path = products_aoi_dir / "stac" / "items" / f"{overpass_id}.json"
    if not item_path.is_file():
        errors.append(f"STAC item missing: {item_path}")
    else:
        item = json.loads(item_path.read_text(encoding="utf-8"))
        errors.extend(stac_item_errors(item))
        if item["properties"].get("oceanos:release_id") != release["release_id"]:
            errors.append("STAC item does not point at this release")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    release_dir = Path(argv[1]).resolve()
    errors = release_errors(release_dir)
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    if not errors:
        print(f"OK: {release_dir}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
