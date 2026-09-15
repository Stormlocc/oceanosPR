"""Offline contract tests for the Phase 1 operational scripts."""

import ast
import importlib.util
import shutil
import subprocess
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_fixture_script():
    path = SCRIPTS_DIR / "make_acolite_fixtures.py"
    spec = importlib.util.spec_from_file_location("make_acolite_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acolite_environment_dry_run_describes_the_pinned_installation(
    tmp_path: Path,
) -> None:
    """Dry-run is safe and identifies the exact ACOLITE release to prepare."""
    home = tmp_path / "home"
    home.mkdir()

    result = subprocess.run(
        ["bash", SCRIPTS_DIR / "acolite_env.sh", "--dry-run"],
        check=False,
        cwd=REPO_ROOT,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "20260421.0" in result.stdout
    assert "f73cbe73887c2b114d9d3c70865effee73871525" in result.stdout
    assert not (home / "acolite").exists()
    assert not (home / "acolite.main-d61c8de").exists()


def test_gshhg_check_reports_missing_owned_reference_data(tmp_path: Path) -> None:
    """A fresh checkout does not falsely pass GSHHG verification."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "fetch_gshhg.sh"
    shutil.copy2(SCRIPTS_DIR / "fetch_gshhg.sh", script)

    result = subprocess.run(
        ["bash", script, "--check"],
        check=False,
        cwd=tmp_path,
        env={"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "data/external/gshhg" in f"{result.stdout}\n{result.stderr}"


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
    module = _load_fixture_script()
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
    module = _load_fixture_script()
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
    module = _load_fixture_script()
    selected = frozenset({"x", "y", "l2_flags"})

    assert module._include_variable("l2_flags", selected, ())
    assert not module._include_variable("Rrs_665", selected, ())
    assert not module._include_variable("TUR_Nechad2016_665", None, ("tur_nechad2016",))
    assert module._include_variable("Rrs_665", None, ())
