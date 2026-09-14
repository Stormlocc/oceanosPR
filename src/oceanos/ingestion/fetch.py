"""Controlled streaming downloads for one already-cataloged Sentinel-2 scene."""

from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
from collections.abc import Sequence
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import AwareDatetime, Field

from oceanos.catalog import LocalSceneCatalog, SceneAsset, SceneMetadata
from oceanos.catalog.models import MetadataModel

MVP_BANDS = ("B02", "B03", "B04", "B08", "B11")
BAND_ASSETS = {"B02": "blue", "B03": "green", "B04": "red", "B08": "nir", "B11": "swir16"}
CHUNK_SIZE = 1024 * 1024


class MaterializationError(RuntimeError):
    """A requested asset is absent, unsupported, or could not be verified."""


class MaterializedAsset(MetadataModel):
    asset_key: str
    source_url: str
    download_timestamp: AwareDatetime
    local_path: str  # Relative to the scene directory containing manifest.json.
    file_size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FailedAsset(MetadataModel):
    asset_key: str
    source_url: str
    timestamp: AwareDatetime
    error: str


class SceneManifest(MetadataModel):
    schema_version: Literal["1.0"] = "1.0"
    scene_id: str
    status: Literal["pending", "partial", "complete", "failed"] = "pending"
    assets: dict[str, MaterializedAsset] = Field(default_factory=dict)
    failures: dict[str, FailedAsset] = Field(default_factory=dict)


def _resolve_asset(scene: SceneMetadata, band: str) -> tuple[str, SceneAsset]:
    # B08 is the broad NIR band (nir), not B8A (nir08).
    for candidate in (band.casefold(), BAND_ASSETS[band]):
        matches = [(key, asset) for key, asset in scene.assets.items() if key.casefold() == candidate]
        if len(matches) > 1:
            raise MaterializationError(f"Ambiguous asset for band {band}")
        if matches:
            return matches[0]
    raise MaterializationError(f"Scene {scene.scene_id} has no asset for band {band}")


def _filename(band: str, asset: SceneAsset) -> str:
    suffix = Path(urlsplit(asset.href).path).suffix.lower()
    # Preserve known source formats without pretending to convert a raster.
    return band + (suffix if suffix in {".tif", ".tiff", ".jp2"} else ".bin")


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verified(record: MaterializedAsset, key: str, asset: SceneAsset, destination: Path) -> bool:
    if record.asset_key != key or record.source_url != asset.href or record.local_path != destination.name:
        return False
    if destination.is_symlink() or not destination.is_file():
        return False
    size = destination.stat().st_size
    if size != record.file_size or (asset.file_size is not None and size != asset.file_size):
        return False
    return _sha256(destination) == record.sha256


def _save_manifest(manifest: SceneManifest, path: Path) -> None:
    text = manifest.model_dump_json(indent=2) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_materialized_bands(
    scene: SceneMetadata, raw_dir: str | Path, bands: Sequence[str] = MVP_BANDS,
) -> dict[str, Path]:
    """Read-only verification for downstream processing; never fetch missing data."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", scene.scene_id):
        raise MaterializationError("scene_id must be a safe filename component")
    directory = Path(raw_dir).expanduser().resolve() / "sentinel2" / scene.scene_id
    if directory.resolve() != directory:
        raise MaterializationError("Scene directory must not contain symbolic links")
    try:
        manifest = SceneManifest.model_validate_json((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.scene_id != scene.scene_id:
            raise ValueError("Manifest belongs to a different scene")
        paths = {}
        for band in bands:
            if band not in MVP_BANDS or band not in manifest.assets:
                raise ValueError(f"Band {band} is not materialized")
            key, asset = _resolve_asset(scene, band)
            path = directory / _filename(band, asset)
            if not _verified(manifest.assets[band], key, asset, path):
                raise ValueError(f"Band {band} failed local integrity verification")
            paths[band] = path
        return paths
    except (OSError, ValueError) as exc:
        raise MaterializationError(f"Cannot use materialized scene {scene.scene_id}: {exc}") from exc


def _sync(manifest: SceneManifest, path: Path, catalog: LocalSceneCatalog) -> None:
    manifest.status = (
        "complete" if set(MVP_BANDS) <= manifest.assets.keys()
        else "partial" if manifest.assets else "failed" if manifest.failures else "pending"
    )
    _save_manifest(manifest, path)
    assets = {}
    for record in manifest.assets.values():
        data = record.model_dump(mode="json")
        data["local_path"] = str(path.parent / record.local_path)
        assets[record.asset_key] = data
    catalog.record_materialization(
        manifest.scene_id, status=manifest.status, manifest_path=str(path), assets=assets,
    )


def _download(
    client: httpx.Client, asset: SceneAsset, key: str, destination: Path, timeout: float,
) -> MaterializedAsset:
    """Publish only a completed, nonempty, size-checked HTTP 200 response."""
    temporary = None
    try:
        with client.stream(
            "GET", asset.href, timeout=timeout, follow_redirects=True,
            headers={"Accept-Encoding": "identity"},
        ) as response:
            if response.status_code != 200 or "Content-Range" in response.headers:
                raise MaterializationError(f"Asset {key}: expected a full HTTP 200 response, got {response.status_code}")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise MaterializationError(f"Asset {key}: unexpected Content-Encoding")
            content_length = response.headers.get("Content-Length")
            remote_size = None
            if content_length is not None:
                if not re.fullmatch(r"[0-9]+", content_length):
                    raise MaterializationError(f"Asset {key}: invalid Content-Length")
                remote_size = int(content_length)
                if asset.file_size is not None and remote_size != asset.file_size:
                    raise MaterializationError(f"Asset {key}: Content-Length differs from catalog file size")
            digest, size = hashlib.sha256(), 0
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=destination.name + ".", suffix=".part", delete=False) as stream:
                temporary = Path(stream.name)
                for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                    stream.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                    if any(expected is not None and size > expected for expected in (asset.file_size, remote_size)):
                        raise MaterializationError(f"Asset {key}: transfer exceeds expected file size")
                stream.flush()
                os.fsync(stream.fileno())
            if size == 0 or any(expected is not None and size != expected for expected in (asset.file_size, remote_size)):
                raise MaterializationError(f"Asset {key}: incomplete transfer or file size mismatch ({size} bytes)")
        os.replace(temporary, destination)
        return MaterializedAsset(
            asset_key=key, source_url=asset.href, local_path=destination.name,
            download_timestamp=datetime.now(UTC), file_size=size, sha256=digest.hexdigest(),
        )
    except httpx.HTTPError as exc:
        raise MaterializationError(f"Asset {key}: transfer failed ({type(exc).__name__})") from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def fetch_scene(
    catalog: LocalSceneCatalog,
    scene_id: str,
    raw_dir: str | Path = "data/raw",
    *,
    bands: Sequence[str] = MVP_BANDS,
    timeout: float = 60,
    client: httpx.Client | None = None,
) -> SceneManifest:
    """Materialize requested MVP bands for ONE existing scene (one writer).

    Verified files are reused without network requests. Interrupted transfers
    restart from scratch on the next call; partial files are never reused.
    A caller-supplied HTTPX client remains owned by the caller.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    requested = tuple(dict.fromkeys(bands))
    if not requested or any(band not in MVP_BANDS for band in requested):
        raise ValueError(f"bands must be a nonempty subset of {MVP_BANDS}")
    # Keep ordinary Sentinel-2 IDs in the requested directory layout. Reject
    # path components that could escape raw_dir instead of rewriting scene IDs.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", scene_id):
        raise ValueError("scene_id must be a safe filename component")
    scene = catalog.get_scene(scene_id)
    if scene is None:
        raise MaterializationError(f"Scene does not exist in local catalog: {scene_id}")
    selected = {band: _resolve_asset(scene, band) for band in requested}
    for key, asset in selected.values():
        parsed = urlsplit(asset.href)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise MaterializationError(f"Asset {key}: materialization requires an HTTP(S) URL")
    directory = Path(raw_dir).expanduser().resolve() / "sentinel2" / scene_id
    if directory.is_symlink() or directory.resolve() != directory:
        raise MaterializationError("Scene directory must not contain symbolic links")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    if path.is_symlink():
        raise MaterializationError("Manifest must not be a symbolic link")
    try:
        manifest = SceneManifest.model_validate_json(path.read_text()) if path.exists() else SceneManifest(scene_id=scene_id)
    except (ValueError, OSError) as exc:
        raise MaterializationError(f"Cannot read manifest: {path}") from exc
    if manifest.scene_id != scene_id:
        raise MaterializationError("Manifest belongs to a different scene")
    if any(band not in MVP_BANDS for band in manifest.assets):
        raise MaterializationError("Manifest contains an unsupported band")
    # Verify all recorded copies, including previously requested bands. Stale
    # records must not keep the catalog marked complete after local corruption.
    for band, record in list(manifest.assets.items()):
        try:
            key, asset = _resolve_asset(scene, band)
            valid = _verified(record, key, asset, directory / _filename(band, asset))
        except (MaterializationError, OSError):
            valid = False
        if not valid:
            del manifest.assets[band]
            manifest.failures[band] = FailedAsset(
                asset_key=record.asset_key, source_url=record.source_url,
                timestamp=datetime.now(UTC), error="Local integrity verification failed",
            )
    _sync(manifest, path, catalog)
    context = nullcontext(client) if client is not None else httpx.Client()
    with context as transport:
        for band, (key, asset) in selected.items():
            if band in manifest.assets:
                continue
            try:
                manifest.assets[band] = _download(transport, asset, key, directory / _filename(band, asset), timeout)
            except (MaterializationError, OSError) as exc:
                manifest.failures[band] = FailedAsset(
                    asset_key=key, source_url=asset.href, timestamp=datetime.now(UTC), error=str(exc),
                )
                _sync(manifest, path, catalog)
                raise MaterializationError(f"Could not materialize {scene_id} band {band}: {exc}") from exc
            manifest.failures.pop(band, None)
            _sync(manifest, path, catalog)
    return manifest
