"""End-to-end tests for the Phase 2.1 command surface."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from shapely.geometry import box, mapping

from oceanos.catalog import LocalSceneCatalog, SceneMetadata
from oceanos.domain import AcquiredScene, ArtifactRef
from oceanos.ingestion import SceneManifest

ROOT = Path(__file__).resolve().parents[1]


def config_path(tmp_path: Path) -> Path:
    config = yaml.safe_load((ROOT / "configs/mvp.yaml").read_text(encoding="utf-8"))
    config["data_root"] = str(tmp_path / "data")
    config["catalog_dir"] = str(tmp_path / "catalog")
    config["aoi"]["path"] = str(ROOT / "configs/aoi/la_parguera_mvp.geojson")
    path = tmp_path / "mvp.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_module_and_console_help() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (str(ROOT / "src"), environment.get("PYTHONPATH"))))
    module = subprocess.run([sys.executable, "-m", "oceanos", "--help"], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
    script = subprocess.run(["uv", "run", "oceanospr", "--help"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert module.returncode == script.returncode == 0
    assert "NASA OCEANOS Puerto Rico" in module.stdout


def test_aoi_json_and_grid_build(tmp_path: Path, capsys) -> None:
    from oceanos.__main__ import main

    config = config_path(tmp_path)
    assert main(["aoi", "info", "--json", "--config", str(config)]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["aoi_id"].startswith("aoi-la-parguera-")
    assert document["crs"] == "EPSG:32619"
    assert main(["grid", "build", "--config", str(config)]) == 0
    output = capsys.readouterr().out
    assert "grid-" in output
    grid_files = list((tmp_path / "data/products").rglob("grid.json"))
    assert len(grid_files) == 1


def discovered_scene() -> SceneMetadata:
    return SceneMetadata(
        scene_id="S2A_MSIL1C_20260702T150741_N0512_R082_T19QGV_X", collection="sentinel-2-l1c",
        platform="S2A", datetime="2026-07-02T15:07:41Z", geometry=mapping(box(-68, 17, -66, 19)),
        bbox=(-68, 17, -66, 19), cloud_cover=2, source_catalog="https://catalogue.example",
        processing_level="Level-1C", processing_baseline="05.12", relative_orbit=82,
        datatake_id="GS2A_20260702T150741_057594_N05.12", overpass_id="S2A_20260702T150741_R082",
        mgrs_tile="19QGV", source_id="uuid", online=True,
    )


def test_search_registers_l1c_and_overpasses_count(monkeypatch, tmp_path: Path, capsys) -> None:
    from oceanos.__main__ import main

    config = config_path(tmp_path)
    fake = SimpleNamespace(search=lambda *args, **kwargs: [discovered_scene()])
    monkeypatch.setattr("oceanos.__main__.CdseODataProvider", lambda *args, **kwargs: fake)
    output = tmp_path / "scenes.json"
    assert main(["scenes", "search", "--start", "2026-07-02", "--end", "2026-07-02", "--output", str(output), "--config", str(config)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "1.1"
    assert LocalSceneCatalog(tmp_path / "catalog").get_scene(discovered_scene().scene_id) is not None
    capsys.readouterr()
    assert main(["scenes", "overpasses", "--start", "2026-07-01", "--end", "2026-07-03", "--count", "--config", str(config)]) == 0
    assert capsys.readouterr().out.strip() == "1"


def test_acquire_uses_only_selected_scene_id_and_builds_input_set(monkeypatch, tmp_path: Path, capsys) -> None:
    from oceanos.__main__ import main

    config = config_path(tmp_path)
    catalog = LocalSceneCatalog(tmp_path / "catalog")
    base = discovered_scene()
    winner = base.model_copy(update={
        "scene_id": base.scene_id.removesuffix("_X") + "_A", "source_id": "uuid-a", "cloud_cover": 1,
    })
    same_tile_loser = base.model_copy(update={
        "scene_id": base.scene_id.removesuffix("_X") + "_B", "source_id": "uuid-b", "cloud_cover": 20,
    })
    partial_geometry = mapping(box(-68, 17, -67.5, 19))
    other_tile = SceneMetadata.model_validate({**base.model_dump(mode="json"),
        "scene_id": base.scene_id.replace("T19QGV_X", "T19QFV_X"), "source_id": "uuid-fv",
        "mgrs_tile": "19QFV", "geometry": partial_geometry, "bbox": (-68, 17, -67.5, 19), "cloud_cover": 0,
    })
    for candidate in (same_tile_loser, other_tile, winner):
        catalog.add_scene(candidate)
    assert main(["grid", "build", "--config", str(config)]) == 0
    capsys.readouterr()
    acquired = []

    def fake_acquire(source: SceneMetadata, *args, **kwargs) -> SceneManifest:
        acquired.append(source.scene_id)
        digest = sha256(source.scene_id.encode()).hexdigest()
        return SceneManifest(
            scene_id=source.scene_id,
            source_id=source.source_id or "source",
            acquired=AcquiredScene(
                scene_id=source.scene_id,
                source_id=source.source_id or "source",
                archive=ArtifactRef(
                    role="source", relpath=f"sentinel2-l1c/{digest}/{source.scene_id}.zip",
                    sha256=digest, size=1, media_type="application/zip",
                ),
                provider_md5_verified=True, safe_members_verified=True, verified_at=datetime.now(UTC),
            ),
        )

    monkeypatch.setattr("oceanos.__main__.CdseTokenClient", lambda *args, **kwargs: lambda: "token")
    monkeypatch.setattr("oceanos.__main__.acquire_scene", fake_acquire)
    assert main(["scenes", "acquire", "--overpass", "S2A_20260702T150741_R082", "--config", str(config)]) == 0
    output = capsys.readouterr().out
    assert acquired == [winner.scene_id]
    assert "Input set: inp-" in output
    assert "scenes: 1" in output


def test_retired_l2a_commands_are_not_parseable() -> None:
    from oceanos.__main__ import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["scenes", "fetch", "scene"])
    with pytest.raises(SystemExit):
        parser.parse_args(["process", "normalize", "scene"])
