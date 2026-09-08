"""Tests for typed configuration loading and path semantics."""

from pathlib import Path

import pytest

from oceanos.config import ConfigurationError, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_mvp_configuration_loads() -> None:
    settings = load_config(PROJECT_ROOT / "configs" / "mvp.yaml")

    assert settings.project_name == "NASA OCEANOS Puerto Rico"
    assert settings.default_crs == "EPSG:4326"


def test_relative_paths_resolve_from_project_and_data_root() -> None:
    settings = load_config(PROJECT_ROOT / "configs" / "mvp.yaml")
    expected_data_root = (PROJECT_ROOT / "data").resolve()

    assert settings.data_root == expected_data_root
    assert settings.raw_dir == expected_data_root / "raw"
    assert settings.intermediate_dir == expected_data_root / "intermediate"
    assert settings.products_dir == expected_data_root / "products"
    assert settings.catalog_dir == PROJECT_ROOT / "catalog"


def test_environment_overrides_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    overridden_root = tmp_path / "external-data"
    monkeypatch.setenv("OCEANOS_DATA_ROOT", str(overridden_root))
    monkeypatch.setenv("OCEANOS_DEFAULT_CRS", "EPSG:6566")

    settings = load_config(PROJECT_ROOT / "configs" / "mvp.yaml")

    assert settings.data_root == overridden_root.resolve()
    assert settings.raw_dir == overridden_root.resolve() / "raw"
    assert settings.default_crs == "EPSG:6566"


def test_missing_configuration_has_explicit_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_config(tmp_path / "missing.yaml")



def test_aoi_configuration_path_and_nested_override(monkeypatch, tmp_path):
    monkeypatch.setenv("OCEANOS_AOI__TARGET_CRS", "EPSG:3857")
    settings = load_config(PROJECT_ROOT / "configs/mvp.yaml", base_dir=tmp_path)
    assert settings.aoi.path == tmp_path / "configs/aoi/la_parguera_mvp.geojson"
    assert settings.aoi.target_crs == "EPSG:3857"


@pytest.mark.parametrize("field,value", [("name", " "), ("path", ""), ("target_crs", "invalid")])
def test_invalid_aoi_configuration(monkeypatch, field, value):
    monkeypatch.setenv(f"OCEANOS_AOI__{field.upper()}", value)
    with pytest.raises(ConfigurationError):
        load_config(PROJECT_ROOT / "configs/mvp.yaml")


def test_scene_configuration_and_environment(monkeypatch):
    monkeypatch.setenv("OCEANOS_SCENES__PAGE_SIZE", "10")
    monkeypatch.setenv("OCEANOS_SCENES__CATALOG_URL", "https://catalog.example/v1")
    settings = load_config(PROJECT_ROOT / "configs/mvp.yaml")
    assert settings.scenes.page_size == 10
    assert settings.scenes.catalog_url == "https://catalog.example/v1"
    assert settings.scenes.collection == "sentinel-2-l2a"


@pytest.mark.parametrize("field,value", [
    ("TIMEOUT", "0"), ("MAX_RETRIES", "-1"), ("PAGE_SIZE", "0"),
    ("CLOUD_COVER_MAX", "101"), ("CATALOG_URL", "file:///tmp/catalog"), ("COLLECTION", " "),
])
def test_invalid_scene_configuration(monkeypatch, field, value):
    monkeypatch.setenv(f"OCEANOS_SCENES__{field}", value)
    with pytest.raises(ConfigurationError):
        load_config(PROJECT_ROOT / "configs/mvp.yaml")


def test_normalization_environment_override(monkeypatch):
    monkeypatch.setenv("OCEANOS_NORMALIZATION__TARGET_RESOLUTION", "20")
    settings = load_config(PROJECT_ROOT / "configs/mvp.yaml")
    assert settings.normalization.target_resolution == 20
    assert settings.normalization.continuous_resampling == "bilinear"


@pytest.mark.parametrize("field,value", [
    ("TARGET_RESOLUTION", "0"), ("TARGET_RESOLUTION", "nan"), ("BUFFER_M", "-1"),
    ("CONTINUOUS_RESAMPLING", "cubic"), ("REFERENCE_BAND", "B11"), ("WARP_MEMORY_LIMIT_MB", "0"),
])
def test_invalid_normalization_configuration(monkeypatch, field, value):
    monkeypatch.setenv(f"OCEANOS_NORMALIZATION__{field}", value)
    with pytest.raises(ConfigurationError):
        load_config(PROJECT_ROOT / "configs/mvp.yaml")
