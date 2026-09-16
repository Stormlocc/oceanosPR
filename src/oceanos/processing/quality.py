"""Pure quality core: valid-pixel predicate, observation gates and series statistics (DA-2, V8).

No I/O. Arrays are full-resolution layers already conformed to one delivery grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from oceanos.domain import (
    AerosolEvidence,
    AncillaryEvidence,
    FlagSpec,
    FlagStatistics,
    ObservationStatus,
    ProductQuality,
    QualityPolicy,
    QualityReport,
    RangeViolation,
    SeriesStatistics,
    SunViewGeometry,
    UsabilityVerdict,
)

# Flag names (FlagBit.name) that exclude a pixel; bit positions always come from the run's FlagSpec.
CLOUD_FLAGS = ("cirrus", "high_toa")
EXCLUDING_FLAGS = ("cirrus", "high_toa", "negative_surface_reflectance")
NEGATIVE_REFLECTANCE_FLAG = "negative_surface_reflectance"
OUT_OF_SCENE_FLAG = "out_of_scene"

REASON_ANCILLARY_FALLBACK = "quality.ancillary_fallback"
REASON_INCOMPLETE_COVERAGE = "quality.incomplete_coverage"
REASON_AEROSOL = "quality.aerosol_out_of_bounds"
REASON_NEGATIVE_REFLECTANCE = "quality.residual_glint_negative_reflectance"
REASON_RESIDUAL_SWIR = "quality.residual_glint_swir"
REASON_OUT_OF_RANGE = "quality.out_of_range"
REASON_BELOW_VALID_FRACTION = "quality.below_valid_fraction"


def specular_angle_deg(geometry: SunViewGeometry) -> float:
    """Angle between the view direction and the specular reflection of the sun (OCEANOS derivation)."""
    sza, vza, raa = (math.radians(value) for value in (geometry.sza, geometry.vza, geometry.raa))
    cosine = math.cos(sza) * math.cos(vza) + math.sin(sza) * math.sin(vza) * math.cos(raa)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def dilate(mask: np.ndarray, radius_px: int) -> np.ndarray:
    """Square binary dilation without wrap-around."""
    if radius_px <= 0 or not mask.any():
        return mask.copy()
    height, width = mask.shape
    padded = np.pad(mask, radius_px, constant_values=False)
    out = np.zeros_like(mask)
    for dy in range(-radius_px, radius_px + 1):
        for dx in range(-radius_px, radius_px + 1):
            out |= padded[radius_px + dy:radius_px + dy + height, radius_px + dx:radius_px + dx + width]
    return out


def _bit(flag_spec: FlagSpec, name: str) -> int:
    for flag in flag_spec.bits:
        if flag.name == name:
            return flag.bit
    raise ValueError(f"FlagSpec has no bit named {name}")


def flag_set(flags: np.ndarray, flag_spec: FlagSpec, name: str) -> np.ndarray:
    return ((flags >> _bit(flag_spec, name)) & 1).astype(bool)


def valid_flag_pixels(flags: np.ndarray, flag_spec: FlagSpec, cloud_dilation_px: int) -> np.ndarray:
    """V8 predicate on flags only: cirrus/high-TOA (dilated) and negative reflectance clear.

    The SWIR threshold bit is informational and never excludes; out-of-scene pixels are excluded.
    """
    cloud = np.zeros(flags.shape, dtype=bool)
    for name in CLOUD_FLAGS:
        cloud |= flag_set(flags, flag_spec, name)
    excluded = dilate(cloud, cloud_dilation_px)
    excluded |= flag_set(flags, flag_spec, NEGATIVE_REFLECTANCE_FLAG)
    excluded |= flag_set(flags, flag_spec, OUT_OF_SCENE_FLAG)
    return ~excluded


def series_statistics(values: np.ndarray, valid: np.ndarray, denominator: int) -> SeriesStatistics | None:
    samples = values[valid & np.isfinite(values)]
    if samples.size == 0 or denominator <= 0:
        return None
    p10, median, p90 = np.percentile(samples, [10, 50, 90])
    return SeriesStatistics(
        valid_pixels=int(samples.size), valid_fraction=min(1.0, samples.size / denominator),
        mean=float(samples.mean()), median=float(median), p10=float(p10), p90=float(p90), std=float(samples.std()),
    )


@dataclass
class ProductLayer:
    """One continuous product on the grid with its statistics mask."""

    values: np.ndarray
    analysis: np.ndarray
    gates_verdict: bool


@dataclass
class QualityInputs:
    observation_id: str
    attempt_id: str
    flags: np.ndarray
    flag_spec: FlagSpec
    water: np.ndarray
    products: dict[str, ProductLayer]
    grid_coverage_fraction: float
    aerosol: AerosolEvidence
    ancillary: AncillaryEvidence
    glint_angle_deg: float | None
    swir_rhow: np.ndarray | None
    policy: QualityPolicy
    valid: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        shapes = {self.flags.shape, self.water.shape, *(layer.values.shape for layer in self.products.values()),
                  *(layer.analysis.shape for layer in self.products.values())}
        if self.swir_rhow is not None:
            shapes.add(self.swir_rhow.shape)
        if len(shapes) != 1:
            raise ValueError("quality inputs must share one grid shape")
        self.valid = valid_flag_pixels(self.flags, self.flag_spec, self.policy.cloud_dilation_px)


def assess(inputs: QualityInputs) -> QualityReport:
    """Apply the gates in contract order and return the observation verdict."""
    policy = inputs.policy
    reasons: list[str] = []
    status = ObservationStatus.USABLE

    water = inputs.water
    water_count = int(water.sum())
    per_bit = {
        flag.name: int((((inputs.flags >> flag.bit) & 1).astype(bool) & water).sum())
        for flag in sorted(inputs.flag_spec.bits, key=lambda item: item.bit)
    }
    negative = per_bit.get(NEGATIVE_REFLECTANCE_FLAG, 0) / water_count if water_count else 0.0
    swir_p90: float | None = None
    if inputs.swir_rhow is not None:
        samples = inputs.swir_rhow[water & inputs.valid & np.isfinite(inputs.swir_rhow)]
        swir_p90 = float(np.percentile(samples, 90)) if samples.size else None

    # 1. Ancillary fallback.
    if inputs.ancillary.fallback_detected and policy.reject_on_ancillary_fallback:
        reasons.append(REASON_ANCILLARY_FALLBACK)
    # 2. Grid coverage.
    if inputs.grid_coverage_fraction < policy.min_grid_coverage:
        reasons.append(REASON_INCOMPLETE_COVERAGE)
        status = ObservationStatus.INCOMPLETE_COVERAGE
    # 3. Aerosol bounds.
    if inputs.aerosol.aot550 > policy.aot550_max or inputs.aerosol.aerosol_model not in policy.allowed_aerosol_models:
        reasons.append(REASON_AEROSOL)
    # 4. Residual glint (the glint angle is recorded, never gated).
    if negative > policy.max_negative_rhos_fraction:
        reasons.append(REASON_NEGATIVE_REFLECTANCE)
    if swir_p90 is not None and swir_p90 > policy.max_residual_swir_rhow:
        reasons.append(REASON_RESIDUAL_SWIR)

    qualities: list[ProductQuality] = []
    violations: list[RangeViolation] = []
    rules = {rule.product_key: rule for rule in policy.range_rules}
    for key, layer in sorted(inputs.products.items()):
        valid = layer.analysis & inputs.valid & np.isfinite(layer.values)
        analysis_count = int(layer.analysis.sum())
        valid_count = int(valid.sum())
        fraction = valid_count / analysis_count if analysis_count else 0.0
        qualities.append(ProductQuality(
            product_key=key, analysis_pixels=analysis_count, valid_pixels=valid_count,
            valid_fraction=fraction, gates_verdict=layer.gates_verdict,
        ))
        rule = rules.get(key)
        if rule is not None and valid_count:
            samples = layer.values[valid]
            offending = float(((samples < rule.min) | (samples > rule.max)).mean())
            if offending > rule.max_offending_fraction:
                violations.append(RangeViolation(product_key=key, rule=rule, offending_fraction=offending))
    # 5. Range rules.
    if any(inputs.products[violation.product_key].gates_verdict for violation in violations):
        reasons.append(REASON_OUT_OF_RANGE)
    # 6. Valid fraction per product, over that product's analysis pixels.
    if any(quality.gates_verdict and quality.valid_fraction < policy.min_valid_fraction for quality in qualities):
        reasons.append(REASON_BELOW_VALID_FRACTION)

    verdict = UsabilityVerdict.UNUSABLE if reasons else UsabilityVerdict.USABLE
    if verdict is UsabilityVerdict.UNUSABLE and status is ObservationStatus.USABLE:
        status = ObservationStatus.NO_USABLE_OBSERVATION
    return QualityReport(
        observation_id=inputs.observation_id, attempt_id=inputs.attempt_id, policy_version=policy.version,
        grid_coverage_fraction=inputs.grid_coverage_fraction,
        flags=FlagStatistics(water_pixels=water_count, valid_pixels=int((water & inputs.valid).sum()), per_bit_counts=per_bit),
        products=tuple(qualities), negative_rhos_fraction=negative, residual_swir_rhow_p90=swir_p90,
        aot550=inputs.aerosol.aot550, aerosol_model=inputs.aerosol.aerosol_model,
        glint_angle_deg=inputs.glint_angle_deg, range_violations=tuple(violations),
        ancillary=inputs.ancillary, verdict=verdict, status=status, reasons=tuple(reasons),
    )
