"""AnalysisMask (DA-3, B7): coastal buffer, per-product shallow cut and analysis-pixel guard."""

from __future__ import annotations

import socket
from pathlib import Path

import numpy as np
import pytest
from support.pipeline_env import BATHYMETRY, window_grid

from oceanos.processing import assert_aligned
from oceanos.processing.masks import (
    AnalysisMaskError,
    analysis_mask_paths,
    ensure_analysis_mask,
    product_analysis,
    read_analysis_layers,
)
from oceanos.processing.quality import series_statistics

AOI_ID = "aoi-la-parguera-0123456789ab"
CUTS = {"tur_nechad2016": 7.0, "spm_nechad2016": 7.0, "chl_re_gons740": 7.0, "fai": None, "fait": None, "ndvi": None}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Mask tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _build(directory: Path, cuts=CUTS, minimum=10_000):
    return ensure_analysis_mask(
        directory, window_grid(AOI_ID), bathymetry_paths=[BATHYMETRY],
        coastal_buffer_m=150, shallow_exclusion_m=cuts, min_analysis_pixels=minimum,
    )


def test_fixture_window_counts_clear_the_20k_recheck(tmp_path: Path) -> None:
    record = _build(tmp_path)
    # CUDEM land + 150 m buffer; window.json's GSHHG-based 53 750 predates the DA-1 amendment.
    assert record.water_pixels == 58_481
    for key in ("tur_nechad2016", "spm_nechad2016", "chl_re_gons740"):
        assert record.analysis_pixels[key] >= 20_000
        assert record.analysis_pixels[key] < record.water_pixels
    assert record.analysis_pixels["fai"] == record.water_pixels
    assert record.bathymetry_source.version == "2022v2" and record.coastal_buffer_m == 150
    assert record.coastline_source.sha256 == record.bathymetry_source.sha256
    for path in analysis_mask_paths(tmp_path)[:2]:
        assert_aligned(path, window_grid(AOI_ID).spec)


def test_depth_is_positive_offshore_and_mask_is_reused_until_cuts_change(tmp_path: Path) -> None:
    first = _build(tmp_path)
    buffer, depth = read_analysis_layers(tmp_path, window_grid(AOI_ID))
    offshore = ~buffer
    assert np.isfinite(depth[offshore]).all() and (depth[offshore] > 0).mean() > 0.99
    stamp = analysis_mask_paths(tmp_path)[1].stat().st_mtime_ns

    assert _build(tmp_path) == first
    assert analysis_mask_paths(tmp_path)[1].stat().st_mtime_ns == stamp
    changed = _build(tmp_path, cuts={**CUTS, "tur_nechad2016": 10.0})
    assert changed.analysis_pixels["tur_nechad2016"] < first.analysis_pixels["tur_nechad2016"]


def test_guard_trips_when_the_mask_leaves_too_few_pixels(tmp_path: Path) -> None:
    with pytest.raises(AnalysisMaskError, match="tur_nechad2016"):
        _build(tmp_path, cuts={"tur_nechad2016": 60.0, "fai": None})


def test_fai_statistics_include_shallow_pixels_and_turbidity_excludes_them(tmp_path: Path) -> None:
    _build(tmp_path)
    buffer, depth = read_analysis_layers(tmp_path, window_grid(AOI_ID))
    shallow = ~buffer & (depth < 7)
    assert shallow.sum() > 1_000
    values = np.where(shallow, 1000.0, 1.0).astype("float32")
    valid = np.ones(values.shape, dtype=bool)

    tur_analysis = product_analysis(buffer, depth, 7.0)
    fai_analysis = product_analysis(buffer, depth, None)
    tur = series_statistics(values, tur_analysis & valid, int(tur_analysis.sum()))
    fai = series_statistics(values, fai_analysis & valid, int(fai_analysis.sum()))
    assert tur is not None and fai is not None
    assert tur.median == tur.p90 == 1.0 and tur.mean == 1.0
    assert fai.mean > 1.0 and fai.valid_pixels == tur.valid_pixels + int(shallow.sum())
