"""Stable discovery interface, independent of any remote catalog format."""

from abc import ABC, abstractmethod
from datetime import datetime

from oceanos.aoi import AOI
from oceanos.catalog.models import SceneMetadata


class SceneProviderError(RuntimeError):
    """Discovery failed; callers must not treat partial results as complete."""


class SceneProvider(ABC):
    @abstractmethod
    def search(
        self,
        aoi: AOI,
        start_datetime: datetime | str,
        end_datetime: datetime | str,
        collection: str,
        cloud_cover_max: float | None = None,
    ) -> list[SceneMetadata]:
        """Discover scenes, without downloading assets.

        Date-only strings include the whole UTC day at each end. Datetimes
        require a timezone. The interval is inclusive; duplicates use the first
        occurrence of each scene_id. Missing optional metadata remains unknown.
        """
