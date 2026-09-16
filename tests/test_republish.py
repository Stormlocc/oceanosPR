"""DA-4: downstream changes re-enter at P5 from the archive, without ACOLITE or acquisition."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from support.pipeline_env import OVERPASS, make_env

from oceanos.pipeline.republish import republish
from oceanos.pipeline.run_one import run_one
from oceanos.publishing import current_release_id, release_ledger


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Republish tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_policy_bump_creates_new_release_without_acolite_or_acquisition(tmp_path: Path, monkeypatch) -> None:
    env = make_env(tmp_path, monkeypatch)
    first = run_one(env.settings, OVERPASS, **env.configs(), dependencies=env.dependencies())
    assert env.calls == {"acquire": 1, "acolite": 1}

    configs = env.configs()
    unchanged = republish(env.settings, OVERPASS, products=configs["products"], policy=configs["policy"],
                          publication=configs["publication"])
    assert (unchanged.status, unchanged.release_id) == ("unchanged", first.release_id)

    bumped = configs["policy"].model_copy(update={"version": "2"})
    result = republish(env.settings, OVERPASS, products=configs["products"], policy=bumped,
                       publication=configs["publication"])

    assert result.status == "published" and result.release_id != first.release_id
    assert env.calls == {"acquire": 1, "acolite": 1}, "republish must not acquire or run ACOLITE"
    assert current_release_id(env.layout, env.aoi_id, OVERPASS) == result.release_id
    assert (env.layout.superseded / env.aoi_id / "releases" / OVERPASS / first.release_id).is_dir()
    events = [(event.event, event.release_id) for event in release_ledger(env.layout).events()]
    assert events[-2:] == [("release_published", result.release_id), ("release_superseded", first.release_id)]


def test_cli_republish_by_observation_and_range(tmp_path: Path, monkeypatch, capsys) -> None:
    from oceanos.__main__ import main

    env = make_env(tmp_path, monkeypatch)
    first = run_one(env.settings, OVERPASS, **env.configs(), dependencies=env.dependencies())
    capsys.readouterr()

    assert main(["pipeline", "republish", "--observation", OVERPASS, "--config", str(env.config)]) == 0
    assert f"{OVERPASS}: unchanged; {first.release_id}" in capsys.readouterr().out

    quality = env.config.parent / "quality.yaml"
    quality.write_text(quality.read_text(encoding="utf-8").replace('version: "1"', 'version: "1.1"', 1), encoding="utf-8")
    assert main(["pipeline", "republish", "--range", "2026-07-01", "2026-07-03", "--config", str(env.config)]) == 0
    output = capsys.readouterr().out
    assert f"{OVERPASS}: published;" in output and first.release_id not in output
    assert env.calls["acolite"] == 1
