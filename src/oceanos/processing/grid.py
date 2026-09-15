"""A single, explicit metric raster grid shared by every normalized band."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import rasterio
from pydantic import AwareDatetime, ConfigDict, Field, field_serializer, field_validator
from pyproj import CRS as Projection
from rasterio.crs import CRS
from rasterio.transform import Affine, array_bounds, from_origin
from rasterio.warp import calculate_default_transform
from shapely.geometry import box

from oceanos.aoi import AOI, reproject_aoi
from oceanos.domain import MetadataModel


def metric_crs(value: str | CRS) -> CRS:
    crs = CRS.from_user_input(value)
    projection = Projection.from_user_input(crs)
    if not projection.is_projected or len(projection.axis_info) != 2 or any(
        axis.unit_conversion_factor != 1 for axis in projection.axis_info
    ):
        raise ValueError("Normalization requires a projected CRS with metre units")
    return crs


def buffered_aoi(aoi: AOI, crs: str | CRS, buffer_m: float = 0):
    if not math.isfinite(buffer_m) or buffer_m < 0:
        raise ValueError("buffer_m must be finite and nonnegative")
    geometry = reproject_aoi(aoi, metric_crs(crs).to_wkt()).geometry
    return geometry.buffer(buffer_m) if buffer_m else geometry


@dataclass(frozen=True)
class GridSpec:
    crs: CRS
    resolution: float
    bounds: tuple[float, float, float, float]
    width: int
    height: int
    transform: Affine

    def __post_init__(self):
        object.__setattr__(self, "crs", metric_crs(self.crs))
        if not math.isfinite(self.resolution) or self.resolution <= 0:
            raise ValueError("resolution must be finite and positive")
        if any(not isinstance(size, int) or isinstance(size, bool) or size <= 0 for size in (self.width, self.height)):
            raise ValueError("Grid dimensions must be positive integers")
        if not all(math.isfinite(value) for value in self.transform):
            raise ValueError("Grid transform must be finite")
        if (self.transform.a, self.transform.b, self.transform.d, self.transform.e) != (
            self.resolution, 0, 0, -self.resolution,
        ):
            raise ValueError("Grid must have square north-up pixels at the configured resolution")
        if tuple(self.bounds) != array_bounds(self.height, self.width, self.transform):
            raise ValueError("Grid bounds must agree exactly with its dimensions and transform")

    def to_dict(self) -> dict:
        return {
            "crs": self.crs.to_string(), "resolution": self.resolution,
            "bounds": list(self.bounds), "width": self.width, "height": self.height,
            "transform": list(self.transform)[:6],
        }


class DeliveryGrid(MetadataModel):
    """One AOI-anchored, scene-independent delivery grid."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, arbitrary_types_allowed=True)

    schema_version: str = "1.0"
    grid_id: str = Field(pattern=r"^grid-[0-9a-f]{12}$")
    aoi_id: str = Field(pattern=r"^aoi-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{12}$")
    spec: GridSpec
    anchor: tuple[float, float]
    buffer_m: float = Field(ge=0)
    created_at: AwareDatetime

    @field_validator("spec", mode="before")
    @classmethod
    def parse_spec(cls, value):
        if isinstance(value, GridSpec):
            return value
        if isinstance(value, dict):
            return GridSpec(
                CRS.from_user_input(value["crs"]), value["resolution"], tuple(value["bounds"]),
                value["width"], value["height"], Affine(*value["transform"]),
            )
        raise ValueError("spec must be a GridSpec or its serialized form")

    @field_serializer("spec")
    def serialize_spec(self, value: GridSpec) -> dict:
        return value.to_dict()

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    def save(self, path: str | Path) -> None:
        """Atomically persist the delivery-grid document."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            temporary.write_text(
                json.dumps(self.model_dump(mode="json"), indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def load(cls, path: str | Path) -> DeliveryGrid:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


def build_delivery_grid(aoi: AOI, *, buffer_m: float = 0) -> DeliveryGrid:
    """Cover an AOI on the fixed EPSG:32619 ten-metre global anchor."""
    resolution = 10.0
    geometry = buffered_aoi(aoi, "EPSG:32619", buffer_m)
    west, south, east, north = geometry.bounds
    left = math.floor(west / resolution) * resolution
    right = math.ceil(east / resolution) * resolution
    bottom = math.floor(south / resolution) * resolution
    top = math.ceil(north / resolution) * resolution
    width = round((right - left) / resolution)
    height = round((top - bottom) / resolution)
    transform = from_origin(left, top, resolution, resolution)
    spec = GridSpec(CRS.from_epsg(32619), resolution, array_bounds(height, width, transform), width, height, transform)
    canonical = json.dumps(
        {"aoi_id": aoi.aoi_id, "spec": spec.to_dict()},
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return DeliveryGrid(
        grid_id=f"grid-{sha256(canonical).hexdigest()[:12]}", aoi_id=aoi.aoi_id,
        spec=spec, anchor=(0, 0), buffer_m=buffer_m, created_at=datetime.now(UTC),
    )


def build_grid(
    reference_path: str | Path, aoi: AOI, *, target_crs: str | CRS | None = None,
    resolution: float = 10, buffer_m: float = 0,
) -> GridSpec:
    """Cover the buffered AOI, snapping outward from the reference pixel origin.

    The reference origin is preserved when it is north-up in the target CRS.
    Otherwise GDAL estimates its projected origin once, shared by every band.
    Grid bounds enclose the buffered AOI; areas outside the scene become nodata.
    """
    if not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("resolution must be finite and positive")
    crs = metric_crs(target_crs if target_crs is not None else aoi.crs.to_wkt())
    geometry = buffered_aoi(aoi, crs, buffer_m)
    with rasterio.open(reference_path) as reference:
        if reference.crs is None or reference.count != 1:
            raise ValueError("Reference must be a georeferenced single-band raster")
        projected_footprint = reproject_aoi(
            AOI("reference", box(*reference.bounds), Projection.from_user_input(reference.crs)),
            crs.to_wkt(),
        ).geometry
        if not geometry.intersects(projected_footprint):
            raise ValueError("Buffered AOI does not intersect the reference raster")
        if reference.crs == crs and reference.transform.b == reference.transform.d == 0:
            anchor = reference.transform
        else:
            anchor, _, _ = calculate_default_transform(
                reference.crs, crs, reference.width, reference.height, *reference.bounds,
                resolution=resolution,
            )
    west, south, east, north = geometry.bounds
    # Suppress roundoff at existing grid lines (less than a billionth of a pixel).
    def pixel(value):
        nearest = round(value)
        return nearest if abs(value - nearest) < 1e-9 else value

    left = math.floor(pixel((west - anchor.c) / resolution))
    right = math.ceil(pixel((east - anchor.c) / resolution))
    top = math.floor(pixel((anchor.f - north) / resolution))
    bottom = math.ceil(pixel((anchor.f - south) / resolution))
    transform = Affine(resolution, 0, anchor.c + left * resolution, 0, -resolution, anchor.f - top * resolution)
    width, height = right - left, bottom - top
    return GridSpec(crs, resolution, array_bounds(height, width, transform), width, height, transform)
