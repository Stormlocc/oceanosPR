"""Validated tier layout, crash-safe directory publication, and writer locking."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import socket
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import IO, Literal

from pydantic import AwareDatetime, Field

from oceanos.domain import MetadataModel, validate_scene_id


class StorageLayout:
    """Resolved roots and validated identity-derived paths for every tier."""

    def __init__(
        self, *, raw: Path, work: Path, archive: Path, products: Path,
        superseded: Path, state: Path,
    ) -> None:
        self.raw = raw.expanduser().resolve()
        self.work = work.expanduser().resolve()
        self.archive = archive.expanduser().resolve()
        self.products = products.expanduser().resolve()
        self.superseded = superseded.expanduser().resolve()
        self.state = state.expanduser().resolve()

    @classmethod
    def from_data_root(cls, root: str | Path) -> StorageLayout:
        base = Path(root).expanduser().resolve()
        return cls(
            raw=base / "raw", work=base / "work", archive=base / "archive",
            products=base / "products", superseded=base / "superseded", state=base / "state",
        )

    def raw_scene_dir(self, scene_id: str) -> Path:
        value = validate_scene_id(scene_id)
        key = sha256(value.encode("utf-8")).hexdigest()
        return self.raw / "sentinel2-l1c" / key

    @staticmethod
    def _id(value: str, pattern: str, label: str) -> str:
        if re.fullmatch(pattern, value) is None:
            raise ValueError(f"invalid {label}")
        return value

    def grid_json(self, aoi_id: str) -> Path:
        value = self._id(aoi_id, r"aoi-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{12}", "AoiId")
        return self.products / value / "grid" / "grid.json"

    def work_attempt_dir(self, attempt_id: str) -> Path:
        value = self._id(attempt_id, r"att-\d{8}T\d{6}Z-[0-9a-f]{8}", "RunAttemptId")
        return self.work / "runs" / value

    def archive_attempt_dir(self, aoi_id: str, overpass_id: str, attempt_id: str) -> Path:
        aoi = self._id(aoi_id, r"aoi-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{12}", "AoiId")
        overpass = self._id(overpass_id, r"S2[ABC]_\d{8}T\d{6}_R\d{3}", "OverpassId")
        attempt = self._id(attempt_id, r"att-\d{8}T\d{6}Z-[0-9a-f]{8}", "RunAttemptId")
        return self.archive / aoi / overpass / attempt

    def release_dir(self, aoi_id: str, overpass_id: str, release_id: str) -> Path:
        aoi = self._id(aoi_id, r"aoi-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{12}", "AoiId")
        overpass = self._id(overpass_id, r"S2[ABC]_\d{8}T\d{6}_R\d{3}", "OverpassId")
        release = self._id(release_id, r"rel-[0-9a-f]{16}", "ReleaseId")
        return self.products / aoi / "releases" / overpass / release

    def superseded_release_dir(self, aoi_id: str, overpass_id: str, release_id: str) -> Path:
        release = self.release_dir(aoi_id, overpass_id, release_id)
        return self.superseded / release.relative_to(self.products)

    @property
    def writer_lock(self) -> Path:
        return self.state / "writer.lock"


class AtomicDirectory:
    """Stage a directory and atomically replace the destination on success."""

    def __init__(self, destination: str | Path) -> None:
        self.destination = Path(destination).expanduser().resolve()
        self.staging: Path | None = None

    def __enter__(self) -> Path:
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.staging = Path(tempfile.mkdtemp(prefix=f".{self.destination.name}-", dir=self.destination.parent))
        return self.staging

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if self.staging is None:
            return False
        if exc_type is not None:
            shutil.rmtree(self.staging, ignore_errors=True)
            return False
        backup: Path | None = None
        try:
            if self.destination.exists():
                backup = Path(tempfile.mkdtemp(prefix=f".{self.destination.name}-backup-", dir=self.destination.parent))
                backup.rmdir()
                os.replace(self.destination, backup)
            try:
                os.replace(self.staging, self.destination)
            except OSError:
                if backup is not None:
                    os.replace(backup, self.destination)
                raise
            if backup is not None:
                shutil.rmtree(backup)
        finally:
            if self.staging.exists():
                shutil.rmtree(self.staging, ignore_errors=True)
        return False


class LockHolder(MetadataModel):
    pid: int = Field(gt=0)
    proc_start_time: int | None
    boot_id: str | None
    host: str = Field(min_length=1)
    child_pid: int | None = Field(default=None, gt=0)
    child_pgid: int | None = Field(default=None, gt=0)
    child_start_time: int | None = None
    child_cmdline: str | None = None
    attempt_id: str = Field(pattern=r"^att-\d{8}T\d{6}Z-[0-9a-f]{8}$")
    started_at: AwareDatetime


class LockInspection(MetadataModel):
    locked: bool
    stale: bool
    holder: LockHolder | None


class WriterLockedError(RuntimeError):
    """Another process owns the single-writer lock."""


def _proc_start_time(pid: int) -> int | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return int(text[text.rfind(")") + 2 :].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None


class WriterLock:
    """Advisory Linux flock with a separately atomically-written holder record."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.holder_path = self.path.with_name(f"{self.path.name}.holder.json")
        self._stream: IO[str] | None = None
        self._holder: LockHolder | None = None

    @contextmanager
    def hold(self, attempt_id: str) -> Iterator[WriterLock]:
        self.acquire(attempt_id)
        try:
            yield self
        finally:
            self.release()

    def acquire(self, attempt_id: str) -> None:
        if self._stream is not None:
            raise RuntimeError("WriterLock instance already holds the lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.close()
            raise WriterLockedError("internal.writer_locked: another mutating command is active") from exc
        holder = LockHolder(
            pid=os.getpid(), proc_start_time=_proc_start_time(os.getpid()), boot_id=_boot_id(),
            host=socket.gethostname(), attempt_id=attempt_id, started_at=datetime.now(UTC),
        )
        self._stream = stream
        self._holder = holder
        self._write_holder(holder)

    def release(self) -> None:
        if self._stream is None:
            return
        fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()
        self._stream = None
        self._holder = None

    def update_child(self, pid: int, pgid: int, cmdline: str) -> None:
        """Atomically record child identity immediately after subprocess spawn."""
        if self._holder is None:
            raise RuntimeError("WriterLock is not held")
        self._holder = self._holder.model_copy(update={
            "child_pid": pid, "child_pgid": pgid, "child_start_time": _proc_start_time(pid),
            "child_cmdline": cmdline,
        })
        self._write_holder(self._holder)

    def inspect(self, terminal_attempt_ids: set[str] | None = None) -> LockInspection:
        holder = self._read_holder()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return LockInspection(locked=True, stale=False, holder=holder)
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        terminal = terminal_attempt_ids or set()
        return LockInspection(
            locked=False,
            stale=holder is not None and holder.attempt_id not in terminal,
            holder=holder,
        )

    def _write_holder(self, holder: LockHolder) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.holder_path.parent,
                prefix=f".{self.holder_path.name}-", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(holder.model_dump(mode="json"), stream, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.holder_path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def _read_holder(self) -> LockHolder | None:
        try:
            return LockHolder.model_validate_json(self.holder_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"invalid writer-lock holder record: {self.holder_path}") from exc
