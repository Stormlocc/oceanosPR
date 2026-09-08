"""Spatial band normalization, without scientific index calculation."""

from oceanos.processing.grid import GridSpec, build_grid
from oceanos.processing.normalize import NormalizationError, assert_aligned, normalize_band, normalize_scene

__all__ = ["GridSpec", "build_grid", "NormalizationError", "assert_aligned", "normalize_band", "normalize_scene"]
