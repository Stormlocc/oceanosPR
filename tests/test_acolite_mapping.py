"""Sentinel-2 platform/band names map to the pinned ACOLITE wavelengths."""

from oceanos.acolite import acolite_variable, platform_wavelengths


def test_all_researched_platform_wavelength_tables_are_preserved() -> None:
    assert platform_wavelengths("S2A") == (443, 492, 560, 665, 704, 740, 783, 833, 865, 945, 1373, 1614, 2202)
    assert platform_wavelengths("S2B") == (442, 492, 559, 665, 704, 739, 780, 833, 864, 943, 1377, 1610, 2186)
    assert platform_wavelengths("S2C") == (444, 489, 561, 667, 707, 741, 785, 835, 866, 947, 1372, 1612, 2191)


def test_band_mapping_keeps_acolite_vocabulary_inside_adapter() -> None:
    assert acolite_variable("S2A", "B04", "rhow") == "rhow_665"
    assert acolite_variable("S2B", "B8A", "Rrs") == "Rrs_864"
    assert acolite_variable("S2C", "B12", "rhorc") == "rhorc_2191"

