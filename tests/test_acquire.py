"""Whole-SAFE acquisition is tested with synthetic ZIP streams."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest
from shapely.geometry import box, mapping

from oceanos.catalog import (
    LocalSceneCatalog,
    ProviderChecksums,
    SceneAsset,
    SceneMetadata,
)
from oceanos.catalog.local import LocalCatalogError
from oceanos.ingestion import AcquisitionError, SceneManifest, acquire_scene
from oceanos.ingestion.cdse_auth import CdseTokenClient

BANDS = ("B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B10", "B11", "B12")


def safe_zip(*, granules: int = 1, omit: str | None = None) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        members = ["SCENE.SAFE/MTD_MSIL1C.xml"]
        for index in range(granules):
            root = f"SCENE.SAFE/GRANULE/G{index}"
            members.extend([f"{root}/MTD_TL.xml", *(f"{root}/IMG_DATA/T_BAND_{band}.jp2" for band in BANDS), f"{root}/QI_DATA/MSK_DETFOO_B01.jp2"])
        for member in members:
            if member != omit:
                archive.writestr(member, b"x")
    return stream.getvalue()


def scene(payload: bytes, *, online: bool = True, md5: str | None = None) -> SceneMetadata:
    digest = hashlib.md5(payload, usedforsecurity=False).hexdigest() if md5 is None else md5
    return SceneMetadata(
        scene_id="S2A_MSIL1C_20260702T150741_N0512_R082_T19QGV_X", collection="sentinel-2-l1c",
        platform="S2A", datetime="2026-07-02T15:07:41Z", geometry=mapping(box(-67.2, 17.8, -66.8, 18.2)),
        bbox=(-67.2, 17.8, -66.8, 18.2), source_catalog="https://catalogue.example", processing_level="Level-1C",
        relative_orbit=82, datatake_id="GS2A_20260702T150741_057594_N05.12", overpass_id="S2A_20260702T150741_R082",
        mgrs_tile="19QGV", source_id="uuid", online=online, checksums=ProviderChecksums(md5=digest, blake3="b" * 64),
        assets={"product": SceneAsset(href="https://download.example/Products(uuid)/$value", media_type="application/zip", file_size=len(payload))},
    )


def acquire(tmp_path: Path, source: SceneMetadata, payload: bytes):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=payload, headers={"Content-Length": str(len(payload))})

    catalog = LocalSceneCatalog(tmp_path / "catalog", collection_id="sentinel-2-l1c")
    catalog.add_scene(source, source_provider="CdseODataProvider")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = acquire_scene(source, tmp_path / "raw", catalog=catalog, token_provider=lambda: "secret-token", client=client)
    return result, calls, catalog


def test_whole_safe_is_verified_and_atomically_published(tmp_path: Path) -> None:
    payload = safe_zip()
    result, calls, catalog = acquire(tmp_path, scene(payload), payload)
    assert result.acquired is not None
    assert result.status == "complete"
    assert result.acquired.provider_md5_verified is True
    assert result.acquired.safe_members_verified is True
    assert result.acquired.archive.sha256 == hashlib.sha256(payload).hexdigest()
    archive = tmp_path / "raw" / result.acquired.archive.relpath
    assert archive.read_bytes() == payload
    assert not list(archive.parent.glob("*.part"))
    persisted = SceneManifest.model_validate_json((archive.parent / "manifest.json").read_text(encoding="utf-8"))
    assert persisted == result
    assert calls[0].headers["Authorization"] == "Bearer secret-token"
    item = catalog.get_stac_item(result.scene_id)
    assert item.properties["oceanos:retained"] is True
    assert item.properties["oceanos:sha256"] == result.acquired.archive.sha256


def test_acquisition_catalog_paths_survive_raw_tier_relocation(tmp_path: Path) -> None:
    payload = safe_zip()
    result, _, catalog = acquire(tmp_path, scene(payload), payload)
    item = catalog.get_stac_item(result.scene_id)
    assert item is not None
    manifest_relpath = item.properties["oceanos:manifest_path"]
    archive_relpath = item.assets["product"].extra_fields["oceanos:local_path"]
    assert manifest_relpath == str(Path(result.acquired.archive.relpath).parent / "manifest.json")
    assert archive_relpath == result.acquired.archive.relpath
    assert not Path(manifest_relpath).is_absolute()
    assert not Path(archive_relpath).is_absolute()

    relocated_raw = tmp_path / "relocated" / "raw"
    relocated_raw.parent.mkdir()
    (tmp_path / "raw").rename(relocated_raw)
    reloaded = LocalSceneCatalog(tmp_path / "catalog", collection_id="sentinel-2-l1c").get_stac_item(result.scene_id)
    assert reloaded is not None
    assert (relocated_raw / reloaded.properties["oceanos:manifest_path"]).is_file()
    assert (relocated_raw / reloaded.assets["product"].extra_fields["oceanos:local_path"]).read_bytes() == payload


def test_cached_safe_recovers_catalog_after_prior_sync_failure(monkeypatch, tmp_path: Path) -> None:
    payload = safe_zip()
    source = scene(payload)
    catalog = LocalSceneCatalog(tmp_path / "catalog", collection_id="sentinel-2-l1c")
    catalog.add_scene(source, source_provider="CdseODataProvider")
    real_record = catalog.record_acquisition

    def failed_sync(*args, **kwargs) -> None:
        raise LocalCatalogError("injected catalog failure")

    monkeypatch.setattr(catalog, "record_acquisition", failed_sync)
    response = lambda _: httpx.Response(200, content=payload, headers={"Content-Length": str(len(payload))})
    with (
        httpx.Client(transport=httpx.MockTransport(response)) as client,
        pytest.raises(LocalCatalogError, match="injected catalog failure"),
    ):
        acquire_scene(source, tmp_path / "raw", catalog=catalog, token_provider=lambda: "token", client=client)

    monkeypatch.setattr(catalog, "record_acquisition", real_record)

    def unexpected_request(_: httpx.Request) -> httpx.Response:
        pytest.fail("a verified cached SAFE must not be downloaded again")

    with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
        recovered = acquire_scene(
            source, tmp_path / "raw", catalog=catalog,
            token_provider=lambda: pytest.fail("cached acquisition must not request a token"), client=client,
        )
    item = catalog.get_stac_item(source.scene_id)
    assert item is not None
    assert item.properties["oceanos:processing_status"] == "acquired"
    assert item.properties["oceanos:sha256"] == recovered.acquired.archive.sha256
    assert item.assets["product"].extra_fields["oceanos:local_path"] == recovered.acquired.archive.relpath


@pytest.mark.parametrize(
    ("source_factory", "payload_factory", "code"),
    [
        (lambda data: scene(data, md5="0" * 32), lambda data: data, "input.md5_mismatch"),
        (lambda data: scene(data), lambda data: safe_zip(omit="SCENE.SAFE/GRANULE/G0/MTD_TL.xml"), "input.safe_members_missing"),
        (lambda data: scene(data), lambda data: safe_zip(granules=2), "input.safe_members_missing"),
    ],
)
def test_invalid_download_is_never_published(tmp_path: Path, source_factory, payload_factory, code: str) -> None:
    valid = safe_zip()
    transferred = payload_factory(valid)
    source = source_factory(valid) if code == "input.md5_mismatch" else scene(transferred)
    with pytest.raises(AcquisitionError, match=code):
        acquire(tmp_path, source, transferred)
    assert not list((tmp_path / "raw").rglob("*.zip"))
    assert not list((tmp_path / "raw").rglob("*.part"))


def test_offline_product_never_requests_download(tmp_path: Path) -> None:
    payload = safe_zip()
    with pytest.raises(AcquisitionError, match="input.product_offline"):
        acquire_scene(scene(payload, online=False), tmp_path / "raw", token_provider=lambda: pytest.fail("no token"))


def test_refetch_sha_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = safe_zip()
    source = scene(payload)
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=payload, headers={"Content-Length": str(len(payload))}))) as client,
        pytest.raises(AcquisitionError, match="input.refetch_mismatch"),
    ):
        acquire_scene(source, tmp_path / "raw", token_provider=lambda: "token", client=client, expected_sha256="0" * 64)


def test_token_is_reused_then_refreshed_below_300_seconds(monkeypatch, tmp_path: Path) -> None:
    credentials = tmp_path / ".netrc"
    credentials.write_text("machine cdse login user password pass\n", encoding="utf-8")
    credentials.chmod(0o600)
    now = [0.0]
    monkeypatch.setattr("oceanos.ingestion.cdse_auth.time.monotonic", lambda: now[0])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path.endswith("/protocol/openid-connect/token")
        assert b"client_id=cdse-public" in request.content
        assert b"grant_type=password" in request.content
        return httpx.Response(200, json={"access_token": f"token-{len(calls)}", "expires_in": 600})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        tokens = CdseTokenClient("https://identity.example/realm", netrc_path=credentials, client=client)
        assert tokens() == "token-1"
        now[0] = 300
        assert tokens() == "token-1"
        now[0] = 301
        assert tokens() == "token-2"
    assert len(calls) == 2


def test_partial_range_response_is_rejected(tmp_path: Path) -> None:
    payload = safe_zip()
    source = scene(payload)
    response = lambda _: httpx.Response(206, content=payload, headers={
        "Content-Length": str(len(payload)), "Content-Range": f"bytes 0-{len(payload) - 1}/{len(payload)}",
    })
    with (
        httpx.Client(transport=httpx.MockTransport(response)) as client,
        pytest.raises(AcquisitionError, match="requires HTTP 200"),
    ):
        acquire_scene(source, tmp_path / "raw", token_provider=lambda: "token", client=client)
    assert not list((tmp_path / "raw").rglob("*.zip"))
