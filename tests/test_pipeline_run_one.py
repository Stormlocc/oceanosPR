"""`pipeline run-one` chains A1 → A2 → P1–P8 for one observation, offline."""

from __future__ import annotations

import json
import socket
import warnings
from pathlib import Path

import numpy as np
import pytest
import rasterio
from support.pipeline_env import FIXTURES, OVERPASS, make_env

from oceanos.domain import FailureCode, RunState
from oceanos.pipeline.archive import AttemptsLedger
from oceanos.pipeline.run_one import PipelineError, latest_release_dir, run_one
from oceanos.processing.masks import rasterize_land
from oceanos.publishing import release_ledger


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("run-one tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _releases(root: Path) -> list[Path]:
    return sorted(path for path in root.glob("*/releases/*/*") if path.is_dir() and not path.name.startswith("."))


def test_run_one_publishes_masked_water_product_and_unmasked_flags(tmp_path: Path, monkeypatch) -> None:
    env = make_env(tmp_path, monkeypatch)
    result = run_one(env.settings, OVERPASS, parameters=env.parameters, products=env.products, dependencies=env.dependencies())

    assert result.status == "published"
    assert _releases(env.layout.products) == [result.release_dir]
    land = rasterize_land(FIXTURES / "gshhg_clip.geojson", env.grid)
    with rasterio.open(result.release_dir / "tur_nechad2016.tif") as dataset:
        turbidity = dataset.read(1)
    with rasterio.open(result.release_dir / "l2_flags.tif") as dataset:
        flags = dataset.read(1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with rasterio.open(f'NETCDF:"{FIXTURES}/success/S2A_MSI_2026_07_02_15_08_19_T19QGV_L2W.nc":l2_flags') as source:
            source_flags = source.read(1)
    assert np.isnan(turbidity[land]).all() and np.isfinite(turbidity[~land]).any()
    np.testing.assert_array_equal(flags, source_flags)

    attempts = AttemptsLedger(env.layout.state / "ledger/attempts.jsonl").latest()
    attempt = attempts[result.attempt_id]
    assert attempt.state is RunState.PUBLISHED
    assert [stage.stage.value for stage in attempt.stages] == [
        "plan", "preflight", "execute", "verify", "archive", "conform", "assess", "package", "publish",
    ]
    manifests = list(env.layout.archive.rglob("run-manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text(encoding="utf-8"))["run_key"] == result.run_key
    assert latest_release_dir(env.settings, OVERPASS) == result.release_dir


def test_same_run_key_is_skipped_and_force_reprocess_supersedes_previous(tmp_path: Path, monkeypatch) -> None:
    env = make_env(tmp_path, monkeypatch)
    dependencies = env.dependencies()
    first = run_one(env.settings, OVERPASS, parameters=env.parameters, products=env.products, dependencies=dependencies)

    skipped = run_one(env.settings, OVERPASS, parameters=env.parameters, products=env.products, dependencies=dependencies)
    assert (skipped.status, skipped.release_id, skipped.run_key) == ("skipped", first.release_id, first.run_key)

    second = run_one(env.settings, OVERPASS, parameters=env.parameters, products=env.products,
                     force_reprocess=True, dependencies=dependencies)
    assert second.run_key == first.run_key and second.release_id != first.release_id
    assert [path.name for path in _releases(env.layout.products)] == [second.release_id]
    assert [path.name for path in _releases(env.layout.superseded)] == [first.release_id]
    events = [(event.event, event.release_id) for event in release_ledger(env.layout).events()]
    assert events == [
        ("release_published", first.release_id),
        ("release_published", second.release_id),
        ("release_superseded", first.release_id),
    ]
    release = json.loads((second.release_dir / "release.json").read_text(encoding="utf-8"))
    assert release["supersedes"] == first.release_id


def test_skipped_acolite_run_publishes_nothing_and_records_failure(tmp_path: Path, monkeypatch) -> None:
    env = make_env(tmp_path, monkeypatch)
    env.variant = "skipped"

    with pytest.raises(PipelineError) as error:
        run_one(env.settings, OVERPASS, parameters=env.parameters, products=env.products, dependencies=env.dependencies())

    assert error.value.failure.code is FailureCode.ACOLITE_SKIPPED
    assert _releases(env.layout.products) == []
    assert not list(env.layout.archive.rglob("run-manifest.json"))
    (attempt,) = AttemptsLedger(env.layout.state / "ledger/attempts.jsonl").latest().values()
    assert attempt.state is RunState.FAILED and attempt.failure is not None
    assert attempt.failure.code is FailureCode.ACOLITE_SKIPPED


def test_run_one_requires_prior_grid_and_scene_search(tmp_path: Path, monkeypatch) -> None:
    env = make_env(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="scenes search"):
        run_one(env.settings, "S2B_20260705T150801_R082", parameters=env.parameters, products=env.products,
                dependencies=env.dependencies())

    env.layout.grid_json(env.aoi_id).unlink()
    with pytest.raises(ValueError, match="grid build"):
        run_one(env.settings, OVERPASS, parameters=env.parameters, products=env.products, dependencies=env.dependencies())


def test_cli_latest_release_prints_current_release(tmp_path: Path, monkeypatch, capsys) -> None:
    from oceanos.__main__ import main

    env = make_env(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        main(["pipeline", "latest-release", "--overpass", OVERPASS, "--config", str(env.config)])
    capsys.readouterr()
    result = run_one(env.settings, OVERPASS, parameters=env.parameters, products=env.products, dependencies=env.dependencies())
    assert main(["pipeline", "latest-release", "--overpass", OVERPASS, "--config", str(env.config)]) == 0
    assert capsys.readouterr().out.strip() == str(result.release_dir)
