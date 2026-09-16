"""Pre-extracted zone statistics for one observation (T8, T9); pure, no I/O."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from oceanos.domain import AncillaryTier, ObservationStatus, SeriesPoint
from oceanos.processing.quality import series_statistics

WHOLE_AOI_ZONE = "aoi"


def zone_series(
    *, zone_id: str, zone: np.ndarray, observation_id: str, observed_at: datetime,
    products: dict[str, tuple[np.ndarray, np.ndarray, str | None]], valid: np.ndarray,
    status: ObservationStatus, release_id: str | None, tier: AncillaryTier,
) -> list[SeriesPoint]:
    """One row per product; a gap (no usable observation) is still a row with ``statistics=None``.

    ``products`` maps a product key to (values, analysis mask, unit). Statistics use full-resolution
    pixels inside ``zone`` ∩ analysis ∩ valid, with the zone's analysis pixels as the denominator.
    """
    usable = status is ObservationStatus.USABLE
    rows: list[SeriesPoint] = []
    for key, (values, analysis, unit) in sorted(products.items()):
        region = zone & analysis
        statistics = series_statistics(values, region & valid, int(region.sum())) if usable else None
        rows.append(SeriesPoint(
            zone_id=zone_id, observation_id=observation_id, datetime=observed_at, product_key=key, unit=unit,
            status=status, statistics=statistics, release_id=release_id, tier=tier,
        ))
    return rows
