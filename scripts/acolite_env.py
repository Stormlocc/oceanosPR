"""Prepare and validate the pinned ACOLITE installation used by OCEANOS.

    uv run python scripts/acolite_env.py [--check | --install | --dry-run]

``--check`` is the default and is read-only: it creates nothing and downloads
nothing. The release tag, commit, paths and interpreter are read from
``configs/mvp.yaml``; this script never re-declares the pin.
"""

from __future__ import annotations

import argparse
import netrc
import stat
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

from oceanos.acolite import InstallationProbe
from oceanos.config import ConfigurationError, OceanosSettings, load_config
from oceanos.domain import AcolitePin, FailureRecord

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/mvp.yaml"
REPOSITORY = "https://github.com/acolite/acolite.git"
BACKUP_NAME = "acolite.main-d61c8de"
MICROMAMBA = Path.home() / ".local/bin/micromamba"
SENSORS = "S2A_MSI,S2B_MSI,S2C_MSI"
REQUIRED_DISK_BYTES = 10 * 1024**3

# Every dependency ACOLITE declares, mapped to the module that proves it is
# installed and to the distribution that carries its version ("" means the
# interpreter itself). An unmapped dependency is an error, never a skip.
ENVIRONMENT_IMPORTS: dict[str, tuple[str, str]] = {
    "python": ("sys", ""),
    "pyresample": ("pyresample", "pyresample"),
    "cartopy": ("cartopy", "cartopy"),
    "scipy": ("scipy", "scipy"),
    "numpy": ("numpy", "numpy"),
    "pyhdf": ("pyhdf", "pyhdf"),
    "gdal": ("osgeo.gdal", "gdal"),
    "libgdal-jp2openjpeg": ("osgeo.gdal", "gdal"),
    "libgdal-netcdf": ("osgeo.gdal", "gdal"),
    "netcdf4": ("netCDF4", "netCDF4"),
    "h5py": ("h5py", "h5py"),
    "pygrib": ("pygrib", "pygrib"),
    "requests": ("requests", "requests"),
    "matplotlib": ("matplotlib", "matplotlib"),
    "scikit-image": ("skimage", "scikit-image"),
    "pyproj": ("pyproj", "pyproj"),
    "zarr": ("zarr", "zarr"),
    "fsspec": ("fsspec", "fsspec"),
    "aiohttp": ("aiohttp", "aiohttp"),
}

# Runs inside the ACOLITE interpreter, which has no OCEANOS code on its path.
_IMPORT_PROGRAM = """\
import importlib
import importlib.metadata as metadata
import platform
import sys

for spec in sys.argv[1:]:
    dependency, module, distribution = spec.split("|")
    importlib.import_module(module)
    if not distribution:
        version = platform.python_version()
    else:
        try:
            version = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            version = "provided by a conda package"
    print(f"{dependency}={version}")
"""


class CheckError(RuntimeError):
    """A prerequisite of the pinned ACOLITE installation is not satisfied."""


def environment_dependencies(environment_yml: Path) -> list[str]:
    """Return the package names ACOLITE declares, with their version pins dropped."""
    document = yaml.safe_load(environment_yml.read_text(encoding="utf-8")) or {}
    return [
        entry.split("=", maxsplit=1)[0].split(">", maxsplit=1)[0].split("<", maxsplit=1)[0].strip()
        for entry in document.get("dependencies", [])
        if isinstance(entry, str)
    ]


def import_specs(dependencies: Sequence[str]) -> list[str]:
    """Return one ``dependency|module|distribution`` triple per declared package."""
    unmapped = sorted(set(dependencies) - set(ENVIRONMENT_IMPORTS))
    if unmapped:
        raise CheckError(f"unmapped environment dependencies: {', '.join(unmapped)}")
    return [f"{name}|{ENVIRONMENT_IMPORTS[name][0]}|{ENVIRONMENT_IMPORTS[name][1]}" for name in dependencies]


def existing_ancestor(path: Path) -> Path:
    """Return the closest existing directory, so a check creates no storage tier."""
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return Path.cwd()


def environment_prefix(python_executable: Path) -> Path:
    """Return the micromamba prefix that owns the configured interpreter."""
    return python_executable.parent.parent


def read_commit(root: Path) -> str:
    """Return the checked-out commit, or an empty string when there is no checkout."""
    if not (root / ".git").is_dir():
        return ""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def assert_only_config_modified(status: str) -> None:
    """The checkout may differ from the tag only in the pinned version line (DA #17)."""
    if status.strip() != "M config/config.txt":
        raise CheckError(
            f"ACOLITE checkout must only modify config/config.txt; got: {status.strip() or 'clean'}"
        )


def check_netrc(path: Path) -> None:
    """Both machines must be present, and only the owner may read the credentials."""
    if not path.is_file():
        raise CheckError(f"credentials file is missing: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise CheckError(f"{path} must have mode 600, not {mode:o}")
    try:
        credentials = netrc.netrc(str(path))
    except netrc.NetrcParseError as exc:
        raise CheckError(f"{path} cannot be parsed: {exc}") from exc
    missing = [machine for machine in ("earthdata", "cdse") if credentials.authenticators(machine) is None]
    if missing:
        raise CheckError(f"{path} lacks machine(s): {', '.join(missing)}")


def check_environment(root: Path, python_executable: Path) -> list[str]:
    """Import every declared dependency in the ACOLITE interpreter and report versions."""
    specs = import_specs(environment_dependencies(root / "environment.yml"))
    result = subprocess.run(
        [str(python_executable), "-c", _IMPORT_PROGRAM, *specs],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        raise CheckError(f"the ACOLITE environment is incomplete: {result.stderr.strip()}")
    return result.stdout.splitlines()


def check(settings: OceanosSettings) -> None:
    """Verify the pin, the LUTs, the reference data, the credentials and the environment."""
    config = settings.acolite
    netrc_path = Path.home() / ".netrc"
    installation = InstallationProbe().probe(
        pin=AcolitePin(release_tag=config.release_tag, commit_sha=config.commit_sha),
        root=config.root, python_executable=config.python_executable, launcher=config.launcher,
        luts_dir=config.luts_dir, netrc_path=netrc_path,
        disk_path=existing_ancestor(settings.storage.work), required_disk_bytes=REQUIRED_DISK_BYTES,
    )
    if isinstance(installation, FailureRecord):
        raise CheckError(f"{installation.message} ({installation.code.value}): {', '.join(installation.evidence)}")
    assert_only_config_modified(read_status(config.root))
    check_netrc(netrc_path)
    for line in check_environment(config.root, config.python_executable):
        print(f"environment dependency: {line}")
    print(f"ACOLITE environment check passed at {installation.observed_commit}.")


def read_status(root: Path) -> str:
    """Return ``git status --porcelain`` for the pinned checkout."""
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"], check=True, capture_output=True, text=True,
    )
    return result.stdout


def describe(settings: OceanosSettings) -> None:
    """Print what an install would do, without touching anything."""
    config = settings.acolite
    print(f"Would prepare ACOLITE tag {config.release_tag} at commit {config.commit_sha} in {config.root}.")
    print(f"Would preserve an unpinned {config.root} at {config.root.with_name(BACKUP_NAME)}.")
    print(f"Would create {environment_prefix(config.python_executable)} from {config.root / 'environment.yml'} when it is missing.")
    print(f"Would retrieve the {SENSORS} LUTs into {config.luts_dir}.")


def run(command: list[str], *, cwd: Path | None = None) -> None:
    """Run one external program and let its output reach the terminal."""
    print(f"$ {' '.join(command)}")
    subprocess.run(command, check=True, cwd=cwd)


def install(settings: OceanosSettings) -> None:
    """Clone the pin, keep any prior checkout, and retrieve the Sentinel-2 LUTs."""
    config = settings.acolite
    root = config.root
    if root.exists() and read_commit(root) != config.commit_sha:
        backup = root.with_name(BACKUP_NAME)
        if backup.exists():
            raise CheckError(f"a backup already exists; refusing to overwrite it: {backup}")
        root.rename(backup)
        print(f"Preserved the prior ACOLITE checkout at {backup}")

    if not (root / ".git").is_dir():
        run(["git", "clone", "--branch", config.release_tag, REPOSITORY, str(root)])
    observed = read_commit(root)
    if observed != config.commit_sha:
        raise CheckError(f"ACOLITE commit is {observed}, expected {config.commit_sha}")

    version_line = f"version={config.release_tag}"
    config_txt = root / "config/config.txt"
    if version_line not in config_txt.read_text(encoding="utf-8").splitlines():
        with config_txt.open("a", encoding="utf-8") as stream:
            stream.write(f"{version_line}\n")
        print(f"Appended {version_line} to {config_txt}")

    if not config.python_executable.is_file():
        run([
            str(MICROMAMBA), "create", "--yes",
            "--prefix", str(environment_prefix(config.python_executable)),
            "--file", str(root / "environment.yml"),
        ])
    run(
        [str(config.python_executable), str(config.launcher), "--retrieve_luts", "--sensor", SENSORS],
        cwd=config.launcher.parent,
    )
    print(f"ACOLITE is ready at {root}.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one mode and return its exit code."""
    parser = argparse.ArgumentParser(description="Prepare or validate the pinned ACOLITE installation.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the installation (default, read-only)")
    mode.add_argument("--install", action="store_true", help="clone the pin and retrieve the LUTs")
    mode.add_argument("--dry-run", action="store_true", help="describe what --install would do")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="OCEANOS configuration file")
    args = parser.parse_args(argv)

    try:
        settings = load_config(args.config)
        if args.install:
            install(settings)
        elif args.dry_run:
            describe(settings)
        else:
            check(settings)
    except (CheckError, ConfigurationError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
