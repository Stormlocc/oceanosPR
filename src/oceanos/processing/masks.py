"""Grid-specific land mask rasterized from OCEANOS-owned coastline polygons (DA-1)."""

from __future__ import annotations

import os
import tempfile
from hashlib import sha256
from pathlib import Path

import numpy as np
import pyogrio  # type: ignore[import-untyped]
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_bounds, transform_geom
from shapely import from_wkb
from shapely.geometry import shape
from shapely.ops import unary_union

from oceanos.domain import ArtifactRef, CoastlineSource, LandMask
from oceanos.processing.grid import DeliveryGrid
from oceanos.processing.normalize import assert_aligned

LAND_MASK_VERSION = "1"
GSHHG_LAND_LAYER = Path("gshhg/GSHHS_shp/f/GSHHS_f_L1.shp")
GSHHG_VERSION = "2.3.7"
# Coastline polygons are read with a margin so edge pixels see their whole polygon.
_BBOX_MARGIN_DEG = 0.02


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rasterize_land(coastline_path: Path, grid: DeliveryGrid) -> np.ndarray:
    """Return a boolean array that is True where a pixel centre lies on land."""
    spec = grid.spec
    west, south, east, north = transform_bounds(spec.crs, "EPSG:4326", *spec.bounds)
    metadata, _, geometries, _ = pyogrio.raw.read(
        coastline_path,
        bbox=(west - _BBOX_MARGIN_DEG, south - _BBOX_MARGIN_DEG, east + _BBOX_MARGIN_DEG, north + _BBOX_MARGIN_DEG),
    )
    source_crs = metadata["crs"] or "EPSG:4326"
    projected = [
        shape(transform_geom(source_crs, spec.crs, geometry.__geo_interface__))
        for geometry in from_wkb(geometries)
        if geometry is not None
    ]
    if not projected:
        return np.zeros((spec.height, spec.width), dtype=bool)
    land = unary_union(projected)
    return geometry_mask(
        [land.__geo_interface__], (spec.height, spec.width), spec.transform, invert=True,
    )


def land_mask_paths(grid_dir: Path) -> tuple[Path, Path]:
    return grid_dir / "land_mask.tif", grid_dir / "land_mask.json"


def load_land_mask(grid_dir: Path, grid: DeliveryGrid) -> LandMask | None:
    """Return the persisted mask only when it matches this grid, version and raster hash."""
    raster_path, record_path = land_mask_paths(grid_dir)
    if not record_path.is_file() or not raster_path.is_file():
        return None
    record = LandMask.model_validate_json(record_path.read_text(encoding="utf-8"))
    if (
        record.grid_id != grid.grid_id
        or record.version != LAND_MASK_VERSION
        or _file_sha256(raster_path) != record.raster.sha256
    ):
        return None
    assert_aligned(raster_path, grid.spec)
    return record


def ensure_land_mask(
    grid_dir: Path, grid: DeliveryGrid, coastline_path: Path, *, coastline_version: str = GSHHG_VERSION,
) -> LandMask:
    """Build the land mask once per grid; reuse a verified existing one."""
    existing = load_land_mask(grid_dir, grid)
    if existing is not None:
        return existing
    if not coastline_path.is_file():
        raise FileNotFoundError(f"coastline polygons are missing: {coastline_path}")
    land = rasterize_land(coastline_path, grid)
    raster_path, record_path = land_mask_paths(grid_dir)
    grid_dir.mkdir(parents=True, exist_ok=True)
    spec = grid.spec
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=grid_dir, prefix=".land_mask-", suffix=".tif", delete=False) as stream:
            temporary = Path(stream.name)
        with rasterio.open(
            temporary, "w", driver="GTiff", count=1, dtype="uint8", nodata=None,
            crs=spec.crs, transform=spec.transform, width=spec.width, height=spec.height,
            tiled=True, blockxsize=256, blockysize=256, compress="deflate",
        ) as destination:
            destination.write(land.astype("uint8"), 1)
            destination.update_tags(meaning="1=land,0=water", land_mask_version=LAND_MASK_VERSION)
        assert_aligned(temporary, spec)
        os.replace(temporary, raster_path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    record = LandMask(
        grid_id=grid.grid_id, version=LAND_MASK_VERSION,
        coastline_source=CoastlineSource(
            dataset="GSHHG full-resolution level 1", version=coastline_version,
            sha256=_file_sha256(coastline_path),
        ),
        raster=ArtifactRef(
            role="land_mask", relpath=raster_path.name, sha256=_file_sha256(raster_path),
            size=raster_path.stat().st_size, media_type="image/tiff; application=geotiff",
        ),
        land_pixels=int(land.sum()),
    )
    temporary_record = record_path.with_name(f".{record_path.name}.tmp")
    temporary_record.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_record, record_path)
    return record


def read_land(grid_dir: Path, grid: DeliveryGrid) -> np.ndarray:
    raster_path, _ = land_mask_paths(grid_dir)
    assert_aligned(raster_path, grid.spec)
    with rasterio.open(raster_path) as dataset:
        return dataset.read(1).astype(bool)
