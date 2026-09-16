"""Read-only validation of the pinned local ACOLITE installation."""

from __future__ import annotations

import netrc
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from oceanos.domain import (
    AcoliteInstallation,
    AcolitePin,
    FailureCode,
    FailureRecord,
    FailureScope,
)


def _read_commit(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


class InstallationProbe:
    """Verify environment prerequisites without importing ACOLITE."""

    def __init__(self, commit_reader: Callable[[Path], str] = _read_commit) -> None:
        self._commit_reader = commit_reader

    @staticmethod
    def _failure(code: FailureCode, message: str, evidence: list[str]) -> FailureRecord:
        return FailureRecord(
            code=code, scope=FailureScope.BATCH, stage="preflight", message=message,
            evidence=evidence, retryable=True, occurred_at=datetime.now(UTC),
        )

    def probe(
        self, *, pin: AcolitePin, root: Path, python_executable: Path, launcher: Path,
        luts_dir: Path, external_dir: Path, netrc_path: Path, disk_path: Path,
        required_disk_bytes: int,
    ) -> AcoliteInstallation | FailureRecord:
        """Return observed installation state or the first batch failure."""
        try:
            observed_commit = self._commit_reader(root)
        except (OSError, subprocess.SubprocessError) as exc:
            return self._failure(FailureCode.ACOLITE_COMMIT_MISMATCH, "cannot read ACOLITE commit", [type(exc).__name__])
        if observed_commit != pin.commit_sha or not python_executable.is_file() or not launcher.is_file():
            return self._failure(
                FailureCode.ACOLITE_COMMIT_MISMATCH, "ACOLITE installation does not match the pin",
                [f"observed_commit={observed_commit}"],
            )

        config_path = root / "config/config.txt"
        try:
            version_lines = [
                line.strip() for line in config_path.read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("version=")
            ]
        except OSError:
            version_lines = []
        expected_version = f"version={pin.release_tag}"
        if version_lines != [expected_version]:
            return self._failure(
                FailureCode.ACOLITE_VERSION_LINE_MISSING,
                "ACOLITE config must contain exactly one pinned version line", version_lines,
            )

        sensor_dirs = {
            "S2A_MSI": tuple(luts_dir.rglob("S2A_MSI")),
            "S2B_MSI": tuple(luts_dir.rglob("S2B_MSI")),
            "S2C_MSI": tuple(luts_dir.rglob("S2C_MSI*")),
        }
        present = {
            sensor for sensor, directories in sensor_dirs.items()
            if any(directory.is_dir() and any(path.is_file() for path in directory.rglob("*")) for directory in directories)
        }
        if present != set(sensor_dirs):
            return self._failure(FailureCode.LUTS_MISSING, "required Sentinel-2 LUTs are missing", sorted(present))

        gshhg = external_dir / "gshhg"
        gshhg_present = gshhg.is_dir() and any(path.is_file() for path in gshhg.rglob("*"))
        if not gshhg_present:
            return self._failure(FailureCode.GSHHG_MISSING, "OCEANOS GSHHG data are missing", ["gshhg"])

        try:
            credentials_present = netrc.netrc(str(netrc_path)).authenticators("earthdata") is not None
        except (OSError, netrc.NetrcParseError):
            credentials_present = False
        if not credentials_present:
            return self._failure(FailureCode.CREDENTIALS_MISSING, "EarthData netrc entry is missing", ["earthdata"])

        try:
            free_disk_bytes = shutil.disk_usage(disk_path).free
        except OSError:
            free_disk_bytes = 0
        if free_disk_bytes < required_disk_bytes:
            return self._failure(
                FailureCode.DISK_INSUFFICIENT, "insufficient free disk for the attempt",
                [f"free_bytes={free_disk_bytes}", f"required_bytes={required_disk_bytes}"],
            )

        return AcoliteInstallation(
            root=str(root), python_executable=str(python_executable),
            observed_commit=observed_commit, config_version_line=expected_version,
            luts_present=present, gshhg_present=True, credentials_present=True,
            free_disk_bytes=free_disk_bytes,
        )
