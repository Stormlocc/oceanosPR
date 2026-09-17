"""Single-writer contention and stale process recovery are fail-safe."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from oceanos.domain import RunAttempt, RunState
from oceanos.pipeline.archive import AttemptsLedger, recover_stale_attempt
from oceanos.storage import WriterLock, WriterLockedError

ATTEMPT_ID = "att-20260915T120000Z-01234567"


def _attempt(state: RunState) -> RunAttempt:
    return RunAttempt(
        attempt_id=ATTEMPT_ID, run_key="run-0123456789abcdef", state=state,
        host="test", oceanos_version="0.1.0", oceanos_git_sha="a" * 40,
        acolite_exit_code=None, stages=[], failure=None,
    )


def _stale_process(tmp_path: Path) -> tuple[WriterLock, subprocess.Popen[str]]:
    script = tmp_path / "launch_acolite.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    child = subprocess.Popen([sys.executable, str(script)], start_new_session=True, text=True)
    lock = WriterLock(tmp_path / "state/writer.lock")
    lock.acquire(ATTEMPT_ID)
    lock.update_child(child.pid, os.getpgid(child.pid), " ".join([sys.executable, str(script)]))
    lock.release()
    return lock, child


def test_live_second_writer_gets_internal_writer_locked(tmp_path: Path) -> None:
    first = WriterLock(tmp_path / "state/writer.lock")
    second = WriterLock(tmp_path / "state/writer.lock")
    with (
        first.hold(ATTEMPT_ID),
        pytest.raises(WriterLockedError, match=r"internal\.writer_locked"),
    ):
        second.acquire("att-20260915T120001Z-01234567")


def test_valid_stale_child_group_is_killed_and_attempt_abandoned(tmp_path: Path) -> None:
    lock, child = _stale_process(tmp_path)
    ledger = AttemptsLedger(tmp_path / "state/ledger/attempts.jsonl")
    ledger.append(_attempt(RunState.EXECUTED))
    staging = tmp_path / "work/runs" / ATTEMPT_ID
    staging.mkdir(parents=True)
    try:
        recovered = recover_stale_attempt(lock=lock, ledger=ledger, staging=staging)
        child.wait(timeout=5)
        assert recovered.state is RunState.ABANDONED
        assert not staging.exists()
    finally:
        if child.poll() is None:
            os.killpg(os.getpgid(child.pid), 9)
            child.wait()


@pytest.mark.parametrize("mismatch", ["boot", "start", "cmdline"])
def test_stale_identity_mismatch_kills_nothing(tmp_path: Path, mismatch: str) -> None:
    lock, child = _stale_process(tmp_path)
    ledger = AttemptsLedger(tmp_path / "state/ledger/attempts.jsonl")
    ledger.append(_attempt(RunState.EXECUTED))
    holder = lock._read_holder()
    assert holder is not None
    if mismatch == "boot":
        update = {"boot_id": "wrong"}
    elif mismatch == "start":
        update = {"child_start_time": -1}
    else:
        update = {"child_cmdline": "python unrelated.py"}
    lock._write_holder(holder.model_copy(update=update))
    try:
        recover_stale_attempt(lock=lock, ledger=ledger, staging=tmp_path / "unused")
        time.sleep(0.05)
        assert child.poll() is None
    finally:
        if child.poll() is None:
            os.killpg(os.getpgid(child.pid), 9)
            child.wait()
