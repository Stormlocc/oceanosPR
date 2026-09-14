"""Windowed spatial normalization; no radiometric calibration or indices."""

import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from shapely.geometry import mapping

from oceanos.aoi import AOI
from oceanos.catalog import LocalSceneCatalog
from oceanos.ingestion.fetch import MVP_BANDS, load_materialized_bands
from oceanos.processing.grid import GridSpec, buffered_aoi, build_grid

BLOCK_SIZE = 256


class NormalizationError(RuntimeError):
    """Normalization could not produce a complete aligned output set."""


def assert_aligned(path: str | Path, grid: GridSpec) -> None:
    """Require exact equality, including bounds derived from the stored transform."""
    with rasterio.open(path) as dataset:
        if (dataset.crs, dataset.transform, dataset.width, dataset.height, tuple(dataset.bounds)) != (
            grid.crs, grid.transform, grid.width, grid.height, grid.bounds,
        ):
            raise NormalizationError(f"Raster is not exactly aligned to GridSpec: {path}")


def normalize_band(
    source_path: str | Path, destination_path: str | Path, grid: GridSpec, *,
    clip_geometry=None, categorical: bool = False,
    resampling_method: Literal["nearest", "bilinear"] | None = None,
    warp_memory_limit_mb: int = 64,
) -> dict:
    """Write one tiled Float32 GeoTIFF in blocks, preserving scale and offset.

    Nodata/masks from the source and pixel centers outside clip_geometry become
    NaN. Categorical data always use nearest; an explicit bilinear request fails.
    clip_geometry must be in the GridSpec CRS. Output values remain in source
    numeric units, without applying any reflectance scaling or index calculation.
    """
    method = resampling_method or ("nearest" if categorical else "bilinear")
    if method not in {"nearest", "bilinear"} or (categorical and method != "nearest"):
        raise ValueError("Categories require nearest; continuous data allow nearest or bilinear")
    if not isinstance(warp_memory_limit_mb, int) or warp_memory_limit_mb <= 0:
        raise ValueError("warp_memory_limit_mb must be a positive integer")
    source_path, destination_path = Path(source_path).resolve(), Path(destination_path).resolve()
    if source_path == destination_path:
        raise ValueError("Normalized output must not overwrite the source raster")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with rasterio.Env(GDAL_CACHEMAX=warp_memory_limit_mb * 1024**2), rasterio.open(source_path) as source:
            if source.crs is None or source.count != 1:
                raise ValueError("Source must be a georeferenced single-band raster")
            if source.dtypes[0] not in {"uint8", "int8", "uint16", "int16", "float32"}:
                raise ValueError("MVP normalization supports up to 16-bit integers or Float32 inputs")
            native_resolution = list(source.res)
            native_crs = source.crs.to_string()
            native_units = "degree" if source.crs.is_geographic else source.crs.linear_units
            with tempfile.NamedTemporaryFile(dir=destination_path.parent, suffix=".tif", delete=False) as stream:
                temporary = Path(stream.name)
            profile = {
                "driver": "GTiff", "count": 1, "dtype": "float32", "nodata": float("nan"),
                "crs": grid.crs, "transform": grid.transform, "width": grid.width, "height": grid.height,
                "tiled": True, "blockxsize": BLOCK_SIZE, "blockysize": BLOCK_SIZE,
                "compress": "deflate", "predictor": 3, "BIGTIFF": "IF_SAFER",
            }
            with WarpedVRT(
                source, crs=grid.crs, transform=grid.transform, width=grid.width, height=grid.height,
                src_nodata=source.nodata, nodata=float("nan"), dtype="float32",
                resampling=Resampling[method], warp_mem_limit=warp_memory_limit_mb,
            ) as warped, rasterio.open(temporary, "w", **profile) as destination:
                for _, window in destination.block_windows(1):
                    data = warped.read(1, window=window, masked=True).filled(np.nan)
                    if clip_geometry is not None:
                        outside = geometry_mask(
                            [mapping(clip_geometry)], out_shape=data.shape,
                            transform=destination.window_transform(window), all_touched=False,
                        )
                        data[outside] = np.nan
                    destination.write(data, 1, window=window)
                destination.scales = source.scales
                destination.offsets = source.offsets
                if source.units[0] is not None:
                    destination.set_band_unit(1, source.units[0])
                destination.update_tags(
                    native_resolution=json.dumps(native_resolution), native_crs=native_crs,
                    native_resolution_units=native_units,
                    processing_resolution=str(grid.resolution), processing_resolution_units="metre",
                    resampling_method=method, data_kind="categorical" if categorical else "continuous",
                    source_path=str(source_path), source_nodata=str(source.nodata),
                )
            assert_aligned(temporary, grid)
        os.replace(temporary, destination_path)
        return {
            "source_path": str(source_path), "local_path": destination_path.name,
            "native_resolution": native_resolution, "processing_resolution": grid.resolution,
            "native_crs": native_crs, "native_resolution_units": native_units,
            "processing_resolution_units": "metre",
            "resampling_method": method, "dtype": "float32", "nodata": "NaN",
            "file_size": destination_path.stat().st_size,
        }
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _peak_memory_bytes() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def normalize_scene(
    catalog: LocalSceneCatalog, scene_id: str, aoi: AOI, *,
    raw_dir: str | Path = "data/raw", intermediate_dir: str | Path = "data/intermediate",
    target_crs: str | None = None, resolution: float = 10, buffer_m: float = 0,
    reference_band: str = "B02", continuous_resampling: Literal["nearest", "bilinear"] = "bilinear",
    warp_memory_limit_mb: int = 64,
) -> dict:
    """Normalize the five verified local MVP bands using one common grid.

    Work is staged in a separate directory. The output set is only replaced
    after all bands pass exact alignment checks. Intended for one writer.
    """
    scene = catalog.get_scene(scene_id)
    if scene is None:
        raise NormalizationError(f"Scene does not exist in local catalog: {scene_id}")
    paths = load_materialized_bands(scene, raw_dir)
    if reference_band not in {"B02", "B03", "B04", "B08"}:
        raise ValueError("Reference must be a native 10 m MVP band: B02, B03, B04 or B08")
    grid = build_grid(paths[reference_band], aoi, target_crs=target_crs, resolution=resolution, buffer_m=buffer_m)
    clip = buffered_aoi(aoi, grid.crs, buffer_m)
    parent = Path(intermediate_dir).expanduser().resolve() / scene_id
    parent.mkdir(parents=True, exist_ok=True)
    output = parent / "normalized"
    if output.is_symlink() or parent.resolve() != parent:
        raise NormalizationError("Output scene directory must not contain symbolic links")
    staging = Path(tempfile.mkdtemp(prefix=".normalized-", dir=parent))
    backup = None
    try:
        bands = {}
        for band in MVP_BANDS:
            bands[band] = normalize_band(
                paths[band], staging / f"{band}.tif", grid, clip_geometry=clip,
                resampling_method=continuous_resampling, warp_memory_limit_mb=warp_memory_limit_mb,
            )
        for band in MVP_BANDS:
            assert_aligned(staging / f"{band}.tif", grid)
        report = {
            "schema_version": "1.0", "scene_id": scene_id,
            "normalized_at": datetime.now(UTC).isoformat(),
            "grid": grid.to_dict(), "reference_band": reference_band, "buffer_m": buffer_m,
            "output_directory": str(output), "bands": bands,
            "output_size_bytes": sum(band["file_size"] for band in bands.values()),
            "uncompressed_size_bytes": grid.width * grid.height * len(bands) * 4,
            "peak_process_memory_bytes": _peak_memory_bytes(),
            "warp_memory_limit_mb": warp_memory_limit_mb, "gdal_cache_limit_mb": warp_memory_limit_mb,
            "block_size": BLOCK_SIZE,
        }
        (staging / "manifest.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        if output.exists():
            backup = Path(tempfile.mkdtemp(prefix=".normalized-backup-", dir=parent))
            backup.rmdir()
            os.replace(output, backup)
        try:
            os.replace(staging, output)
        except OSError:
            if backup is not None:
                os.replace(backup, output)
            raise
        if backup is not None:
            shutil.rmtree(backup)
        return report
    finally:
        if staging.exists():
            shutil.rmtree(staging)
