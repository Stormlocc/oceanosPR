"""Typed scene discovery without asset downloads."""

from oceanos.catalog.local import (
    LocalCatalogError,
    LocalSceneCatalog,
    scene_from_stac_item,
    scene_to_stac_item,
)
from oceanos.catalog.models import SceneAsset, SceneMetadata, SceneSearchResult
from oceanos.catalog.provider import SceneProvider, SceneProviderError
from oceanos.catalog.sentinel2 import Sentinel2Provider

__all__ = [
    "LocalCatalogError",
    "LocalSceneCatalog",
    "SceneAsset",
    "SceneMetadata",
    "SceneProvider",
    "SceneProviderError",
    "SceneSearchResult",
    "Sentinel2Provider",
    "scene_from_stac_item",
    "scene_to_stac_item",
]
