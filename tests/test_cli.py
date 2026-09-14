"""End-to-end tests for the minimal module CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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


def test_console_script_help_returns_successfully() -> None:
    result = subprocess.run(
        ["uv", "run", "oceanospr", "--help"],
        cwd=PROJECT_ROOT,
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


def _scene_config(tmp_path):
    import yaml

    config = yaml.safe_load((PROJECT_ROOT / "configs/mvp.yaml").read_text())
    config["aoi"]["path"] = str(PROJECT_ROOT / "tests/fixtures/aoi.geojson")
    config["scenes"]["catalog_url"] = "https://catalog.example"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def test_scenes_cli_table_and_normalized_output(monkeypatch, tmp_path, capsys):
    import json

    import httpx

    from oceanos.__main__ import main
    from oceanos.catalog import SceneSearchResult, Sentinel2Provider

    item = json.loads((PROJECT_ROOT / "tests/fixtures/stac_item.json").read_text())
    calls = []
    def handler(request):
        calls.append(request)
        assert json.loads(request.content)["query"] == {"eo:cloud_cover": {"lte": 0}}
        assert json.loads(request.content)["collections"] == ["custom-sentinel"]
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [item], "links": []})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr("oceanos.__main__.Sentinel2Provider", lambda *a, **kw: Sentinel2Provider(*a, client=client, **kw))
        output = tmp_path / "scenes.json"
        assert main(["scenes", "search", "--start", "2024-01-01", "--end", "2024-01-02",
                     "--config", str(_scene_config(tmp_path)), "--output", str(output),
                     "--cloud-cover-max", "0", "--collection", "custom-sentinel"]) == 0
    result = SceneSearchResult.model_validate_json(output.read_text())
    assert result.scenes[0].scene_id == item["id"]
    assert "properties" not in output.read_text()
    table = capsys.readouterr().out
    for text in ["SCENE ID", "CLOUD %", item["id"], "1 scene(s) found."]:
        assert text in table
    assert len(calls) == 1


def test_scenes_cli_empty_json(monkeypatch, tmp_path, capsys):
    import json

    import httpx

    from oceanos.__main__ import main
    from oceanos.catalog import Sentinel2Provider

    def handler(request):
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr("oceanos.__main__.Sentinel2Provider", lambda *a, **kw: Sentinel2Provider(*a, client=client, **kw))
        output = tmp_path / "scenes.json"
        assert main(["scenes", "search", "--start", "2024-01-01", "--end", "2024-01-01",
                     "--config", str(_scene_config(tmp_path)), "--output", str(output)]) == 0
    assert json.loads(output.read_text()) == {"schema_version": "1.0", "scenes": []}
    assert "0 scenes found." in capsys.readouterr().out


def test_scenes_cli_remote_failure_preserves_previous_output(monkeypatch, tmp_path, capsys):
    import httpx
    import pytest

    from oceanos.__main__ import main
    from oceanos.catalog import Sentinel2Provider

    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(400))) as client:
        monkeypatch.setattr("oceanos.__main__.Sentinel2Provider", lambda *a, **kw: Sentinel2Provider(*a, client=client, **kw))
        output = tmp_path / "scenes.json"
        output.write_text("existing metadata")
        with pytest.raises(SystemExit) as exc:
            main(["scenes", "search", "--start", "2024-01-01", "--end", "2024-01-01",
                  "--config", str(_scene_config(tmp_path)), "--output", str(output)])
    assert exc.value.code == 1
    assert output.read_text() == "existing metadata"
    assert "HTTP 400" in capsys.readouterr().err
