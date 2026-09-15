"""Pure domain identifiers, acquisition records, coverage, and failures."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated, Any, TypeAlias

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from shapely.geometry import shape  # type: ignore[import-untyped]


class MetadataModel(BaseModel):
    """Base for strict finite persisted metadata."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


SafeComponent = StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
SceneId: TypeAlias = Annotated[str, SafeComponent]
OverpassId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^S2[ABC]_\d{8}T\d{6}_R\d{3}$")]
AoiId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^aoi-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{12}$")]
GridId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^grid-[0-9a-f]{12}$")]
InputSetId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^inp-[0-9a-f]{16}$")]


def validate_scene_id(value: str) -> str:
    """Validate a provider scene id before it participates in a path."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value) is None:
        raise ValueError("scene_id must be a safe filename component")
    return value


class FailureCode(str, Enum):
    """Complete failure taxonomy from the acquisition/processing contract."""

    INCOMPLETE_TILE_SET = "input.incomplete_tile_set"
    PRODUCT_OFFLINE = "input.product_offline"
    MD5_MISMATCH = "input.md5_mismatch"
    SAFE_MEMBERS_MISSING = "input.safe_members_missing"
    AUTH_FAILED = "input.auth_failed"
    MIXED_OVERPASS = "input.mixed_overpass"
    NOT_L1C = "input.not_l1c"
    CHECKSUM_MISMATCH = "input.checksum_mismatch"
    ACOLITE_COMMIT_MISMATCH = "env.acolite_commit_mismatch"
    ACOLITE_VERSION_LINE_MISSING = "env.acolite_version_line_missing"
    LUTS_MISSING = "env.luts_missing"
    GSHHG_MISSING = "env.gshhg_missing"
    CREDENTIALS_MISSING = "env.credentials_missing"
    DISK_INSUFFICIENT = "env.disk_insufficient"
    ACOLITE_TIMEOUT = "acolite.timeout"
    ACOLITE_NONZERO_EXIT = "acolite.nonzero_exit"
    ACOLITE_SKIPPED = "acolite.skipped"
    ACOLITE_MISSING_OUTPUT = "acolite.missing_output"
    ACOLITE_MISSING_VARIABLE = "acolite.missing_variable"
    ACOLITE_ANCILLARY_FALLBACK = "acolite.ancillary_fallback"
    ACOLITE_VERSION_ATTR_MISMATCH = "acolite.version_attr_mismatch"
    GRID_MISALIGNED = "grid.misaligned"
    GRID_NO_INTERSECTION = "grid.no_intersection"
    PUBLISH_IO_ERROR = "publish.io_error"
    INTERNAL_ABANDONED = "internal.abandoned"
    INTERNAL_WRITER_LOCKED = "internal.writer_locked"
    REFETCH_MISMATCH = "input.refetch_mismatch"
    INTERNAL_UNEXPECTED = "internal.unexpected"


class FailureScope(str, Enum):
    OBSERVATION = "observation"
    BATCH = "batch"


class FailureRecord(MetadataModel):
    schema_version: str = "1.0"
    code: FailureCode
    scope: FailureScope
    stage: str = Field(min_length=1)
    message: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    retryable: bool
    occurred_at: AwareDatetime

    @field_validator("occurred_at")
    @classmethod
    def utc_datetime(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class ArtifactRef(MetadataModel):
    role: str = Field(min_length=1)
    relpath: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    media_type: str = Field(min_length=1)

    @field_validator("relpath")
    @classmethod
    def relative_portable_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value or value in {"", "."}:
            raise ValueError("artifact paths must be relative to their tier root")
        return path.as_posix()


class AcquiredScene(MetadataModel):
    scene_id: SceneId
    source_id: str = Field(min_length=1)
    archive: ArtifactRef
    provider_md5_verified: bool
    safe_members_verified: bool
    verified_at: AwareDatetime

    @field_validator("verified_at")
    @classmethod
    def utc_datetime(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class TileCandidate(MetadataModel):
    scene_id: SceneId
    mgrs_tile: str = Field(pattern=r"^\d{2}[A-Z]{3}$")
    footprint: dict[str, Any]
    cloud_cover: float | None = Field(default=None, ge=0, le=100)
    aoi_fraction: float = Field(ge=0, le=1)

    @field_validator("footprint")
    @classmethod
    def valid_polygon(cls, value: dict[str, Any]) -> dict[str, Any]:
        geometry = shape(value)
        if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid:
            raise ValueError("footprint must be a valid polygon in EPSG:4326")
        return value


class TileCoverage(MetadataModel):
    candidates: tuple[TileCandidate, ...]
    selected: tuple[str, ...]
    selected_scene_ids: tuple[SceneId, ...]
    covers_grid: bool

    @model_validator(mode="after")
    def selected_candidates_exist(self) -> TileCoverage:
        tiles = {candidate.mgrs_tile for candidate in self.candidates}
        scene_ids = [candidate.scene_id for candidate in self.candidates]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("coverage candidate scene identities must be unique")
        if (
            self.selected != tuple(sorted(self.selected))
            or len(self.selected) != len(set(self.selected))
            or not set(self.selected) <= tiles
        ):
            raise ValueError("selected tiles must be unique candidates")
        selected_scene_ids = tuple(sorted(self.selected_scene_ids))
        candidates = {candidate.scene_id: candidate for candidate in self.candidates}
        if (
            self.selected_scene_ids != selected_scene_ids
            or len(self.selected_scene_ids) != len(set(self.selected_scene_ids))
            or any(scene_id not in candidates for scene_id in self.selected_scene_ids)
            or tuple(sorted(candidates[scene_id].mgrs_tile for scene_id in self.selected_scene_ids)) != self.selected
        ):
            raise ValueError("selected scene identities must exactly represent selected tiles")
        return self


def input_set_id(scenes: tuple[AcquiredScene, ...]) -> str:
    """Derive content identity from sorted scene ids and SAFE SHA-256 values."""
    pairs = sorted((scene.scene_id, scene.archive.sha256) for scene in scenes)
    canonical = json.dumps(pairs, separators=(",", ":"), ensure_ascii=True)
    return f"inp-{sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


class InputSet(MetadataModel):
    schema_version: str = "1.0"
    input_set_id: InputSetId
    overpass_id: OverpassId
    scenes: tuple[AcquiredScene, ...]
    coverage: TileCoverage
    discovery_cloud_cover: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def valid_complete_set(self) -> InputSet:
        if not self.coverage.covers_grid:
            raise ValueError("input.incomplete_tile_set")
        if tuple(scene.scene_id for scene in self.scenes) != tuple(sorted(scene.scene_id for scene in self.scenes)):
            raise ValueError("InputSet scenes must be sorted by scene_id")
        if tuple(scene.scene_id for scene in self.scenes) != self.coverage.selected_scene_ids:
            raise ValueError("InputSet selected acquired scenes must equal A1 winning scene identities")
        candidates = {candidate.scene_id: candidate for candidate in self.coverage.candidates}
        selected_tiles: list[str] = []
        for scene in self.scenes:
            candidate = candidates.get(scene.scene_id)
            if candidate is None or candidate.mgrs_tile not in self.coverage.selected:
                raise ValueError("InputSet must contain exactly the selected acquired scenes")
            selected_tiles.append(candidate.mgrs_tile)
            if not scene.provider_md5_verified or not scene.safe_members_verified:
                raise ValueError("InputSet scenes must be acquired and verified")
            match = re.match(
                r"^(S2[ABC])_MSIL1C_(\d{8}T\d{6})_.*_R(\d{3})_T\d{2}[A-Z]{3}(?:_|$)",
                scene.scene_id,
            )
            scene_overpass = f"{match.group(1)}_{match.group(2)}_R{match.group(3)}" if match else None
            if scene_overpass != self.overpass_id:
                raise ValueError("InputSet scenes must share the same overpass")
        if tuple(sorted(selected_tiles)) != self.coverage.selected:
            raise ValueError("InputSet must contain exactly the selected acquired scenes")
        if self.input_set_id != input_set_id(self.scenes):
            raise ValueError("InputSetId does not match its acquired scenes")
        return self
