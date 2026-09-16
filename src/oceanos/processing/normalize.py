"""Delivery-grid conformance and windowed normalization; no radiometric calibration or indices."""

import math
import os
import tempfile
import warnings
from hashlib import sha256
from pathlib import Path
from typing import Literal

import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.windows import Window

from oceanos.domain import (
    ArtifactRef,
    ConformedLayer,
    FailureCode,
    LandMaskRef,
    LayerSource,
)
from oceanos.processing.grid import DeliveryGrid, GridSpec

BLOCK_SIZE = 256
# Sub-pixel tolerance for phase alignment of floating-point origins (one millionth of a pixel).
_PHASE_TOLERANCE_PX = 1e-6


class NormalizationError(RuntimeError):
    """Normalization could not produce a complete aligned output set."""


class ConformError(RuntimeError):
    """P5 conformance refused a layer; carries the contract failure code."""

    def __init__(self, code: FailureCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code


def assert_aligned(path: str | Path, grid: GridSpec) -> None:
    """Require exact equality, including bounds derived from the stored transform."""
    with rasterio.open(path) as dataset:
        if (dataset.crs, dataset.transform, dataset.width, dataset.height, tuple(dataset.bounds)) != (
            grid.crs, grid.transform, grid.width, grid.height, grid.bounds,
        ):
            raise NormalizationError(f"Raster is not exactly aligned to GridSpec: {path}")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _phase_offset(source_origin: float, grid_origin: float, resolution: float, label: str) -> int:
    offset = (source_origin - grid_origin) / resolution
    nearest = round(offset)
    if abs(offset - nearest) > _PHASE_TOLERANCE_PX:
        raise ConformError(FailureCode.GRID_MISALIGNED, f"{label} origin is not phase-aligned to the delivery grid")
    return int(nearest)


def conform_layer(
    container: Path, variable: str, destination: Path, grid: DeliveryGrid, *,
    product_key: str, kind: Literal["continuous", "binary", "bitfield", "display"],
    unit: str | None, source: LayerSource, out_of_scene_value: int | None = None,
    land: np.ndarray | None = None, land_mask: LandMaskRef | None = None,
    tier_root: Path,
) -> ConformedLayer:
    """Copy one archived NetCDF variable onto the delivery grid without resampling (P5).

    The source must share the grid CRS and resolution and be phase-aligned; otherwise
    ``grid.misaligned``. Grid cells outside the source extent become NaN for continuous
    layers and ``out_of_scene_value`` for bitfields. ``land`` (True = land) sets
    continuous values to NaN and is never applied to bitfields.
    """
    spec = grid.spec
    bitfield = kind == "bitfield"
    if bitfield and out_of_scene_value is None:
        raise ValueError("bitfield conformance requires the out-of-scene flag value")
    if bitfield and land is not None:
        raise ValueError("bitfield layers are never land-masked")
    if land is not None and land.shape != (spec.height, spec.width):
        raise ValueError("land mask shape must equal the delivery grid")
    dataset_name = f'NETCDF:"{container}":{variable}'
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(dataset_name) as dataset:
            if dataset.count != 1 or dataset.crs is None or dataset.crs != spec.crs:
                raise ConformError(FailureCode.GRID_MISALIGNED, "source CRS differs from the delivery grid")
            transform = dataset.transform
            if (transform.a, transform.b, transform.d, transform.e) != (spec.resolution, 0, 0, -spec.resolution):
                raise ConformError(FailureCode.GRID_MISALIGNED, "source pixels differ from the delivery grid resolution")
            expected_dtype = "int32" if bitfield else "float32"
            if dataset.dtypes[0] != expected_dtype:
                raise ValueError(f"{kind} layers require {expected_dtype} input, got {dataset.dtypes[0]}")
            column = _phase_offset(transform.c, spec.transform.c, spec.resolution, "column")
            row = _phase_offset(spec.transform.f, transform.f, spec.resolution, "row")
            # Grid index range covered by the source raster.
            left, top = max(column, 0), max(row, 0)
            right, bottom = min(column + dataset.width, spec.width), min(row + dataset.height, spec.height)
            if right <= left or bottom <= top:
                raise ConformError(FailureCode.GRID_NO_INTERSECTION, "source extent does not intersect the delivery grid")
            window = Window(left - column, top - row, right - left, bottom - top)
            data = dataset.read(1, window=window, masked=True)
            nodata = dataset.nodata

    if bitfield:
        assert out_of_scene_value is not None
        output = np.full((spec.height, spec.width), out_of_scene_value, dtype="int32")
        output[top:bottom, left:right] = data.filled(out_of_scene_value)
    else:
        output = np.full((spec.height, spec.width), np.nan, dtype="float32")
        values = data.astype("float32").filled(np.nan)
        if nodata is not None and math.isfinite(nodata):
            values[values == np.float32(nodata)] = np.nan
        output[top:bottom, left:right] = values
        if land is not None:
            output[land] = np.nan
    coverage = ((right - left) * (bottom - top)) / (spec.width * spec.height)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}-", suffix=".tif", delete=False) as stream:
            temporary = Path(stream.name)
        profile = {
            "driver": "GTiff", "count": 1, "dtype": "int32" if bitfield else "float32",
            "nodata": None if bitfield else float("nan"),
            "crs": spec.crs, "transform": spec.transform, "width": spec.width, "height": spec.height,
            "tiled": True, "blockxsize": BLOCK_SIZE, "blockysize": BLOCK_SIZE,
            "compress": "deflate", "predictor": 2 if bitfield else 3, "BIGTIFF": "IF_SAFER",
        }
        with rasterio.open(temporary, "w", **profile) as written:
            written.write(output, 1)
            if unit is not None:
                written.set_band_unit(1, unit)
            written.update_tags(
                product_key=product_key, conform_method="copy", grid_id=grid.grid_id,
                grid_coverage_fraction=repr(coverage), land_masked=str(land is not None),
            )
        assert_aligned(temporary, spec)
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

    return ConformedLayer(
        product_key=product_key, kind=kind,
        raster=ArtifactRef(
            role=product_key, relpath=destination.relative_to(tier_root).as_posix(),
            sha256=_file_sha256(destination), size=destination.stat().st_size,
            media_type="image/tiff; application=geotiff",
        ),
        data_type="int32" if bitfield else "float32", nodata=None if bitfield else "nan",
        unit=unit, source=source, grid_id=grid.grid_id, method="copy",
        grid_coverage_fraction=coverage, land_mask=land_mask,
    )
