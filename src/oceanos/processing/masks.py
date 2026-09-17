"""Grid-specific land and analysis masks derived from OCEANOS-owned CUDEM elevation (DA-1 amended, DA-3).

Land is CUDEM elevation above 0 m (PRVD02, ≈ local mean sea level). GSHHG was the original land
source, but at La Parguera it is displaced ≈ 380 m south and ≈ 150 m west and misses the cays
(DA-6 review, 2026-09-15), so both the land mask and the coastal buffer use the bathymetry tiles.
"""

from __future__ import annotations

import os
import tempfile
from hashlib import sha256
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, shapes
from rasterio.vrt import WarpedVRT
from shapely.geometry import shape
from shapely.ops import unary_union

from oceanos.domain import (
    AnalysisMask,
    BathymetrySource,
    CoastlineSource,
    LandMask,
)
from oceanos.processing.grid import DeliveryGrid
from oceanos.processing.normalize import assert_aligned
from oceanos.storage import GEOTIFF_MEDIA_TYPE, artifact_ref, file_sha256

LAND_MASK_VERSION = "2"
ANALYSIS_MASK_VERSION = "2"
CUDEM_DATASET = "NOAA NCEI CUDEM 1/9 arc-second Puerto Rico"
CUDEM_VERSION = "2022v2"
LAND_DEFINITION = "elevation > 0 m (PRVD02), tile average on the delivery grid"


class AnalysisMaskError(RuntimeError):
    """The analysis mask leaves too few pixels for a product; a user decision is required."""


def _tile_set_sha256(paths: list[Path]) -> str:
    """One digest over the ordered (name, digest) pairs of a reference tile set."""
    digest = sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(f"{path.name}:{file_sha256(path)}\n".encode())
    return digest.hexdigest()


def _require_tiles(bathymetry_paths: list[Path]) -> None:
    if not bathymetry_paths or any(not path.is_file() for path in bathymetry_paths):
        raise FileNotFoundError("bathymetry tiles are missing; run scripts/fetch_reference_data.py bathymetry")


def _write_grid_raster(path: Path, grid: DeliveryGrid, data: np.ndarray, dtype: str, nodata: float | None, **tags: str) -> None:
    spec = grid.spec
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", suffix=".tif", delete=False) as stream:
            temporary = Path(stream.name)
        with rasterio.open(
            temporary, "w", driver="GTiff", count=1, dtype=dtype, nodata=nodata,
            crs=spec.crs, transform=spec.transform, width=spec.width, height=spec.height,
            tiled=True, blockxsize=256, blockysize=256, compress="deflate",
        ) as destination:
            destination.write(data.astype(dtype), 1)
            destination.update_tags(**tags)
        assert_aligned(temporary, spec)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _write_record(path: Path, record: LandMask | AnalysisMask) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def elevation_on_grid(bathymetry_paths: list[Path], grid: DeliveryGrid) -> np.ndarray:
    """Average elevation tiles onto the grid (metres, positive up); NaN where no tile has data."""
    spec = grid.spec
    elevation = np.full((spec.height, spec.width), np.nan, dtype="float32")
    for path in sorted(bathymetry_paths):
        with rasterio.open(path) as source, WarpedVRT(
            source, crs=spec.crs, transform=spec.transform, width=spec.width, height=spec.height,
            resampling=Resampling.average, src_nodata=source.nodata, nodata=np.nan, dtype="float32",
        ) as warped:
            tile = warped.read(1)
        fill = np.isnan(elevation) & np.isfinite(tile)
        elevation[fill] = tile[fill]
    return elevation


def land_from_elevation(elevation: np.ndarray) -> np.ndarray:
    """Land where the grid-averaged elevation is above 0 m; unknown elevation is not land."""
    with np.errstate(invalid="ignore"):
        return np.asarray(np.isfinite(elevation) & (elevation > 0))


def coastal_buffer(land: np.ndarray, grid: DeliveryGrid, buffer_m: float) -> np.ndarray:
    """True where a pixel centre lies on land or within ``buffer_m`` of a land pixel's footprint."""
    spec = grid.spec
    if not land.any():
        return np.zeros(land.shape, dtype=bool)
    polygons = [
        shape(geometry)
        for geometry, value in shapes(land.astype("uint8"), mask=land, transform=spec.transform)
        if value == 1
    ]
    buffered = unary_union(polygons).buffer(buffer_m)
    within = geometry_mask([buffered.__geo_interface__], land.shape, spec.transform, invert=True)
    return np.asarray(within | land)


def land_mask_paths(grid_dir: Path) -> tuple[Path, Path]:
    return grid_dir / "land_mask.tif", grid_dir / "land_mask.json"


def _land_source(bathymetry_paths: list[Path]) -> CoastlineSource:
    return CoastlineSource(
        dataset=f"{CUDEM_DATASET}; land = {LAND_DEFINITION}", version=CUDEM_VERSION,
        sha256=_tile_set_sha256(bathymetry_paths),
    )


def load_land_mask(grid_dir: Path, grid: DeliveryGrid) -> LandMask | None:
    """Return the persisted mask only when it matches this grid, version and raster hash."""
    raster_path, record_path = land_mask_paths(grid_dir)
    if not record_path.is_file() or not raster_path.is_file():
        return None
    record = LandMask.model_validate_json(record_path.read_text(encoding="utf-8"))
    if (
        record.grid_id != grid.grid_id
        or record.version != LAND_MASK_VERSION
        or file_sha256(raster_path) != record.raster.sha256
    ):
        return None
    assert_aligned(raster_path, grid.spec)
    return record


def ensure_land_mask(grid_dir: Path, grid: DeliveryGrid, bathymetry_paths: list[Path]) -> LandMask:
    """Build the land mask once per grid from CUDEM; reuse a verified existing one."""
    existing = load_land_mask(grid_dir, grid)
    if existing is not None:
        return existing
    _require_tiles(bathymetry_paths)
    land = land_from_elevation(elevation_on_grid(bathymetry_paths, grid))
    raster_path, record_path = land_mask_paths(grid_dir)
    _write_grid_raster(raster_path, grid, land, "uint8", None, meaning="1=land,0=water",
                       land_mask_version=LAND_MASK_VERSION, land_definition=LAND_DEFINITION)
    record = LandMask(
        grid_id=grid.grid_id, version=LAND_MASK_VERSION, coastline_source=_land_source(bathymetry_paths),
        raster=artifact_ref(raster_path, grid_dir, "land_mask", GEOTIFF_MEDIA_TYPE),
        land_pixels=int(land.sum()),
    )
    _write_record(record_path, record)
    return record


def read_land(grid_dir: Path, grid: DeliveryGrid) -> np.ndarray:
    raster_path, _ = land_mask_paths(grid_dir)
    assert_aligned(raster_path, grid.spec)
    with rasterio.open(raster_path) as dataset:
        return np.asarray(dataset.read(1)).astype(bool)


def analysis_mask_paths(grid_dir: Path) -> tuple[Path, Path, Path]:
    return grid_dir / "coastal_buffer.tif", grid_dir / "depth_m.tif", grid_dir / "analysis_mask.json"


def product_analysis(buffer: np.ndarray, depth: np.ndarray, shallow_exclusion_m: float | None) -> np.ndarray:
    """Pixels counted in a product's statistics: outside the coastal buffer and, if set, deep enough."""
    analysis = ~buffer
    if shallow_exclusion_m is not None:
        with np.errstate(invalid="ignore"):
            analysis &= np.isfinite(depth) & (depth >= shallow_exclusion_m)
    return analysis


def ensure_analysis_mask(
    grid_dir: Path, grid: DeliveryGrid, *, bathymetry_paths: list[Path], coastal_buffer_m: float,
    shallow_exclusion_m: dict[str, float | None], min_analysis_pixels: int,
) -> AnalysisMask:
    """Build (or reuse) the grid's analysis mask and enforce the analysis-pixel guard."""
    buffer_path, depth_path, record_path = analysis_mask_paths(grid_dir)
    record: AnalysisMask | None = None
    if record_path.is_file() and buffer_path.is_file() and depth_path.is_file():
        candidate = AnalysisMask.model_validate_json(record_path.read_text(encoding="utf-8"))
        if (
            candidate.grid_id == grid.grid_id and candidate.version == ANALYSIS_MASK_VERSION
            and candidate.coastal_buffer_m == coastal_buffer_m
            and candidate.shallow_exclusion_m == shallow_exclusion_m
            and file_sha256(buffer_path) == candidate.coastal_buffer.sha256
            and file_sha256(depth_path) == candidate.depth.sha256
        ):
            record = candidate
    if record is None:
        _require_tiles(bathymetry_paths)
        elevation = elevation_on_grid(bathymetry_paths, grid)
        buffer = coastal_buffer(land_from_elevation(elevation), grid, coastal_buffer_m)
        depth = -elevation
        _write_grid_raster(buffer_path, grid, buffer, "uint8", None, meaning=f"1=land or within {coastal_buffer_m} m of land")
        _write_grid_raster(depth_path, grid, depth, "float32", float("nan"), meaning="depth below PRVD02, metres, positive down")
        record = AnalysisMask(
            grid_id=grid.grid_id, version=ANALYSIS_MASK_VERSION, coastal_buffer_m=coastal_buffer_m,
            coastline_source=_land_source(bathymetry_paths),
            bathymetry_source=BathymetrySource(
                dataset=CUDEM_DATASET, version=CUDEM_VERSION, sha256=_tile_set_sha256(bathymetry_paths),
            ),
            coastal_buffer=artifact_ref(buffer_path, grid_dir, "coastal_buffer", GEOTIFF_MEDIA_TYPE),
            depth=artifact_ref(depth_path, grid_dir, "depth", GEOTIFF_MEDIA_TYPE),
            water_pixels=int((~buffer).sum()),
            analysis_pixels={key: int(product_analysis(buffer, depth, cut).sum()) for key, cut in shallow_exclusion_m.items()},
            shallow_exclusion_m=dict(shallow_exclusion_m),
        )
        _write_record(record_path, record)
    short = {key: count for key, count in record.analysis_pixels.items() if count < min_analysis_pixels}
    if short:
        raise AnalysisMaskError(
            f"analysis pixels below {min_analysis_pixels} for {sorted(short)}; the shelf may be too shallow "
            "for these products (user decision required)"
        )
    return record


def read_analysis_layers(grid_dir: Path, grid: DeliveryGrid) -> tuple[np.ndarray, np.ndarray]:
    """Return (coastal buffer, depth) arrays after exact alignment checks."""
    buffer_path, depth_path, _ = analysis_mask_paths(grid_dir)
    for path in (buffer_path, depth_path):
        assert_aligned(path, grid.spec)
    with rasterio.open(buffer_path) as buffer, rasterio.open(depth_path) as depth:
        return np.asarray(buffer.read(1)).astype(bool), np.asarray(depth.read(1))
