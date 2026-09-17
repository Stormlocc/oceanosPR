"""Resolve platform-neutral product specs to verified ACOLITE variables."""

from __future__ import annotations

import fnmatch
import re
from typing import Literal

from oceanos.acolite.mapping import Platform, acolite_variable
from oceanos.domain import AcoliteRunOutputs, AncillaryTier, ProductSpec

_WAVELENGTH_SUFFIX = re.compile(r"_(\d{3,4})$")
_ANCILLARY_TYPES: dict[AncillaryTier, Literal["GMAO_IT_MET", "GMAO_MERRA2_MET"]] = {
    AncillaryTier.PROVISIONAL: "GMAO_IT_MET",
    AncillaryTier.FINAL: "GMAO_MERRA2_MET",
}


class ProductResolutionError(ValueError):
    """A product spec does not resolve to exactly one verified variable."""


def ancillary_type_for(tier: AncillaryTier) -> Literal["GMAO_IT_MET", "GMAO_MERRA2_MET"]:
    """Return the ancillary source ACOLITE uses for a processing tier."""
    return _ANCILLARY_TYPES[tier]


def resolve_product(
    outputs: AcoliteRunOutputs, spec: ProductSpec,
) -> tuple[Literal["l2r", "l2w"], str, float | None]:
    """Return the container role, exact variable and centre wavelength for one spec."""
    l2r = set(outputs.l2r_variables)
    l2w = set(outputs.variables_present) - l2r
    matches = [
        (role, name)
        for role, names in (("l2w", l2w), ("l2r", l2r))
        for name in sorted(names)
        if fnmatch.fnmatchcase(name, spec.variable_pattern)
    ]
    if len(matches) != 1:
        raise ProductResolutionError(
            f"{spec.product_key} must resolve to exactly one variable, found {[name for _, name in matches]}"
        )
    role, name = matches[0]
    suffix = _WAVELENGTH_SUFFIX.search(name)
    wavelength = float(suffix.group(1)) if suffix else None
    return ("l2w" if role == "l2w" else "l2r"), name, wavelength


def surface_reflectance_bands(
    outputs: AcoliteRunOutputs, platform: Platform, bands: tuple[str, str, str],
) -> tuple[str, str, str]:
    """Return the L2R surface-reflectance variables for S2 band names (T2, T4)."""
    try:
        names = tuple(acolite_variable(platform, band, "rhos") for band in bands)
    except ValueError as exc:
        raise ProductResolutionError(str(exc)) from exc
    missing = [name for name in names if name not in outputs.l2r_variables]
    if missing:
        raise ProductResolutionError(f"surface reflectance variables missing from L2R: {missing}")
    return names[0], names[1], names[2]


def residual_swir_variable(outputs: AcoliteRunOutputs, platform: Platform) -> str | None:
    """Water reflectance at ~1610 nm (B11), used by the residual-glint gate; None if absent."""
    name = acolite_variable(platform, "B11", "rhow")
    return name if name in outputs.variables_present else None

