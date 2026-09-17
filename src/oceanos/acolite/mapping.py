"""Pinned Sentinel-2 MSI band-to-variable mapping."""

from __future__ import annotations

from typing import Literal

Platform = Literal["S2A", "S2B", "S2C"]
Band = Literal["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B10", "B11", "B12"]

_BANDS: tuple[Band, ...] = (
    "B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B10", "B11", "B12",
)
_WAVELENGTHS: dict[Platform, tuple[int, ...]] = {
    "S2A": (443, 492, 560, 665, 704, 740, 783, 833, 865, 945, 1373, 1614, 2202),
    "S2B": (442, 492, 559, 665, 704, 739, 780, 833, 864, 943, 1377, 1610, 2186),
    "S2C": (444, 489, 561, 667, 707, 741, 785, 835, 866, 947, 1372, 1612, 2191),
}
_BAND_INDEX: dict[str, int] = {band: index for index, band in enumerate(_BANDS)}


def platform_wavelengths(platform: Platform) -> tuple[int, ...]:
    """Return all researched wavelengths in MSI band order."""
    try:
        return _WAVELENGTHS[platform]
    except KeyError as exc:
        raise ValueError(f"unsupported Sentinel-2 platform: {platform}") from exc


def science_wavelengths(platform: Platform) -> tuple[int, ...]:
    """Return bands for which the pinned run emits corrected reflectance."""
    return tuple(
        wavelength for band, wavelength in zip(_BANDS, platform_wavelengths(platform), strict=True)
        if band not in {"B09", "B10"}
    )


def acolite_variable(
    platform: Platform, band: str, family: Literal["rhos", "rhow", "Rrs", "rhorc"],
) -> str:
    """Build the exact platform-specific ACOLITE variable name.

    ``band`` is an MSI band name; an unknown one is a ``ValueError``, so callers
    never silently resolve to the wrong wavelength.
    """
    try:
        index = _BAND_INDEX[band]
    except KeyError as exc:
        raise ValueError(f"unknown Sentinel-2 band: {band}") from exc
    return f"{family}_{platform_wavelengths(platform)[index]}"
