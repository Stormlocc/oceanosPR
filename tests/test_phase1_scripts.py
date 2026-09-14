"""Offline contract tests for the Phase 1 operational scripts."""

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


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
