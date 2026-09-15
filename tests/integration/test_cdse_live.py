"""Opt-in live verification of the bounded Phase 1 CDSE window."""

from pathlib import Path

import pytest

from oceanos.aoi import load_aoi
from oceanos.catalog import CdseODataProvider
from oceanos.config import load_config
from oceanos.pipeline.plan import group_overpasses, select_minimal_cover
from oceanos.processing.grid import build_delivery_grid

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_phase1_window_selects_only_19qgv() -> None:
    settings = load_config(ROOT / "configs/mvp.yaml")
    aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
    provider = CdseODataProvider(
        settings.scenes.catalogue_url, settings.scenes.download_url,
        timeout=settings.scenes.timeout, max_retries=settings.scenes.max_retries,
        page_size=settings.scenes.page_size,
    )
    groups = group_overpasses(provider.search(aoi, "2026-06-01", "2026-09-01"))
    assert groups
    grid = build_delivery_grid(aoi)
    assert {
        select_minimal_cover(scenes, grid).selected for scenes in groups.values()
    } == {("19QGV",)}
