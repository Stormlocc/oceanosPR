"""Offline checks for the real, trimmed ACOLITE Phase 1 fixtures."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from shapely.geometry import shape
from shapely.ops import unary_union

FIXTURES = Path(__file__).parent / "fixtures" / "acolite"
EXPECTED_SUCCESS_PRODUCTS = {
    *(f"{family}_{wavelength}" for family in ("Rrs", "rhorc", "rhow") for wavelength in (443, 492, 560, 665, 704, 740, 783, 833, 865, 1614, 2202)),
    "SPM_Nechad2016_665",
    "TUR_Nechad2016_665",
    "chl_re_gons740",
    "fai",
    "fait",
    "ndvi",
}


def _one(variant: str, pattern: str) -> Path:
    matches = list((FIXTURES / variant).glob(pattern))
    assert len(matches) == 1
    return matches[0]


def _subdataset_names(path: Path) -> set[str]:
    # A NetCDF container has no raster transform; its individual subdatasets do.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(path) as dataset:
            return {subdataset.rsplit(":", 1)[-1] for subdataset in dataset.subdatasets}


def _settings(variant: str) -> dict[str, str]:
    path = _one(variant, "*_l2r_settings.txt")
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def _water_masks() -> tuple[np.ndarray, np.ndarray]:
    window = json.loads((FIXTURES / "window.json").read_text(encoding="utf-8"))
    clip = json.loads((FIXTURES / "gshhg_clip.geojson").read_text(encoding="utf-8"))
    bounds = window["projected_bounds"]
    transform = from_origin(bounds["west"], bounds["north"], 10, 10)
    land_geometry = unary_union(
        [
            shape(transform_geom("EPSG:4326", window["crs"], feature["geometry"]))
            for feature in clip["features"]
        ]
    )
    shape_2d = (window["height"], window["width"])
    land = geometry_mask([land_geometry.__geo_interface__], shape_2d, transform, invert=True)
    buffered_land = geometry_mask(
        [land_geometry.buffer(150).__geo_interface__],
        shape_2d,
        transform,
        invert=True,
    )
    return land, buffered_land


def _read_array(path: Path, variable: str) -> np.ndarray:
    with rasterio.open(f"netcdf:{path}:{variable}") as dataset:
        values = dataset.read(1, masked=True).astype("float64").filled(np.nan)
    values[np.abs(values) > 1e20] = np.nan
    return values


def _candidate_mask(variant: str, water: np.ndarray) -> np.ndarray:
    settings = _settings(variant)
    excluded = sum(
        1 << int(settings[name])
        for name in ("flag_exponent_cirrus", "flag_exponent_toa", "flag_exponent_negative")
    )
    flags = _read_array(_one(variant, "*_L2W.nc"), "l2_flags").astype("int64")
    return water & ((flags & excluded) == 0)


def test_fixture_layout_and_storage_budget() -> None:
    assert (FIXTURES / "window.json").is_file()
    assert (FIXTURES / "gshhg_clip.geojson").is_file()
    for variant in ("success", "ancillary_fallback", "missing_variable", "cloudy"):
        assert _one(variant, "*_L2R.nc").is_file()
        assert _one(variant, "*_L2W.nc").is_file()
        assert _one(variant, "*_log_file.txt").is_file()
        assert _one(variant, "*_l1r_settings_user.txt").is_file()
        assert _one(variant, "*_l2r_settings.txt").is_file()
    assert not list((FIXTURES / "skipped").glob("*.nc"))
    assert sum(path.stat().st_size for path in FIXTURES.rglob("*")) < 10_000_000


def test_fixture_window_satisfies_the_geometric_coastal_criterion() -> None:
    window = json.loads((FIXTURES / "window.json").read_text(encoding="utf-8"))
    land, buffered_land = _water_masks()
    counts = {
        "land_pixels": int(land.sum()),
        "coastal_buffer_150m_pixels": int((buffered_land & ~land).sum()),
        "water_outside_buffer_pixels": int((~buffered_land).sum()),
    }

    assert land.any()
    assert (buffered_land & ~land).any()
    assert int((~buffered_land).sum()) >= 20_000
    assert counts == window["geometric_counts"]


def test_acolite_derived_fixtures_use_the_amended_v8_settings() -> None:
    window = json.loads((FIXTURES / "window.json").read_text(encoding="utf-8"))
    assert window["source_run"] == "F"
    for variant in ("success", "ancillary_fallback", "missing_variable", "cloudy"):
        settings = _settings(variant)
        assert settings["l2w_mask_threshold"] == "0.05"
        assert settings["l2w_mask_water_parameters"] == "False"
        assert settings["dsf_residual_glint_correction"] == "True"
        assert settings["dsf_residual_glint_correction_method"] == "default"
        assert settings["dsf_residual_glint_wave_range"] == "1500,2400"


def test_success_fixture_has_enough_valid_water_for_every_product() -> None:
    _, buffered_land = _water_masks()
    water = ~buffered_land
    l2w = _one("success", "*_L2W.nc")
    candidate = _candidate_mask("success", water)
    products = _subdataset_names(l2w) - {"lon", "lat", "l2_flags"}
    assert EXPECTED_SUCCESS_PRODUCTS <= products
    fractions = {
        product: float(np.count_nonzero(candidate & np.isfinite(_read_array(l2w, product))) / water.sum())
        for product in EXPECTED_SUCCESS_PRODUCTS
    }

    assert fractions
    assert min(fractions.values()) >= 0.20, fractions


def test_cloudy_fixture_has_a_nonzero_low_valid_fraction() -> None:
    _, buffered_land = _water_masks()
    water = ~buffered_land
    candidate = _candidate_mask("cloudy", water)
    turbidity = _read_array(_one("cloudy", "*_L2W.nc"), "TUR_Nechad2016_665")
    fraction = float(np.count_nonzero(candidate & np.isfinite(turbidity)) / water.sum())

    assert 0 < fraction < 0.20


def test_success_fixture_preserves_the_real_grid_and_variable_inventory() -> None:
    l2w = _one("success", "*_L2W.nc")
    variables = _subdataset_names(l2w)
    assert {"l2_flags", "TUR_Nechad2016_665", "Rrs_665", "rhow_665", "rhorc_665"} <= variables

    with rasterio.open(f"netcdf:{l2w}:l2_flags") as flags:
        window = json.loads((FIXTURES / "window.json").read_text(encoding="utf-8"))
        bounds = window["projected_bounds"]
        assert flags.shape == (256, 256)
        assert flags.crs == rasterio.CRS.from_epsg(32619)
        assert flags.transform == rasterio.Affine(10, 0, bounds["west"], 0, -10, bounds["north"])


def test_failure_variants_encode_real_observed_conditions() -> None:
    missing_variables = _subdataset_names(_one("missing_variable", "*_L2W.nc"))
    assert not any(name.lower().startswith("tur_nechad2016") for name in missing_variables)

    fallback = _one("ancillary_fallback", "*_L2R.nc")
    with rasterio.open(f"netcdf:{fallback}:lon") as dataset:
        tags = dataset.tags()
    assert float(tags["NC_GLOBAL#uoz"]) == 0.3
    assert float(tags["NC_GLOBAL#uwv"]) == 1.5
    assert float(tags["NC_GLOBAL#pressure"]) == 1013.25
    assert float(tags["NC_GLOBAL#wind"]) == 2.0

    skipped_log = _one("skipped", "*_log_file.txt").read_text(encoding="utf-8")
    assert "Longitude limits outside" in skipped_log
