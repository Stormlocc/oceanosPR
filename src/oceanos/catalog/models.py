"""Provider-independent scene metadata. Geometry and bbox always use WGS84 x/y."""

from __future__ import annotations

import json
from datetime import UTC
from datetime import datetime as DateTime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class MetadataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PolygonGeometry(MetadataModel):
    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]]


class MultiPolygonGeometry(MetadataModel):
    type: Literal["MultiPolygon"]
    coordinates: list[list[list[tuple[float, float]]]]


SceneGeometry = Annotated[PolygonGeometry | MultiPolygonGeometry, Field(discriminator="type")]


class SceneAsset(MetadataModel):
    """An available asset reference; discovery never fetches its contents."""

    href: str = Field(min_length=1)
    media_type: str | None = None
    title: str | None = None
    roles: list[str] = Field(default_factory=list)
    file_size: int | None = Field(default=None, ge=0)


class ProviderChecksums(MetadataModel):
    """Checksums published by CDSE; BLAKE3 is recorded but not verified."""

    md5: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{32}$")
    blake3: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class SceneMetadata(MetadataModel):
    scene_id: str = Field(min_length=1)
    collection: str = Field(min_length=1)
    platform: str | None = None
    datetime: AwareDatetime
    geometry: SceneGeometry
    bbox: tuple[float, float, float, float]
    cloud_cover: float | None = Field(default=None, ge=0, le=100)
    assets: dict[str, SceneAsset] = Field(default_factory=dict)
    source_catalog: str = Field(min_length=1)
    processing_level: str | None = None
    processing_baseline: str | None = None
    relative_orbit: int | None = Field(default=None, ge=0)
    datatake_id: str | None = None
    overpass_id: str | None = None
    mgrs_tile: str | None = None
    source_id: str | None = None
    checksums: ProviderChecksums | None = None
    online: bool | None = None

    @field_validator("datetime")
    @classmethod
    def utc_datetime(cls, value: DateTime) -> DateTime:
        return value.astimezone(UTC)


class SceneSearchResult(MetadataModel):
    """Versioned serialization contract for downstream consumers."""

    schema_version: Literal["1.0", "1.1"] = "1.1"
    scenes: list[SceneMetadata]

    def save(self, path: str | Path) -> None:
        """Save normalized metadata only, including an empty list for no matches."""
        Path(path).write_text(
            json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
