"""Typed scene discovery without asset downloads."""

from oceanos.catalog.cdse import L1C_COLLECTION, CdseODataProvider
from oceanos.catalog.local import (
    LocalCatalogError,
    LocalSceneCatalog,
    scene_from_stac_item,
    scene_to_stac_item,
)
from oceanos.catalog.models import (
    ProviderChecksums,
    SceneAsset,
    SceneMetadata,
    SceneSearchResult,
)
from oceanos.catalog.provider import SceneProvider, SceneProviderError

__all__ = [
    "L1C_COLLECTION",
    "CdseODataProvider",
    "LocalCatalogError",
    "LocalSceneCatalog",
    "ProviderChecksums",
    "SceneAsset",
    "SceneMetadata",
    "SceneProvider",
    "SceneProviderError",
    "SceneSearchResult",
    "scene_from_stac_item",
    "scene_to_stac_item",
]
