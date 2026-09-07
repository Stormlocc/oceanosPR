"""Typed scene discovery without asset downloads."""

from oceanos.catalog.models import SceneAsset, SceneMetadata, SceneSearchResult
from oceanos.catalog.local import LocalCatalogError, LocalSceneCatalog, scene_from_stac_item, scene_to_stac_item
from oceanos.catalog.provider import SceneProvider, SceneProviderError
from oceanos.catalog.sentinel2 import Sentinel2Provider

__all__ = [
    "SceneAsset", "SceneMetadata", "SceneSearchResult", "SceneProvider",
    "SceneProviderError", "Sentinel2Provider", "LocalCatalogError",
    "LocalSceneCatalog", "scene_from_stac_item", "scene_to_stac_item",
]
