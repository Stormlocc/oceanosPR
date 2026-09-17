"""DA-2 gates (V8-amended valid-pixel predicate) over the pure quality core."""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest
import rasterio
import yaml
from support.pipeline_env import FIXTURES, ROOT

from oceanos.domain import (
    AerosolEvidence,
    AncillaryEvidence,
    FlagBit,
    FlagSpec,
    ObservationStatus,
    QualityPolicy,
    RangeRule,
    SunViewGeometry,
    UsabilityVerdict,
)
from oceanos.processing import quality
from oceanos.processing.quality import (
    ProductLayer,
    QualityInputs,
    assess,
    dilate,
    specular_angle_deg,
    valid_flag_pixels,
)

FLAG_SPEC = FlagSpec(bits=tuple(
    FlagBit(name=name, bit=bit, meaning=name, source_setting=f"flag_exponent_{bit}")
    for bit, name in enumerate(
        ("swir_threshold", "cirrus", "high_toa", "negative_surface_reflectance", "out_of_scene", "mixed_pixel", "dem_shadow")
    )
), usable_mask_value=47)
SHAPE = (100, 100)


def _policy(**update) -> QualityPolicy:
    policy = QualityPolicy.model_validate(yaml.safe_load((ROOT / "configs/quality.yaml").read_text(encoding="utf-8")))
    return policy.model_copy(update=update)


def _inputs(*, flags=None, products=None, coverage=1.0, aot=0.05, model="ACOLITE-LUT-202110-MOD1",
            fallback=False, swir=None, policy=None, shape=SHAPE) -> QualityInputs:
    everywhere = np.ones(shape, dtype=bool)
    return QualityInputs(
        observation_id="aoi-x-0123456789ab/S2A_20260702T150741_R082", attempt_id="att-20260915T120000Z-01234567",
        flags=np.zeros(shape, dtype="int32") if flags is None else flags, flag_spec=FLAG_SPEC, water=everywhere,
        products=products or {"tur_nechad2016": ProductLayer(np.full(shape, 2.0, "float32"), everywhere, True)},
        grid_coverage_fraction=coverage,
        aerosol=AerosolEvidence(aot550=aot, aerosol_model=model, dsf_fit_diagnostics="0.001"),
        ancillary=AncillaryEvidence(ancillary_type="GMAO_MERRA2_MET", uoz=0.3 if fallback else 0.28,
                                    uwv=1.5 if fallback else 4.3, pressure=1013.25 if fallback else 1003.4,
                                    wind=2.0 if fallback else 5.9, fallback_detected=fallback),
        glint_angle_deg=22.1, swir_rhow=swir, policy=policy or _policy(),
    )


def test_specular_angle_matches_known_scene_a_geometry() -> None:
    geometry = SunViewGeometry(sza=19.9961428493223, vza=3.000503679511415, raa=132.5435969592353)
    assert specular_angle_deg(geometry) == pytest.approx(22.13106635390421, abs=1e-9)
    assert specular_angle_deg(SunViewGeometry(sza=30, vza=30, raa=0)) == pytest.approx(0.0, abs=1e-6)


def test_dilation_does_not_wrap_and_valid_predicate_follows_v8() -> None:
    mask = np.zeros((5, 5), dtype=bool)
    mask[0, 0] = True
    assert dilate(mask, 1).sum() == 4 and not dilate(mask, 1)[4, 4]

    flags = np.zeros((7, 7), dtype="int32")
    flags[:, :] |= 1  # SWIR threshold bit everywhere: informational only
    flags[3, 3] |= 2  # cirrus, dilated by one pixel
    flags[0, 6] |= 8  # negative reflectance
    flags[6, 0] |= 16  # out of scene
    valid = valid_flag_pixels(flags, FLAG_SPEC, cloud_dilation_px=1)
    assert valid.sum() == 49 - 9 - 1 - 1
    assert not valid[2:5, 2:5].any() and not valid[0, 6] and not valid[6, 0]


def test_clean_observation_is_usable() -> None:
    report = assess(_inputs(swir=np.full(SHAPE, 0.001, "float32")))
    assert report.verdict is UsabilityVerdict.USABLE and report.status is ObservationStatus.USABLE
    assert report.reasons == () and report.products[0].valid_fraction == 1.0


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"fallback": True}, quality.REASON_ANCILLARY_FALLBACK),
    ({"coverage": 0.90}, quality.REASON_INCOMPLETE_COVERAGE),
    ({"aot": 0.6}, quality.REASON_AEROSOL),
    ({"model": "ACOLITE-LUT-202110-MOD3"}, quality.REASON_AEROSOL),
    ({"swir": np.full(SHAPE, 0.05, "float32")}, quality.REASON_RESIDUAL_SWIR),
])
def test_each_observation_gate_fails_on_its_condition(kwargs, reason) -> None:
    report = assess(_inputs(**kwargs))
    assert report.verdict is UsabilityVerdict.UNUSABLE
    assert report.reasons == (reason,)
    expected = (
        ObservationStatus.INCOMPLETE_COVERAGE if reason == quality.REASON_INCOMPLETE_COVERAGE
        else ObservationStatus.NO_USABLE_OBSERVATION
    )
    assert report.status is expected


def test_negative_reflectance_range_and_valid_fraction_gates() -> None:
    flags = np.zeros(SHAPE, dtype="int32")
    flags[:15, :] |= 8
    report = assess(_inputs(flags=flags))
    assert report.negative_rhos_fraction == pytest.approx(0.15)
    assert quality.REASON_NEGATIVE_REFLECTANCE in report.reasons

    values = np.full(SHAPE, 2.0, "float32")
    values[:10, :] = 500.0
    everywhere = np.ones(SHAPE, dtype=bool)
    report = assess(_inputs(products={"tur_nechad2016": ProductLayer(values, everywhere, True)}))
    assert report.reasons == (quality.REASON_OUT_OF_RANGE,)
    assert report.range_violations[0].offending_fraction == pytest.approx(0.10)

    cloudy = np.zeros(SHAPE, dtype="int32")
    cloudy[:85, :] |= 2
    report = assess(_inputs(flags=cloudy))
    assert report.reasons == (quality.REASON_BELOW_VALID_FRACTION,)


def test_non_gating_product_reports_but_does_not_decide() -> None:
    everywhere = np.ones(SHAPE, dtype=bool)
    chl = np.full(SHAPE, np.nan, "float32")
    chl[:5, :] = 5.0
    report = assess(_inputs(
        products={
            "tur_nechad2016": ProductLayer(np.full(SHAPE, 2.0, "float32"), everywhere, True),
            "chl_re_gons740": ProductLayer(chl, everywhere, False),
        },
        policy=_policy(range_rules=(RangeRule(product_key="chl_re_gons740", min=0, max=1, max_offending_fraction=0.0),)),
    ))
    by_key = {item.product_key: item for item in report.products}
    assert by_key["chl_re_gons740"].valid_fraction == pytest.approx(0.05)
    assert report.range_violations and report.verdict is UsabilityVerdict.USABLE


def _fixture_flags(variant: str) -> np.ndarray:
    name = next((FIXTURES / variant).glob("*_L2W.nc"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with rasterio.open(f'NETCDF:"{name}":l2_flags') as dataset:
            return dataset.read(1).astype("int32")


def test_real_cloudy_flags_are_unusable_and_success_flags_are_usable() -> None:
    cloudy = _fixture_flags("cloudy")
    shape = cloudy.shape
    everywhere = np.ones(shape, dtype=bool)

    def run(flags: np.ndarray):
        return assess(_inputs(flags=flags, shape=shape, products={
            "tur_nechad2016": ProductLayer(np.full(shape, 2.0, "float32"), everywhere, True),
        }))

    cloudy_report = run(cloudy)
    assert cloudy_report.verdict is UsabilityVerdict.UNUSABLE
    assert quality.REASON_BELOW_VALID_FRACTION in cloudy_report.reasons
    assert run(_fixture_flags("success")).verdict is UsabilityVerdict.USABLE


def test_quality_config_records_a_basis_for_every_threshold() -> None:
    policy = _policy()
    for field_name in ("min_valid_fraction", "min_grid_coverage", "cloud_dilation_px", "aot550_max",
                       "max_negative_rhos_fraction", "max_residual_swir_rhow", "coastal_buffer_m", "range_rules"):
        assert policy.basis.get(field_name), field_name
    assert (policy.max_negative_rhos_fraction, policy.max_residual_swir_rhow, policy.aot550_max) == (0.10, 0.02, 0.5)
    assert Path(ROOT / "configs/quality.yaml").is_file()
