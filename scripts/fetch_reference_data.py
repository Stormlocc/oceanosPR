"""Download and verify the OCEANOS-owned reference datasets.

    uv run python scripts/fetch_reference_data.py [gshhg | bathymetry | all] [--check]

Every file is pinned here by size and SHA-256. Neither value is ever computed
from a downloaded file and written back: a mismatch is a failure (B12). The
provenance of each accepted checksum is recorded in PLAN.md and design-threads.md.

Destination: ``acolite.external_dir`` from the OCEANOS configuration.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

import httpx

from oceanos.config import ConfigurationError, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/mvp.yaml"
DOWNLOAD_ATTEMPTS = 3
CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PinnedFile:
    """One remote file, accepted only at this exact size and digest."""

    url: str
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Dataset:
    """A reference dataset: its files, and the archive members it unpacks."""

    directory: str
    files: tuple[PinnedFile, ...]
    members: tuple[str, ...] = field(default=())


_GSHHG_URL = "https://www.soest.hawaii.edu/pwessel/gshhg/gshhg-shp-2.3.7.zip"
_CUDEM_URL = "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/NCEI_ninth_Topobathy_PuertoRico_9525"

DATASETS: dict[str, Dataset] = {
    # GSHHG 2.3.7 full resolution, level 1 land polygons. OCEANOS applies the
    # land mask itself; the pin never applies its own (DA-1).
    "gshhg": Dataset(
        directory="gshhg",
        files=(
            PinnedFile(
                url=_GSHHG_URL,
                name="gshhg-shp-2.3.7.zip",
                size=149157845,
                sha256="8dbbe7e071e77e9e75f2d639239099ebca8d5c16d6a07df8169729d49f15cf41",
            ),
        ),
        members=tuple(f"GSHHS_shp/f/GSHHS_f_L1.{suffix}" for suffix in ("shp", "shx", "dbf", "prj")),
    ),
    # NOAA NCEI CUDEM 1/9", Puerto Rico 2022v2, NAD83 + PRVD02 metres positive up.
    "bathymetry": Dataset(
        directory="bathymetry/cudem",
        files=(
            PinnedFile(
                url=f"{_CUDEM_URL}/ncei19_n18x00_w067x00_2022v2.tif",
                name="ncei19_n18x00_w067x00_2022v2.tif",
                size=161978725,
                sha256="7b4d211a22104e7f7ef32a5e71a67cbf9403c4dbc9a4b5fdc0be4a51e113d4ed",
            ),
            PinnedFile(
                url=f"{_CUDEM_URL}/ncei19_n18x00_w067x25_2022v2.tif",
                name="ncei19_n18x00_w067x25_2022v2.tif",
                size=175373802,
                sha256="c5ef52dd3bd102edc0780bd55d110a33d953d8a1bf43dcb0d511636ecb1eb3e4",
            ),
            PinnedFile(
                url=f"{_CUDEM_URL}/ncei19_n18x25_w067x00_2022v2.tif",
                name="ncei19_n18x25_w067x00_2022v2.tif",
                size=213041389,
                sha256="4f2a1cb5669ee02bcbaaa55ff026750058800257482a26d74d4fd4f032eb0264",
            ),
            PinnedFile(
                url=f"{_CUDEM_URL}/ncei19_n18x25_w067x25_2022v2.tif",
                name="ncei19_n18x25_w067x25_2022v2.tif",
                size=219311934,
                sha256="5efcd93a1dd900bd0f6cff3c2ac27ff69daf46af52d1ae6ee1d6c40b236d5a18",
            ),
        ),
    ),
}


class CheckError(RuntimeError):
    """A reference file is missing or does not match its pinned identity."""


def digest_of(path: Path) -> str:
    """Return the SHA-256 of a file, read in bounded blocks."""
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path, pinned: PinnedFile) -> None:
    """Accept a file only at its pinned size and digest."""
    if not path.is_file():
        raise CheckError(f"reference file is missing: {path}")
    size = path.stat().st_size
    if size != pinned.size:
        raise CheckError(f"{path} has {size} bytes, expected {pinned.size}")
    if digest_of(path) != pinned.sha256:
        raise CheckError(f"{path} does not match the pinned SHA-256")


def download(pinned: PinnedFile, target: Path) -> None:
    """Stream to a partial file and rename it into place only once complete."""
    partial = target.with_name(f"{target.name}.part")
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with httpx.stream("GET", pinned.url, follow_redirects=True, timeout=60.0) as response:
                response.raise_for_status()
                with partial.open("wb") as stream:
                    for chunk in response.iter_bytes(CHUNK_BYTES):
                        stream.write(chunk)
            break
        except httpx.HTTPError as exc:
            partial.unlink(missing_ok=True)
            if attempt == DOWNLOAD_ATTEMPTS:
                raise CheckError(f"could not download {pinned.url}: {exc}") from exc
            print(f"retrying {pinned.name} after {type(exc).__name__}")
    partial.replace(target)


def extract(archive: Path, members: Sequence[str], directory: Path) -> None:
    """Unpack the named members through a staging directory, then move them into place."""
    staging = directory / ".extract"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(archive) as source:
            broken = source.testzip()
            if broken is not None:
                raise CheckError(f"CRC failure in {archive}: {broken}")
            missing = sorted(set(members) - set(source.namelist()))
            if missing:
                raise CheckError(f"{archive} lacks required members: {', '.join(missing)}")
            source.extractall(staging, members=list(members))
        for member in members:
            target = directory / member
            target.parent.mkdir(parents=True, exist_ok=True)
            (staging / member).replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def check(dataset: Dataset, directory: Path) -> None:
    """Verify every pinned file and every unpacked member."""
    for pinned in dataset.files:
        verify(directory / pinned.name, pinned)
    for member in dataset.members:
        if not (directory / member).is_file():
            raise CheckError(f"reference data is missing: {directory / member}")


def fetch(dataset: Dataset, directory: Path) -> None:
    """Download what is absent, verify everything, and unpack the archive members."""
    directory.mkdir(parents=True, exist_ok=True)
    for pinned in dataset.files:
        target = directory / pinned.name
        if not target.is_file():
            download(pinned, target)
        verify(target, pinned)
    if dataset.members and not all((directory / member).is_file() for member in dataset.members):
        extract(directory / dataset.files[0].name, dataset.members, directory)
    check(dataset, directory)


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch or check one dataset, or all of them, and return an exit code."""
    parser = argparse.ArgumentParser(description="Fetch the OCEANOS-owned reference datasets.")
    parser.add_argument("dataset", nargs="?", default="all", choices=("all", *DATASETS), help="dataset to handle")
    parser.add_argument("--check", action="store_true", help="verify what is on disk without downloading")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="OCEANOS configuration file")
    args = parser.parse_args(argv)

    selected = list(DATASETS) if args.dataset == "all" else [args.dataset]
    try:
        external_dir = load_config(args.config).acolite.external_dir
        for name in selected:
            dataset = DATASETS[name]
            directory = external_dir / dataset.directory
            if args.check:
                check(dataset, directory)
                print(f"{name}: reference data check passed at {directory}")
            else:
                fetch(dataset, directory)
                print(f"{name}: reference data is ready at {directory}")
    except (CheckError, ConfigurationError, OSError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
