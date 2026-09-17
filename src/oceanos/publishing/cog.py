"""Cloud-Optimized GeoTIFFs with explicit, recorded compression and overview profiles."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

import rasterio
import rasterio.shutil

from oceanos.domain import CogProfile

# Los perfiles concretos son configuración versionada (`configs/publication.yaml`,
# `PublicationProfile`). Este módulo solo sabe aplicar un perfil, nunca elegirlo.


def overview_count(width: int, height: int, blocksize: int) -> int:
    """Halve until the largest side fits one block; always at least one level for display."""
    levels = 1
    while math.ceil(max(width, height) / 2**levels) > blocksize:
        levels += 1
    return levels


def write_cog(source: Path, destination: Path, profile: CogProfile) -> None:
    """Atomically translate a GeoTIFF into a COG using ``profile`` exactly (one band, or RGB for uint8)."""
    with rasterio.open(source) as dataset:
        bands_allowed = {3} if profile.data_type == "uint8" else {1}
        if dataset.count not in bands_allowed or any(dtype != profile.data_type for dtype in dataset.dtypes):
            raise ValueError(f"COG profile expects {profile.data_type} with {sorted(bands_allowed)} band(s): {source}")
        levels = overview_count(dataset.width, dataset.height, profile.blocksize)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}-", suffix=".tif", delete=False) as stream:
            temporary = Path(stream.name)
        rasterio.shutil.copy(
            source, temporary, driver="COG",
            COMPRESS=profile.compress, PREDICTOR=str(profile.predictor),
            OVERVIEW_RESAMPLING=profile.overview_resampling, OVERVIEW_COUNT=str(levels),
            BLOCKSIZE=str(profile.blocksize), BIGTIFF="IF_SAFER",
        )
        with rasterio.open(temporary) as written:
            if not written.overviews(1):
                raise RuntimeError(f"COG has no overviews: {destination}")
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
