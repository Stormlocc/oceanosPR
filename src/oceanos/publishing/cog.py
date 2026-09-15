"""Cloud-Optimized GeoTIFFs with explicit, recorded compression and overview profiles."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

import rasterio
import rasterio.shutil

from oceanos.domain import CogProfile

CONTINUOUS_COG = CogProfile(predictor=3, overview_resampling="AVERAGE", data_type="float32")
BITFIELD_COG = CogProfile(predictor=2, overview_resampling="MODE", data_type="int32")


def overview_count(width: int, height: int, blocksize: int) -> int:
    """Halve until the largest side fits one block; always at least one level for display."""
    levels = 1
    while math.ceil(max(width, height) / 2**levels) > blocksize:
        levels += 1
    return levels


def write_cog(source: Path, destination: Path, profile: CogProfile) -> None:
    """Atomically translate one single-band GeoTIFF into a COG using ``profile`` exactly."""
    with rasterio.open(source) as dataset:
        if dataset.count != 1 or dataset.dtypes[0] != profile.data_type:
            raise ValueError(f"COG profile expects one {profile.data_type} band: {source}")
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
