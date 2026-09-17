"""P4 atomic archive, attempt ledger, and guarded stale-run recovery."""

from __future__ import annotations

import json
import os
import shutil
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from oceanos.domain import (
    AcoliteProfile,
    AcoliteRunOutputs,
    FailureCode,
    FailureRecord,
    FailureScope,
    RunAttempt,
    RunState,
)
from oceanos.storage import (
    AtomicDirectory,
    StorageLayout,
    WriterLock,
    boot_id,
    process_start_time,
)


class AttemptsLedger:
    """Append-only, fsynced source of attempt state transitions."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, attempt: RunAttempt) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(attempt.model_dump(mode="json"), sort_keys=True, allow_nan=False)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def latest(self) -> dict[str, RunAttempt]:
        if not self.path.exists():
            return {}
        records: dict[str, RunAttempt] = {}
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    attempt = RunAttempt.model_validate_json(line)
                except ValueError as exc:
                    raise RuntimeError(f"invalid attempt ledger row {line_number}") from exc
                records[attempt.attempt_id] = attempt
        return records


def _as_json(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


class ArchiveStore:
    """Commit the exact P4 allow-list and authoritative manifest atomically."""

    def __init__(self, layout: StorageLayout) -> None:
        self.layout = layout

    def commit(
        self, *, aoi_id: str, overpass_id: str, attempt: RunAttempt,
        profile: AcoliteProfile, input_set: BaseModel | dict[str, Any],
        installation: BaseModel | dict[str, Any], workspace: Path,
        outputs: AcoliteRunOutputs,
    ) -> Path:
        destination = self.layout.archive_attempt_dir(aoi_id, overpass_id, attempt.attempt_id)
        sources = {
            Path(outputs.l2r.relpath).name: workspace / outputs.l2r.relpath,
            Path(outputs.l2w.relpath).name: workspace / outputs.l2w.relpath,
            "run.log": workspace / outputs.log.relpath,
            "l1r_settings_user.txt": workspace / outputs.settings_user.relpath,
            "l2r_settings.txt": workspace / outputs.settings_resolved.relpath,
        }
        if any(not source.is_file() for source in sources.values()):
            missing = sorted(name for name, source in sources.items() if not source.is_file())
            raise FileNotFoundError(f"P4 source allow-list incomplete: {missing}")
        archive_prefix = destination.relative_to(self.layout.archive)
        archived_files = [(archive_prefix / name).as_posix() for name in sources]
        archived_outputs = outputs.model_dump(mode="json")
        output_names = {
            "l2r": Path(outputs.l2r.relpath).name,
            "l2w": Path(outputs.l2w.relpath).name,
            "log": "run.log",
            "settings_user": "l1r_settings_user.txt",
            "settings_resolved": "l2r_settings.txt",
        }
        for field, name in output_names.items():
            archived_outputs[field]["relpath"] = (archive_prefix / name).as_posix()
        archived_attempt = attempt.model_copy(update={"state": RunState.ARCHIVED})
        installation_json = _as_json(installation)
        installation_json.pop("root", None)
        installation_json.pop("python_executable", None)
        manifest = {
            "schema_version": "1.0",
            "attempt": archived_attempt.model_dump(mode="json"),
            "run_key": attempt.run_key,
            "observation_id": f"{aoi_id}/{overpass_id}",
            "input_set": _as_json(input_set),
            "acolite_profile": profile.model_dump(mode="json"),
            "acolite_profile_id": profile.profile_id,
            "archived_files": archived_files,
            "installation": installation_json,
            "outputs": archived_outputs,
            "flag_spec": outputs.flag_spec.model_dump(mode="json"),
            "ancillary": outputs.ancillary.model_dump(mode="json"),
            "glint_angle_deg": outputs.glint_angle_deg,
        }
        with AtomicDirectory(destination) as staging:
            for name, source in sources.items():
                shutil.copy2(source, staging / name)
            manifest_path = staging / "run-manifest.json"
            with manifest_path.open("w", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        return destination


def _actual_cmdline(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def recover_stale_attempt(
    *, lock: WriterLock, ledger: AttemptsLedger, staging: Path,
) -> RunAttempt | None:
    """Abandon a stale attempt and kill only a provably identical child group."""
    latest = ledger.latest()
    terminal = {attempt_id for attempt_id, attempt in latest.items() if attempt.state.terminal}
    inspection = lock.inspect(terminal)
    holder = inspection.holder
    if inspection.locked or not inspection.stale or holder is None:
        return None
    attempt = latest.get(holder.attempt_id)
    if attempt is None or attempt.state.terminal:
        return None

    child_pid = holder.child_pid
    child_pgid = holder.child_pgid
    identity_matches = (
        child_pid is not None
        and child_pgid is not None
        and holder.boot_id is not None
        and holder.boot_id == boot_id()
        and holder.child_start_time is not None
        and holder.child_start_time == process_start_time(child_pid)
        and holder.child_cmdline is not None
        and (cmdline := _actual_cmdline(child_pid)) is not None
        and "launch_acolite.py" in holder.child_cmdline
        and holder.child_cmdline.split() == cmdline.split()
    )
    if identity_matches:
        assert child_pid is not None and child_pgid is not None
        try:
            if os.getpgid(child_pid) == child_pgid:
                os.killpg(child_pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    failure = FailureRecord(
        code=FailureCode.INTERNAL_ABANDONED, scope=FailureScope.OBSERVATION,
        stage="restart", message="non-terminal attempt had a stale writer holder",
        evidence=[f"child_identity_matched={identity_matches}"], retryable=True,
        occurred_at=datetime.now(UTC),
    )
    abandoned = attempt.model_copy(update={"state": RunState.ABANDONED, "failure": failure})
    ledger.append(abandoned)
    if staging.exists():
        shutil.rmtree(staging)
    return abandoned
