"""Process-isolated ACOLITE CLI execution with bounded lifetime."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path, PurePosixPath

from pydantic import Field, field_validator

from oceanos.domain import MetadataModel
from oceanos.storage import WriterLock


class ProcessOutcome(MetadataModel):
    runid: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    exit_code: int
    duration_seconds: float = Field(ge=0)
    log_path: str = Field(min_length=1)
    timed_out: bool

    @field_validator("log_path")
    @classmethod
    def relative_log_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("process log path must be workspace-relative")
        return path.as_posix()


class SubprocessAcoliteRunner:
    """Launch ACOLITE in its own process group and record child identity."""

    def run(
        self, *, python_executable: Path, launcher: Path, settings_path: Path,
        workspace: Path, timeout_seconds: float, runid: str, lock: WriterLock,
    ) -> ProcessOutcome:
        workspace.mkdir(parents=True, exist_ok=True)
        # ACOLITE writes its own run text file in the workspace. Keep the
        # subprocess tee separate so two writers never truncate each other.
        log_path = workspace / "run.log"
        command = [
            str(python_executable), str(launcher), "--cli", f"--settings={settings_path}",
        ]
        prefix = python_executable.parent.parent
        environment = os.environ.copy()
        environment.update({
            "PROJ_DATA": str(prefix / "share/proj"),
            "GDAL_DATA": str(prefix / "share/gdal"),
            "GDAL_DRIVER_PATH": str(prefix / "lib/gdalplugins"),
            "PROJ_NETWORK": "ON",
            "PATH": f"{prefix / 'bin'}{os.pathsep}{environment.get('PATH', '')}",
        })
        started = time.monotonic()
        timed_out = False
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command, cwd=launcher.parent, stdout=log, stderr=subprocess.STDOUT,
                text=True, start_new_session=True, env=environment,
            )
            pgid = os.getpgid(process.pid)
            lock.update_child(process.pid, pgid, " ".join(command))
            try:
                exit_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(pgid, signal.SIGTERM)
                try:
                    exit_code = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
                    exit_code = process.wait()
            log.flush()
            os.fsync(log.fileno())
        return ProcessOutcome(
            runid=runid, exit_code=exit_code,
            duration_seconds=time.monotonic() - started,
            log_path=log_path.relative_to(workspace).as_posix(), timed_out=timed_out,
        )
