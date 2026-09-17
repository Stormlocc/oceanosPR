"""Portable, local PySTAC scene catalog. No asset or remote metadata downloads."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import pystac
from pystac.extensions.eo import EOExtension
from pystac.extensions.file import FileExtension
from pystac.layout import HrefLayoutStrategy
from shapely.geometry import shape

from oceanos.aoi import AOI
from oceanos.catalog.models import ProviderChecksums, SceneAsset, SceneMetadata


class LocalCatalogError(RuntimeError):
    """The local catalog is unreadable, inconsistent, or cannot be saved."""


def _tier_relpath(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or value in {"", "."}:
        raise ValueError("catalog artifact paths must be relative to their tier root")
    return path.as_posix()


class _LocalIO(pystac.StacIO):
    """Only local JSON, with atomic replacement of individual documents."""

    def _path(self, href: Any) -> Path:
        value = href.get_absolute_href() if isinstance(href, pystac.Link) else str(href)
        if value is None:
            raise LocalCatalogError("Local catalog links must resolve to a path")
        if urlsplit(value).scheme:
            raise LocalCatalogError(f"Local catalog links must refer to local files: {value}")
        return Path(value)

    def read_text(self, source: Any, *args: Any, **kwargs: Any) -> str:
        return self._path(source).read_text(encoding="utf-8")

    def write_text(self, dest: Any, txt: str, *args: Any, **kwargs: Any) -> None:
        path = self._path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(txt + "\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()


class _Layout(HrefLayoutStrategy):
    """Stable filenames independent of insertion order, safe for arbitrary IDs."""

    def get_catalog_href(self, cat: pystac.Catalog, parent_dir: str, is_root: bool) -> str:
        return str(Path(parent_dir) / "catalog.json")

    def get_collection_href(self, col: pystac.Collection, parent_dir: str, is_root: bool) -> str:
        key = sha256(col.id.encode("utf-8")).hexdigest()
        return str(Path(parent_dir) / "collections" / key / "collection.json")

    def get_item_href(self, item: pystac.Item, parent_dir: str) -> str:
        key = sha256(item.id.encode("utf-8")).hexdigest()
        return str(Path(parent_dir) / "items" / f"{key}.json")


def scene_to_stac_item(
    scene: SceneMetadata,
    *,
    source_provider: str = "CdseODataProvider",
    ingested_at: datetime | None = None,
) -> pystac.Item:
    """Copy scientific metadata verbatim; add local provenance separately."""
    registered = ingested_at if ingested_at is not None else datetime.now(UTC)
    if registered.tzinfo is None or registered.utcoffset() is None:
        raise ValueError("ingested_at must include a timezone")
    if not source_provider.strip():
        raise ValueError("source_provider must not be blank")
    item = pystac.Item(
        id=scene.scene_id,
        geometry=scene.geometry.model_dump(mode="json"),
        bbox=list(scene.bbox),
        datetime=scene.datetime,
        collection=scene.collection,
        properties={
            "oceanos:source_catalog": scene.source_catalog,
            "oceanos:original_scene_id": scene.scene_id,
            "oceanos:source_provider": source_provider,
            "oceanos:ingested_at": registered.astimezone(UTC).isoformat(),
            "oceanos:processing_status": "discovered",
        },
    )
    if scene.platform is not None:
        item.properties["platform"] = scene.platform
    if scene.cloud_cover is not None:
        EOExtension.ext(item, add_if_missing=True).cloud_cover = scene.cloud_cover
    optional_properties = {
        "oceanos:processing_level": scene.processing_level,
        "oceanos:processing_baseline": scene.processing_baseline,
        "sat:relative_orbit": scene.relative_orbit,
        "oceanos:datatake_id": scene.datatake_id,
        "oceanos:overpass_id": scene.overpass_id,
        "s2:mgrs_tile": scene.mgrs_tile,
        "oceanos:source_id": scene.source_id,
        "oceanos:provider_checksums": (
            scene.checksums.model_dump(mode="json") if scene.checksums is not None else None
        ),
        "oceanos:online": scene.online,
    }
    item.properties.update({key: value for key, value in optional_properties.items() if value is not None})
    for key, asset in scene.assets.items():
        item.add_asset(key, pystac.Asset(
            href=asset.href, media_type=asset.media_type, title=asset.title,
            roles=list(asset.roles),
        ))
        if asset.file_size is not None:
            FileExtension.ext(item.assets[key], add_if_missing=True).size = asset.file_size
    return item


def scene_from_stac_item(item: pystac.Item) -> SceneMetadata:
    """Reconstruct the Phase 2 model from a persisted OCEANOS STAC Item."""
    try:
        if item.properties["oceanos:original_scene_id"] != item.id:
            raise ValueError("original_scene_id differs from the STAC Item ID")
        if item.collection_id is None or item.datetime is None or item.geometry is None or item.bbox is None:
            raise ValueError("STAC Item lacks a collection, datetime, geometry or bbox")
        return SceneMetadata(
            scene_id=item.id,
            collection=item.collection_id,
            platform=item.properties.get("platform"),
            datetime=item.datetime,
            # Validated into the discriminated union by pydantic at construction.
            geometry=item.geometry,  # type: ignore[arg-type]
            bbox=(item.bbox[0], item.bbox[1], item.bbox[2], item.bbox[3]),
            cloud_cover=item.properties.get("eo:cloud_cover"),
            source_catalog=item.properties["oceanos:source_catalog"],
            processing_level=item.properties.get("oceanos:processing_level"),
            processing_baseline=item.properties.get("oceanos:processing_baseline"),
            relative_orbit=item.properties.get("sat:relative_orbit"),
            datatake_id=item.properties.get("oceanos:datatake_id"),
            overpass_id=item.properties.get("oceanos:overpass_id"),
            mgrs_tile=item.properties.get("s2:mgrs_tile"),
            source_id=item.properties.get("oceanos:source_id"),
            checksums=(
                ProviderChecksums.model_validate(item.properties["oceanos:provider_checksums"])
                if "oceanos:provider_checksums" in item.properties else None
            ),
            online=item.properties.get("oceanos:online"),
            assets={key: SceneAsset(
                href=asset.href, media_type=asset.media_type, title=asset.title,
                roles=asset.roles or [],
                file_size=asset.extra_fields.get("file:size"),
            ) for key, asset in item.assets.items()},
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LocalCatalogError(f"Cannot reconstruct scene from STAC Item {item.id}: {exc}") from exc


def _collection(collection_id: str) -> pystac.Collection:
    # Unknown extent until the first scene, then replaced with actual item extents.
    return pystac.Collection(
        id=collection_id,
        title=f"OCEANOS Sentinel-2 — {collection_id}",
        description="Local index of discovered Sentinel-2 scene metadata and remote asset references.",
        extent=pystac.Extent(
            pystac.SpatialExtent([[-180.0, -90.0, 180.0, 90.0]]),
            # An unbounded interval is how STAC spells "extent not yet known".
            pystac.TemporalExtent([[None, None]]),  # type: ignore[arg-type]
        ),
        license="other",
        extra_fields={"oceanos:extent_status": "empty"},
    )


class LocalSceneCatalog:
    """Persist scenes under a STAC root, retaining original Collection IDs.

    Mutations are intended for one writer at a time. Each operation reloads
    the catalog so successive instances see each other's completed changes.
    Duplicate IDs with identical metadata are no-ops; conflicts raise an error.
    """

    def __init__(self, directory: str | Path = "catalog", *, collection_id: str = "sentinel-2-l1c") -> None:
        self.directory = Path(directory).expanduser().resolve()
        self.path = self.directory / "catalog.json"
        self._io = _LocalIO()
        if self.path.exists():
            self._load()
        else:
            if not collection_id.strip():
                raise ValueError("collection_id must not be blank")
            catalog = pystac.Catalog(
                id="oceanos", title="OCEANOS local scene catalog",
                description="Reproducible local catalog of discovered scenes. Assets remain remote.",
                catalog_type=pystac.CatalogType.SELF_CONTAINED,
            )
            catalog.add_child(_collection(collection_id))
            self._save(catalog)

    def _load(self) -> pystac.Catalog:
        try:
            catalog = pystac.Catalog.from_file(str(self.path), stac_io=self._io)
            if isinstance(catalog, pystac.Collection) or catalog.id != "oceanos":
                raise ValueError("Expected an OCEANOS root Catalog")
            # Resolve local links now so a broken file never looks like an empty catalog.
            list(catalog.get_items(recursive=True))
            return catalog
        except (OSError, ValueError, TypeError, KeyError, pystac.STACError) as exc:
            raise LocalCatalogError(f"Cannot load local catalog {self.path}: {exc}") from exc

    def _save(self, catalog: pystac.Catalog) -> None:
        try:
            catalog.normalize_hrefs(str(self.directory), strategy=_Layout())
            catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED, stac_io=self._io)
        except (OSError, ValueError, pystac.STACError) as exc:
            raise LocalCatalogError(f"Cannot save local catalog {self.path}: {exc}") from exc

    def add_scene(self, scene: SceneMetadata, *, source_provider: str = "CdseODataProvider") -> bool:
        """Persist one scene; True if inserted, False if already identical."""
        catalog = self._load()
        existing = next(catalog.get_items(scene.scene_id, recursive=True), None)
        if existing is not None:
            if scene_from_stac_item(existing) != scene:
                raise LocalCatalogError(f"Scene ID {scene.scene_id!r} already exists with different metadata")
            return False
        item = scene_to_stac_item(scene, source_provider=source_provider)
        collection = catalog.get_child(scene.collection)
        if collection is None:
            collection = _collection(scene.collection)
            catalog.add_child(collection)
        if not isinstance(collection, pystac.Collection):
            raise LocalCatalogError(f"Expected a Collection for {scene.collection}")
        collection.add_item(item)
        collection.update_extent_from_items()
        collection.extra_fields["oceanos:extent_status"] = "from_scenes"
        self._save(catalog)
        return True

    def scene_exists(self, scene_id: str) -> bool:
        return self.get_stac_item(scene_id) is not None

    def record_acquisition(
        self, scene_id: str, *, manifest_relpath: str, archive_relpath: str,
        file_size: int, sha256: str, provider_md5: str,
    ) -> None:
        """Synchronize a verified whole-SAFE acquisition onto its scene Item."""
        manifest_relpath = _tier_relpath(manifest_relpath)
        archive_relpath = _tier_relpath(archive_relpath)
        catalog = self._load()
        item = next(catalog.get_items(scene_id, recursive=True), None)
        if item is None:
            raise LocalCatalogError(f"Scene does not exist: {scene_id}")
        if "product" not in item.assets:
            raise LocalCatalogError(f"Scene has no product asset: {scene_id}")
        item.properties.update({
            "oceanos:materialization_status": "complete",
            "oceanos:processing_status": "acquired",
            "oceanos:manifest_path": manifest_relpath,
            "oceanos:retained": True,
            "oceanos:sha256": sha256,
            "oceanos:provider_md5": provider_md5,
        })
        asset = item.assets["product"]
        asset.extra_fields.update({
            "oceanos:local_path": archive_relpath,
            "oceanos:file_size": file_size,
            "oceanos:sha256": sha256,
        })
        self._save(catalog)

    def get_stac_item(self, scene_id: str) -> pystac.Item | None:
        """Return a detached item; mutating it does not update the catalog."""
        item = next(self._load().get_items(scene_id, recursive=True), None)
        return item.clone() if item is not None else None

    def get_scene(self, scene_id: str) -> SceneMetadata | None:
        item = self.get_stac_item(scene_id)
        return scene_from_stac_item(item) if item is not None else None

    def search_local_catalog(
        self,
        *,
        aoi: AOI | None = None,
        start_datetime: datetime | None = None,
        end_datetime: datetime | None = None,
        collection: str | None = None,
        platform: str | None = None,
        cloud_cover_max: float | None = None,
    ) -> list[SceneMetadata]:
        """Search local metadata, with inclusive aware-datetime bounds.

        No filters returns all scenes, sorted by ID. Unknown cloud cover is
        excluded when a maximum is supplied. AOIs may use any supported CRS.
        """
        for value in (start_datetime, end_datetime):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("Local search datetimes must include a timezone")
        if start_datetime is not None and end_datetime is not None and start_datetime > end_datetime:
            raise ValueError("start_datetime must be before or equal to end_datetime")
        if cloud_cover_max is not None and not 0 <= cloud_cover_max <= 100:
            raise ValueError("cloud_cover_max must be between 0 and 100")
        footprint = shape(aoi.to_geojson()["geometry"]) if aoi is not None else None
        matches = []
        for item in self._load().get_items(recursive=True):
            scene = scene_from_stac_item(item)
            if collection is not None and scene.collection != collection:
                continue
            if platform is not None and scene.platform != platform:
                continue
            if start_datetime is not None and scene.datetime < start_datetime:
                continue
            if end_datetime is not None and scene.datetime > end_datetime:
                continue
            if cloud_cover_max is not None and (scene.cloud_cover is None or scene.cloud_cover > cloud_cover_max):
                continue
            if footprint is not None and not shape(item.geometry).intersects(footprint):
                continue
            matches.append(scene)
        return sorted(matches, key=lambda scene: scene.scene_id)
