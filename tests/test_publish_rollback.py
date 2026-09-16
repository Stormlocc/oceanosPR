"""Crash injection after each release-commit step keeps I3; reconciliation restores it."""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest
from support.pipeline_env import OVERPASS, make_env

from oceanos.pipeline.run_one import run_one
from oceanos.publishing import (
    ReconcileError,
    current_release_id,
    reconcile,
    release_ledger,
)


class Crash(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Rollback tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _served(env) -> list[str]:
    directory = env.layout.products / env.aoi_id / "releases" / OVERPASS
    return sorted(path.name for path in directory.iterdir() if path.is_dir() and not path.name.startswith("."))


def _superseded(env) -> list[str]:
    directory = env.layout.superseded / env.aoi_id / "releases" / OVERPASS
    return sorted(path.name for path in directory.iterdir()) if directory.exists() else []


@pytest.mark.parametrize(("step", "item_switched"), [("release_dir", False), ("stac_item", True), ("index", True)])
def test_crash_after_commit_step_keeps_previous_release_until_reconciled(tmp_path: Path, monkeypatch, step, item_switched) -> None:
    env = make_env(tmp_path, monkeypatch)
    dependencies = env.dependencies()
    first = run_one(env.settings, OVERPASS, **env.configs(), dependencies=dependencies)

    def crash(name: str) -> None:
        if name == step:
            raise Crash(name)

    with pytest.raises(Crash):
        run_one(env.settings, OVERPASS, **env.configs(),
                force_reprocess=True, dependencies=dependencies, fault=crash)

    served = _served(env)
    assert first.release_id in served, "the previous release must stay served until step 4"
    assert len(served) == 2
    new_release = next(name for name in served if name != first.release_id)
    current = current_release_id(env.layout, env.aoi_id, OVERPASS)
    assert current == (new_release if item_switched else first.release_id)

    preview = reconcile(env.layout, env.aoi_id, repair=False)
    assert _served(env) == served, "read-only reconciliation changes nothing"
    assert not preview.clean

    reconcile(env.layout, env.aoi_id, repair=True)
    assert _served(env) == [current]
    if item_switched:
        assert _superseded(env) == [first.release_id]
    else:
        assert _superseded(env) == []
    assert reconcile(env.layout, env.aoi_id, repair=True).clean
    events = [(event.event, event.release_id) for event in release_ledger(env.layout).events()]
    assert events.count(("release_published", current)) == 1
    if not item_switched:
        assert events[-1] == ("orphan_removed", new_release)


def test_next_run_after_crash_reconciles_and_publishes_exactly_one_release(tmp_path: Path, monkeypatch) -> None:
    env = make_env(tmp_path, monkeypatch)
    dependencies = env.dependencies()
    run_one(env.settings, OVERPASS, **env.configs(), dependencies=dependencies)

    def crash(name: str) -> None:
        if name == "release_dir":
            raise Crash(name)

    with pytest.raises(Crash):
        run_one(env.settings, OVERPASS, **env.configs(),
                force_reprocess=True, dependencies=dependencies, fault=crash)
    final = run_one(env.settings, OVERPASS, **env.configs(),
                    force_reprocess=True, dependencies=dependencies)

    assert _served(env) == [final.release_id]
    assert len(_superseded(env)) == 1


def test_broken_state_is_refused(tmp_path: Path, monkeypatch) -> None:
    env = make_env(tmp_path, monkeypatch)
    result = run_one(env.settings, OVERPASS, **env.configs(), dependencies=env.dependencies())
    shutil.rmtree(result.release_dir)

    with pytest.raises(ReconcileError, match="missing"):
        reconcile(env.layout, env.aoi_id, repair=False)
    item = json.loads((env.layout.products / env.aoi_id / "stac/items" / f"{OVERPASS}.json").read_text(encoding="utf-8"))
    assert item["properties"]["oceanos:release_id"] == result.release_id
