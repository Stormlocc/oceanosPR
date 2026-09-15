"""Spatial band normalization, without scientific index calculation."""

from oceanos.processing.grid import (
    DeliveryGrid,
    GridSpec,
    build_delivery_grid,
    build_grid,
)
from oceanos.processing.normalize import (
    NormalizationError,
    assert_aligned,
    normalize_band,
)

__all__ = [
    "DeliveryGrid", "GridSpec", "NormalizationError", "assert_aligned",
    "build_delivery_grid", "build_grid", "normalize_band",
]
