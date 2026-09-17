"""Validated polygon AOIs, with explicit CRS and RFC 7946 serialization."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError, ProjError
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from shapely.validation import explain_validity


class AOIError(ValueError):
    """An AOI cannot be read, validated, or transformed."""


@dataclass(frozen=True)
class AOI:
    """A named polygon in ``crs``; construct via ``load_aoi`` for validation."""

    name: str
    geometry: BaseGeometry
    crs: CRS

    @property
    def aoi_id(self) -> str:
        """Return the stable id of the named EPSG:4326 GeoJSON boundary."""
        return derive_aoi_id(self)

    def to_geojson(self) -> dict[str, Any]:
        """Return an RFC 7946 Feature in WGS84 longitude/latitude.

        Projected AOIs are transformed back to EPSG:4326 for interoperability.
        This preserves the region, rather than the working CRS.
        """
        geographic = reproject_aoi(self, "EPSG:4326")
        return {
            "type": "Feature",
            "properties": {"name": self.name},
            "geometry": mapping(geographic.geometry),
        }

    def save(self, path: str | Path) -> None:
        """Write a UTF-8 GeoJSON Feature; the parent directory must exist."""
        Path(path).write_text(
            json.dumps(self.to_geojson(), indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )


def derive_aoi_id(aoi: AOI) -> str:
    """Hash canonical WGS84 GeoJSON while keeping a readable name slug."""
    validate_aoi(aoi)

    def canonicalize(value: Any) -> Any:
        """Round floats so an identical boundary always hashes the same."""
        if isinstance(value, float):
            return round(value, 12)
        if isinstance(value, (list, tuple)):
            return [canonicalize(item) for item in value]
        if isinstance(value, dict):
            return {key: canonicalize(item) for key, item in value.items()}
        return value

    canonical = json.dumps(
        canonicalize(aoi.to_geojson()), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    ascii_name = unicodedata.normalize("NFKD", aoi.name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "aoi"
    return f"aoi-{slug}-{sha256(canonical).hexdigest()[:12]}"


def validate_aoi(aoi: AOI) -> bool:
    """Return True if valid; otherwise raise AOIError with the reason.

    Only nonempty, finite, two-dimensional Polygon/MultiPolygon geometries
    are accepted. Invalid topology is never silently repaired.
    """
    if not aoi.name.strip():
        raise AOIError("AOI name must not be blank")
    try:
        crs = CRS.from_user_input(aoi.crs)
    except (CRSError, ValueError, TypeError) as exc:
        raise AOIError(f"Invalid AOI CRS: {aoi.crs}") from exc
    if not (crs.is_geographic or crs.is_projected) or len(crs.axis_info) != 2:
        raise AOIError("AOI CRS must be a two-dimensional geographic or projected CRS")
    geometry = aoi.geometry
    if not isinstance(geometry, (Polygon, MultiPolygon)):
        raise AOIError("AOI geometry must be Polygon or MultiPolygon")
    if geometry.is_empty:
        raise AOIError("AOI geometry must not be empty")
    polygons = [geometry] if isinstance(geometry, Polygon) else geometry.geoms
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            for coordinate in ring.coords:
                if len(coordinate) != 2 or not all(math.isfinite(v) for v in coordinate):
                    raise AOIError("AOI coordinates must be finite and two-dimensional")
    if not geometry.is_valid:
        raise AOIError(f"Invalid AOI geometry: {explain_validity(geometry)}")
    if crs.equals(CRS.from_epsg(4326), ignore_axis_order=True):
        west, south, east, north = geometry.bounds
        if west < -180 or east > 180 or south < -90 or north > 90:
            raise AOIError("WGS84 coordinates are outside longitude/latitude bounds")
    return True


def load_aoi(
    path: str | Path, *, name: str | None = None, target_crs: str | CRS | None = None
) -> AOI:
    """Load an RFC 7946 geometry, Feature, or single-feature FeatureCollection.

    Input uses EPSG:4326 (longitude, latitude). Legacy GeoJSON ``crs`` members
    are rejected to avoid ambiguous coordinate interpretation. ``target_crs``
    optionally selects the working CRS after validation.
    """
    path = Path(path).expanduser()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AOIError(f"AOI file does not exist: {path}") from exc
    except (OSError, UnicodeError, ValueError) as exc:
        raise AOIError(f"Could not read AOI GeoJSON {path}: {exc}") from exc
    try:
        if "crs" in document:
            raise AOIError("GeoJSON must use RFC 7946 EPSG:4326 without a crs member")
        if document["type"] == "FeatureCollection":
            if len(document["features"]) != 1:
                raise AOIError("AOI FeatureCollection must contain exactly one Feature")
            document = document["features"][0]
            if document["type"] != "Feature":
                raise AOIError("FeatureCollection entries must be Features")
        properties = document.get("properties") or {}
        geometry = document["geometry"] if document["type"] == "Feature" else document
        if "crs" in document or "crs" in geometry:
            raise AOIError("GeoJSON must use RFC 7946 EPSG:4326 without a crs member")
        if geometry["type"] not in ("Polygon", "MultiPolygon"):
            raise AOIError("AOI geometry must be Polygon or MultiPolygon")
        # Shapely closes open rings automatically; reject malformed GeoJSON first.
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for polygon in polygons:
            for ring in polygon:
                if len(ring) < 4 or ring[0] != ring[-1]:
                    raise AOIError("GeoJSON polygon rings must be closed with at least four positions")
        aoi = AOI(name if name is not None else properties.get("name", path.stem), shape(geometry), CRS.from_epsg(4326))
        validate_aoi(aoi)
    except AOIError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, GEOSException) as exc:
        raise AOIError(f"Invalid AOI GeoJSON structure in {path}: {exc}") from exc
    return reproject_aoi(aoi, target_crs) if target_crs is not None else aoi


def get_bounds(aoi: AOI) -> tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y) in the AOI's current CRS."""
    validate_aoi(aoi)
    west, south, east, north = aoi.geometry.bounds
    return float(west), float(south), float(east), float(north)


def reproject_aoi(aoi: AOI, target_crs: str | CRS) -> AOI:
    """Return a validated AOI in target_crs, always using x/y axis order."""
    validate_aoi(aoi)
    try:
        target = CRS.from_user_input(target_crs)
        transformer = Transformer.from_crs(aoi.crs, target, always_xy=True)
        geometry = transform(
            lambda x, y, z=None: transformer.transform(x, y, errcheck=True),
            aoi.geometry,
        )
    except (CRSError, ProjError, ValueError, TypeError) as exc:
        raise AOIError(f"Could not reproject AOI to {target_crs}: {exc}") from exc
    result = AOI(aoi.name, geometry, target)
    validate_aoi(result)
    return result
