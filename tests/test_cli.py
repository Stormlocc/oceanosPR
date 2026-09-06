"""End-to-end tests for the minimal module CLI."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_module_help_returns_successfully() -> None:
    environment = os.environ.copy()
    source_path = str(PROJECT_ROOT / "src")
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_path
        if not existing_pythonpath
        else os.pathsep.join((source_path, existing_pythonpath))
    )

    result = subprocess.run(
        [sys.executable, "-m", "oceanos", "--help"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
    assert "NASA OCEANOS Puerto Rico" in result.stdout



def test_aoi_info_uses_replaceable_configuration(tmp_path, capsys):
    import yaml
    from oceanos.__main__ import main

    config = yaml.safe_load((PROJECT_ROOT / "configs/mvp.yaml").read_text())
    config["aoi"] = {
        "name": "CLI synthetic square",
        "path": str(PROJECT_ROOT / "tests/fixtures/aoi.geojson"),
        "target_crs": "EPSG:3857",
    }
    path = tmp_path / "custom.yaml"
    path.write_text(yaml.safe_dump(config))
    assert main(["aoi", "info", "--config", str(path)]) == 0
    output = capsys.readouterr().out
    for expected in ("CLI synthetic square", "EPSG:3857", "Bounds:", "Polygon", "Validation: valid"):
        assert expected in output


def test_aoi_info_reports_missing_file(tmp_path, capsys):
    import pytest
    import yaml
    from oceanos.__main__ import main

    config = yaml.safe_load((PROJECT_ROOT / "configs/mvp.yaml").read_text())
    config["aoi"]["path"] = str(tmp_path / "missing.geojson")
    path = tmp_path / "custom.yaml"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(SystemExit) as error:
        main(["aoi", "info", "--config", str(path)])
    assert error.value.code == 1
    assert "does not exist" in capsys.readouterr().err
