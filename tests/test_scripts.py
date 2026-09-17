"""Offline contract tests for the operational scripts under ``scripts/``."""

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_script(name: str) -> ModuleType:
    """Import a script by path; ``main`` is not executed."""
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


# --- scripts/acolite_env.py -------------------------------------------------


def test_acolite_environment_dry_run_describes_the_pin_without_touching_anything(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry-run reports the pinned release and runs no external command."""
    module = _load_script("acolite_env")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("--dry-run must not run a subprocess")

    monkeypatch.setattr(module.subprocess, "run", forbidden)

    assert module.main(["--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "20260421.0" in output
    assert "f73cbe73887c2b114d9d3c70865effee73871525" in output


def test_acolite_environment_reads_the_pin_from_the_configuration() -> None:
    """The pin has one source; the script must not re-declare it."""
    source = (SCRIPTS_DIR / "acolite_env.py").read_text(encoding="utf-8")

    assert "f73cbe73887c2b114d9d3c70865effee73871525" not in source
    assert "20260421.0" not in source


def test_acolite_checkout_status_accepts_only_the_pinned_configuration_edit() -> None:
    """A dirty checkout cannot masquerade as the pin (DA #17)."""
    module = _load_script("acolite_env")

    module.assert_only_config_modified(" M config/config.txt")

    with pytest.raises(module.CheckError):
        module.assert_only_config_modified(" M acolite/acolite_l2r.py")
    with pytest.raises(module.CheckError):
        module.assert_only_config_modified("")


def test_acolite_netrc_requires_mode_600_and_both_machines(tmp_path: Path) -> None:
    """Credentials stay in ~/.netrc, readable only by their owner."""
    module = _load_script("acolite_env")
    netrc_path = tmp_path / ".netrc"
    netrc_path.write_text(
        "machine earthdata login u password p\nmachine cdse login u password p\n",
        encoding="utf-8",
    )

    netrc_path.chmod(0o644)
    with pytest.raises(module.CheckError, match="600"):
        module.check_netrc(netrc_path)

    netrc_path.chmod(0o600)
    module.check_netrc(netrc_path)

    netrc_path.write_text("machine earthdata login u password p\n", encoding="utf-8")
    netrc_path.chmod(0o600)
    with pytest.raises(module.CheckError, match="cdse"):
        module.check_netrc(netrc_path)


def test_acolite_environment_dependencies_come_from_the_pinned_environment_file(
    tmp_path: Path,
) -> None:
    """Every dependency ACOLITE declares is checked, with its version pin dropped."""
    module = _load_script("acolite_env")
    environment_yml = tmp_path / "environment.yml"
    environment_yml.write_text(
        "name: acolite\nchannels:\n  - conda-forge\ndependencies:\n"
        "  - python=3.11\n  - numpy>=2\n  - netcdf4\n  - pip:\n    - something\n",
        encoding="utf-8",
    )

    assert module.environment_dependencies(environment_yml) == ["python", "numpy", "netcdf4"]


def test_acolite_environment_maps_every_declared_dependency_to_an_import() -> None:
    """A new dependency at the pin must fail loudly, not be skipped silently."""
    module = _load_script("acolite_env")

    with pytest.raises(module.CheckError, match="unmapped"):
        module.import_specs(["numpy", "brand-new-package"])


def test_acolite_disk_probe_measures_an_existing_directory_without_creating_it(
    tmp_path: Path,
) -> None:
    """--check is read-only; it never creates the storage tiers."""
    module = _load_script("acolite_env")
    missing = tmp_path / "work" / "deeper"

    assert module.existing_ancestor(missing) == tmp_path
    assert not missing.exists()


# --- scripts/fetch_reference_data.py ---------------------------------------


def test_reference_datasets_pin_every_file(tmp_path: Path) -> None:
    """Checksums are pinned in the script and never computed at run time (B12)."""
    module = _load_script("fetch_reference_data")

    pinned = [file for dataset in module.DATASETS.values() for file in dataset.files]
    assert pinned, "no reference file is pinned"
    for file in pinned:
        assert len(file.sha256) == 64 and set(file.sha256) <= set("0123456789abcdef")
        assert file.size > 0
        assert file.url.startswith("https://")
    assert len({file.name for file in pinned}) == len(pinned)


def test_reference_check_reports_missing_owned_data(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A fresh checkout does not falsely pass verification."""
    module = _load_script("fetch_reference_data")
    monkeypatch.setenv("OCEANOS_ACOLITE__EXTERNAL_DIR", str(tmp_path))

    assert module.main(["bathymetry", "--check"]) == 1

    assert "ncei19_" in capsys.readouterr().err


def test_reference_verify_rejects_wrong_size_and_wrong_digest(tmp_path: Path) -> None:
    """Size and SHA-256 are both checked before a file is accepted."""
    module = _load_script("fetch_reference_data")
    path = tmp_path / "sample.bin"
    path.write_bytes(b"oceanos")
    digest = "9d4a0b5e1cdd2a4a8a9cfc7ca41b06a2e9ab5b98a2a31a4d1a6e3a8b0e7f0c11"

    with pytest.raises(module.CheckError, match="bytes"):
        module.verify(path, module.PinnedFile(url="https://x/y", name="sample.bin", size=6, sha256=digest))
    with pytest.raises(module.CheckError, match="SHA-256"):
        module.verify(path, module.PinnedFile(url="https://x/y", name="sample.bin", size=7, sha256=digest))


# --- scripts/probe_run_one.py ----------------------------------------------


def test_probe_derives_the_overpass_window_from_the_recorded_scene() -> None:
    """The probe reads the scene recorded in Phase 1, never a hard-coded id."""
    module = _load_script("probe_run_one")
    scene = {
        "Name": "S2A_MSIL1C_20260702T150741_N0511_R082_T19QGV_20260702T184521.SAFE",
        "ContentDate": {"Start": "2026-07-02T15:07:41.024Z"},
    }

    assert module.overpass_window(scene) == ("2026-07-02", "2026-07-03", "S2A_20260702T150741_R082")


def test_probe_rejects_a_scene_it_cannot_identify() -> None:
    """A product name that is not an L1C SAFE stops the probe."""
    module = _load_script("probe_run_one")

    with pytest.raises(ValueError, match="overpass"):
        module.overpass_window({"Name": "not-a-safe", "ContentDate": {"Start": "2026-07-02T15:07:41Z"}})


# --- scripts/make_acolite_fixtures.py (unchanged dev tool) -------------------


def test_fixture_generator_has_no_acolite_dependency() -> None:
    """The committed trimmer uses the ACOLITE environment, not its Python API."""
    path = SCRIPTS_DIR / "make_acolite_fixtures.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert "acolite" not in imports
    assert not any(name.startswith("acolite.") for name in imports)


def test_fixture_generator_rewrites_cropped_spatial_metadata() -> None:
    """Coordinates, extents, dimensions and the geographic limit stay coherent."""
    module = _load_script("make_acolite_fixtures")
    attrs = {
        "global_dims": np.array([1126, 1605]),
        "data_dimensions": np.array([1126, 1605]),
        "data_elements": 1_807_230,
        "sub": np.array([119, 865, 1605, 1126]),
        "xrange": np.array([701150.0, 717200.0]),
        "yrange": np.array([1991390.0, 1980130.0]),
        "limit": np.array([17.8999, -67.1001, 18.0001, -66.9499]),
        "sensor": "S2A_MSI",
    }
    x = np.arange(713555.0, 716115.0, 10.0)
    y = np.arange(1986215.0, 1983655.0, -10.0)
    lon = np.array([[-66.9838, -66.9595], [-66.9839, -66.9596]])
    lat = np.array([[17.9536, 17.9535], [17.9304, 17.9303]])

    updated = module._updated_spatial_attributes(
        attrs,
        x=x,
        y=y,
        lon=lon,
        lat=lat,
        row=517,
        column=1240,
    )

    np.testing.assert_array_equal(updated["global_dims"], [256, 256])
    np.testing.assert_array_equal(updated["data_dimensions"], [256, 256])
    assert updated["data_elements"] == 65_536
    np.testing.assert_array_equal(updated["sub"], [1359, 1382, 256, 256])
    np.testing.assert_array_equal(updated["xrange"], [713550.0, 716110.0])
    np.testing.assert_array_equal(updated["yrange"], [1986220.0, 1983660.0])
    np.testing.assert_allclose(updated["limit"], [17.9303, -66.9839, 17.9536, -66.9595])
    assert updated["sensor"] == "S2A_MSI"


def test_fixture_generator_finds_tools_next_to_its_python(tmp_path: Path) -> None:
    """An absolute ACOLITE Python path still resolves its bundled GDAL tools."""
    module = _load_script("make_acolite_fixtures")
    environment_bin = tmp_path / "env" / "bin"
    environment_bin.mkdir(parents=True)
    python = environment_bin / "python"
    ogr2ogr = environment_bin / "ogr2ogr"
    python.touch()
    ogr2ogr.touch()
    ogr2ogr.chmod(0o755)

    resolved = module._environment_executable("ogr2ogr", python_executable=python)

    assert resolved == ogr2ogr


def test_fixture_generator_can_limit_variant_variables() -> None:
    """Failure variants retain only the real variables needed to exercise them."""
    module = _load_script("make_acolite_fixtures")
    selected = frozenset({"x", "y", "l2_flags"})

    assert module._include_variable("l2_flags", selected, ())
    assert not module._include_variable("Rrs_665", selected, ())
    assert not module._include_variable("TUR_Nechad2016_665", None, ("tur_nechad2016",))
    assert module._include_variable("Rrs_665", None, ())
