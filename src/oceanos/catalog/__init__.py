"""Typed scene discovery without asset downloads."""

from oceanos.catalog.cdse import CdseODataProvider
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
