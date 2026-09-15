"""Verified whole-SAFE acquisition from CDSE without extraction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import zipfile
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from pydantic import Field

from oceanos.catalog.local import LocalSceneCatalog
from oceanos.catalog.models import MetadataModel, SceneMetadata
from oceanos.domain import AcquiredScene, ArtifactRef, FailureCode
from oceanos.storage import StorageLayout

CHUNK_SIZE = 1024 * 1024
SAFE_BANDS = frozenset({"B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B10", "B11", "B12"})


class AcquisitionError(RuntimeError):
    """A source product could not become a verified acquired scene."""

    def __init__(self, code: FailureCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")


class SceneManifest(MetadataModel):
    """Portable manifest for one atomically published SAFE ZIP."""

    schema_version: Literal["1.0"] = "1.0"
    scene_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    status: Literal["complete"] = "complete"
    acquired: AcquiredScene
    provider_blake3: str | None = None


def _validate_safe(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name.rstrip("/") for name in archive.namelist() if not name.endswith("/")]
    except (OSError, zipfile.BadZipFile) as exc:
        raise AcquisitionError(FailureCode.SAFE_MEMBERS_MISSING, "product is not a readable ZIP") from exc
    roots = {name.split("/", 1)[0] for name in names if "/" in name}
    root_metadata = [name for name in names if name.count("/") == 1 and name.endswith("/MTD_MSIL1C.xml")]
    granules = {
        parts[2]
        for name in names
        if len(parts := name.split("/")) >= 4 and parts[1] == "GRANULE"
    }
    valid = len(roots) == 1 and len(root_metadata) == 1 and len(granules) == 1
    if valid:
        root = next(iter(roots))
        granule = next(iter(granules))
        prefix = f"{root}/GRANULE/{granule}/"
        tile_metadata = f"{prefix}MTD_TL.xml" in names
        image_bands = set()
        for name in names:
            if name.startswith(f"{prefix}IMG_DATA/") and name.lower().endswith(".jp2"):
                match = re.search(r"_B(0[1-9]|1[0-2]|8A)\.jp2$", name, re.IGNORECASE)
                if match is not None:
                        image_bands.add(f"B{match.group(1).upper()}")
        detector_masks = [name for name in names if name.startswith(f"{prefix}QI_DATA/MSK_DETFOO")]
        valid = tile_metadata and image_bands == SAFE_BANDS and bool(detector_masks)
    if not valid:
        raise AcquisitionError(
            FailureCode.SAFE_MEMBERS_MISSING,
            "SAFE must contain one granule, root/tile metadata, all 13 JP2 bands, and detector masks",
        )


def _atomic_json(model: MetadataModel, path: Path) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}-", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(model.model_dump(mode="json"), stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_manifest(path: Path, archive: Path, expected_sha256: str | None) -> SceneManifest | None:
    if not path.exists() or not archive.exists():
        return None
    try:
        manifest = SceneManifest.model_validate_json(path.read_text(encoding="utf-8"))
        digest = _file_sha256(archive)
    except (OSError, ValueError):
        return None
    wanted = expected_sha256 or manifest.acquired.archive.sha256
    if digest != manifest.acquired.archive.sha256 or digest != wanted or archive.stat().st_size != manifest.acquired.archive.size:
        return None
    _validate_safe(archive)
    return manifest


def _sync_catalog(
    catalog: LocalSceneCatalog | None,
    scene: SceneMetadata,
    manifest: SceneManifest,
    raw_root: Path,
    manifest_path: Path,
) -> None:
    if catalog is None:
        return
    assert scene.checksums is not None and scene.checksums.md5 is not None
    catalog.record_acquisition(
        scene.scene_id,
        manifest_relpath=manifest_path.relative_to(raw_root).as_posix(),
        archive_relpath=manifest.acquired.archive.relpath,
        file_size=manifest.acquired.archive.size,
        sha256=manifest.acquired.archive.sha256,
        provider_md5=scene.checksums.md5.lower(),
    )


def acquire_scene(
    scene: SceneMetadata,
    raw_root: str | Path,
    *,
    token_provider: Callable[[], str],
    expected_sha256: str | None = None,
    catalog: LocalSceneCatalog | None = None,
    timeout: float = 60,
    max_retries: int = 1,
    client: httpx.Client | None = None,
) -> SceneManifest:
    """Download, verify, and atomically publish one complete L1C SAFE ZIP."""
    if scene.processing_level != "Level-1C":
        raise AcquisitionError(FailureCode.NOT_L1C, "acquisition accepts only Level-1C scenes")
    if scene.online is False:
        raise AcquisitionError(FailureCode.PRODUCT_OFFLINE, "CDSE reports the product offline")
    if scene.source_id is None or scene.checksums is None or scene.checksums.md5 is None:
        raise AcquisitionError(FailureCode.MD5_MISMATCH, "CDSE MD5 is required for acquisition")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if not isinstance(max_retries, int) or not 0 <= max_retries <= 5:
        raise ValueError("max_retries must be an integer between 0 and 5")
    if set(scene.assets) != {"product"}:
        raise AcquisitionError(FailureCode.SAFE_MEMBERS_MISSING, "scene must expose exactly one product asset")
    asset = scene.assets["product"]
    if asset.file_size is None or asset.file_size <= 0:
        raise AcquisitionError(FailureCode.SAFE_MEMBERS_MISSING, "catalogue ContentLength is required")
    raw_path = Path(raw_root).expanduser().resolve()
    layout = StorageLayout.from_data_root(raw_path.parent)
    layout.raw = raw_path
    directory = layout.raw_scene_dir(scene.scene_id)
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f"{scene.scene_id}.zip"
    manifest_path = directory / "manifest.json"
    existing = _existing_manifest(manifest_path, archive, expected_sha256)
    if existing is not None:
        _sync_catalog(catalog, scene, existing, layout.raw, manifest_path)
        return existing
    temporary = archive.with_suffix(".zip.part")
    context = nullcontext(client) if client is not None else httpx.Client()
    last_error: AcquisitionError | None = None
    try:
        with context as transport:
            for attempt in range(max_retries + 1):
                md5 = hashlib.md5(usedforsecurity=False)
                sha256 = hashlib.sha256()
                size = 0
                try:
                    token = token_provider()
                    with transport.stream(
                        "GET", asset.href,
                        headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"},
                        timeout=timeout,
                    ) as response:
                        if response.status_code != 200 or "Content-Range" in response.headers:
                            raise AcquisitionError(FailureCode.INTERNAL_UNEXPECTED, f"full transfer requires HTTP 200, got {response.status_code}")
                        header = response.headers.get("Content-Length")
                        if header is None or int(header) != asset.file_size:
                            raise AcquisitionError(FailureCode.INTERNAL_UNEXPECTED, "Content-Length differs from catalogue ContentLength")
                        with temporary.open("wb") as stream:
                            for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                                stream.write(chunk)
                                md5.update(chunk)
                                sha256.update(chunk)
                                size += len(chunk)
                            stream.flush()
                            os.fsync(stream.fileno())
                    if size != asset.file_size:
                        raise AcquisitionError(FailureCode.INTERNAL_UNEXPECTED, "downloaded size differs from ContentLength")
                    if md5.hexdigest().lower() != scene.checksums.md5.lower():
                        raise AcquisitionError(FailureCode.MD5_MISMATCH, "stream MD5 differs from provider checksum")
                    digest = sha256.hexdigest()
                    if expected_sha256 is not None and digest != expected_sha256:
                        raise AcquisitionError(FailureCode.REFETCH_MISMATCH, "re-fetched SAFE differs from recorded SHA-256")
                    _validate_safe(temporary)
                    os.replace(temporary, archive)
                    relative = archive.relative_to(layout.raw).as_posix()
                    acquired = AcquiredScene(
                        scene_id=scene.scene_id, source_id=scene.source_id,
                        archive=ArtifactRef(
                            role="source", relpath=relative, sha256=digest, size=size,
                            media_type="application/zip",
                        ),
                        provider_md5_verified=True, safe_members_verified=True,
                        verified_at=datetime.now(UTC),
                    )
                    manifest = SceneManifest(
                        scene_id=scene.scene_id, source_id=scene.source_id,
                        acquired=acquired, provider_blake3=scene.checksums.blake3,
                    )
                    _atomic_json(manifest, manifest_path)
                    _sync_catalog(catalog, scene, manifest, layout.raw, manifest_path)
                    return manifest
                except AcquisitionError as exc:
                    last_error = exc
                    if exc.code is not FailureCode.MD5_MISMATCH or attempt == max_retries:
                        raise
                except (httpx.HTTPError, OSError, ValueError) as exc:
                    last_error = AcquisitionError(FailureCode.INTERNAL_UNEXPECTED, f"SAFE transfer failed: {type(exc).__name__}")
                    if attempt == max_retries:
                        raise last_error from exc
                finally:
                    if temporary.exists():
                        temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()
    assert last_error is not None
    raise last_error
