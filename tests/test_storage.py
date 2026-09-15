"""Storage paths, directory commits, and writer locks preserve state."""

from __future__ import annotations

from pathlib import Path

import pytest

from oceanos.storage import (
    AtomicDirectory,
    StorageLayout,
    WriterLock,
    WriterLockedError,
)


def test_tier_paths_are_derived_from_validated_ids(tmp_path: Path) -> None:
    layout = StorageLayout.from_data_root(tmp_path)
    path = layout.raw_scene_dir("S2A_MSIL1C_20260702T150741_N0512_R082_T19QGV_X")
    assert path.parent == tmp_path / "raw" / "sentinel2-l1c"
    assert path.name != "S2A_MSIL1C_20260702T150741_N0512_R082_T19QGV_X"
    with pytest.raises(ValueError):
        layout.raw_scene_dir("../../outside")


def test_atomic_directory_rolls_back_failed_replacement(monkeypatch, tmp_path: Path) -> None:
    destination = tmp_path / "published"
    destination.mkdir()
    (destination / "value").write_text("old", encoding="utf-8")
    with pytest.raises(RuntimeError), AtomicDirectory(destination) as staging:
        (staging / "value").write_text("new", encoding="utf-8")
        raise RuntimeError("abort")
    assert (destination / "value").read_text(encoding="utf-8") == "old"

    from oceanos import storage

    real_replace = storage.os.replace
    calls = []

    def fail_commit(source, target):
        calls.append((Path(source), Path(target)))
        if Path(target) == destination and len(calls) == 2:
            raise OSError("commit failed")
        real_replace(source, target)

    monkeypatch.setattr(storage.os, "replace", fail_commit)
    with pytest.raises(OSError), AtomicDirectory(destination) as staging:
        (staging / "value").write_text("new", encoding="utf-8")
    assert (destination / "value").read_text(encoding="utf-8") == "old"


def test_writer_lock_records_holder_and_rejects_second_writer(tmp_path: Path) -> None:
    path = tmp_path / "state" / "writer.lock"
    first = WriterLock(path)
    second = WriterLock(path)
    with first.hold("att-20260915T120000Z-01234567"):
        inspection = second.inspect()
        assert inspection.locked is True
        assert inspection.holder is not None
        assert inspection.holder.attempt_id == "att-20260915T120000Z-01234567"
        assert inspection.holder.child_pid is None
        with (
            pytest.raises(WriterLockedError, match="internal.writer_locked"),
            second.hold("att-20260915T120001Z-01234567"),
        ):
            pass
        first.update_child(123, 123, "launch_acolite.py --run")
        assert second.inspect().holder.child_cmdline == "launch_acolite.py --run"
    assert second.inspect().stale is True
    assert second.inspect({"att-20260915T120000Z-01234567"}).stale is False
