"""Pure domain identifiers, acquisition records, coverage, and failures."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, TypeAlias

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
AcoliteProfileId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^acp-[0-9a-f]{16}$")]
DownstreamProfileId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^dsp-[0-9a-f]{16}$")]
RunKey: TypeAlias = Annotated[str, StringConstraints(pattern=r"^run-[0-9a-f]{16}$")]
RunAttemptId: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^att-\d{8}T\d{6}Z-[0-9a-f]{8}$")
]
PublicationProfileId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^pub-[0-9a-f]{16}$")]
ReleaseId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^rel-[0-9a-f]{16}$")]
Sha256: TypeAlias = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


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


def _content_id(prefix: str, value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"{prefix}-{sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


class AcolitePin(MetadataModel):
    release_tag: str = Field(pattern=r"^\d{8}\.\d+$")
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class AcoliteInstallation(MetadataModel):
    """Observed preflight state; never used as stable content identity."""

    root: str
    python_executable: str
    observed_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    config_version_line: str
    luts_present: set[str]
    credentials_present: bool
    free_disk_bytes: int = Field(ge=0)


class AncillaryTier(str, Enum):
    PROVISIONAL = "provisional"
    FINAL = "final"


class AcoliteParameterSet(MetadataModel):
    schema_version: str = "1.0"
    version: str = Field(min_length=1)
    parameters: tuple[str, ...] = Field(min_length=1)

    @field_validator("parameters")
    @classmethod
    def unique_parameters(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(not item.strip() for item in value):
            raise ValueError("parameters must be unique and nonblank")
        return value


class OwnedSettings(MetadataModel):
    """Only settings deliberately owned by OCEANOS, excluding attempt paths."""

    limit: tuple[float, float, float, float]
    merge_tiles: bool
    s2_target_res: Literal[10] = 10
    l2w_parameters: tuple[str, ...] = Field(min_length=1)
    l2w_mask_threshold: float = Field(default=0.05, ge=0, le=1)
    dsf_aot_estimate: Literal["fixed"] = "fixed"
    ancillary_type: Literal["GMAO_IT_MET", "GMAO_MERRA2_MET"]
    l1r_delete_netcdf: Literal[True] = True
    extract_inputfile: Literal[True] = True
    delete_extracted_input: Literal[True] = True
    rgb_rhot: Literal[False] = False
    rgb_rhos: Literal[False] = False
    dsf_residual_glint_correction: Literal[True] = True
    l2w_mask_water_parameters: Literal[False] = False
    netcdf_compression: Literal[True] = True

    @field_validator("limit")
    @classmethod
    def ordered_limit(cls, value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        south, west, north, east = value
        if north < south or east < west:
            raise ValueError("limit must be ordered south,west,north,east")
        return value

    @field_validator("l2w_parameters")
    @classmethod
    def unique_parameters(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("parameters must be unique")
        return value

    @field_validator("l2w_mask_threshold")
    @classmethod
    def fixed_mask_threshold(cls, value: float) -> float:
        if value != 0.05:
            raise ValueError("l2w_mask_threshold is fixed at 0.05")
        return value


class AcoliteProfile(MetadataModel):
    schema_version: str = "1.0"
    acolite: AcolitePin
    settings: OwnedSettings
    parameter_set_version: str = Field(min_length=1)
    grid_id: GridId
    ancillary_tier: AncillaryTier
    contract_version: str = Field(min_length=1)

    @property
    def profile_id(self) -> str:
        return _content_id("acp", self.model_dump(mode="json", exclude={"schema_version"}))


class DownstreamProfile(MetadataModel):
    schema_version: str = "1.0"
    product_set_version: str = Field(min_length=1)
    quality_policy_version: str = Field(min_length=1)
    land_mask_version: str = Field(min_length=1)
    analysis_mask_version: str = Field(min_length=1)
    publication_profile_version: str = Field(min_length=1)

    @property
    def profile_id(self) -> str:
        return _content_id("dsp", self.model_dump(mode="json", exclude={"schema_version"}))


def run_key(observation_id: str, input_set_id_value: str, profile_id: str) -> str:
    """Derive stable processing identity without attempt or machine state."""
    return _content_id("run", {
        "observation_id": observation_id,
        "input_set_id": input_set_id_value,
        "acolite_profile_id": profile_id,
    })


class ProductSpec(MetadataModel):
    product_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    acolite_parameter: str | None = None
    variable_pattern: str = Field(min_length=1)
    kind: Literal["continuous", "binary", "bitfield", "display"]
    unit: str | None
    masked_by_acolite: bool
    land_masked: bool
    shallow_exclusion_m: float | None = Field(default=None, ge=0)
    accepted_range: tuple[float, float] | None = None
    display_range: tuple[float, float] | None = None
    s2_calibrated: bool
    publish: Literal["archive_only", "cog"]
    caveat: str | None = None


class ProductSet(MetadataModel):
    schema_version: str = "1.0"
    version: str = Field(min_length=1)
    specs: tuple[ProductSpec, ...] = Field(min_length=1)

    @field_validator("specs")
    @classmethod
    def unique_product_keys(cls, value: tuple[ProductSpec, ...]) -> tuple[ProductSpec, ...]:
        keys = [spec.product_key for spec in value]
        if len(keys) != len(set(keys)):
            raise ValueError("product keys must be unique")
        return value


class RunState(str, Enum):
    PLANNED = "planned"
    PREFLIGHTED = "preflighted"
    EXECUTED = "executed"
    VERIFIED = "verified"
    ARCHIVED = "archived"
    CONFORMED = "conformed"
    ASSESSED = "assessed"
    PACKAGED = "packaged"
    PUBLISHED = "published"
    FAILED = "failed"
    ABANDONED = "abandoned"

    @property
    def terminal(self) -> bool:
        return self in {RunState.FAILED, RunState.ABANDONED, RunState.PUBLISHED}


class StageName(str, Enum):
    PLAN = "plan"
    PREFLIGHT = "preflight"
    EXECUTE = "execute"
    VERIFY = "verify"
    ARCHIVE = "archive"
    CONFORM = "conform"
    ASSESS = "assess"
    PACKAGE = "package"
    PUBLISH = "publish"
    RETAIN = "retain"


class StageResult(MetadataModel):
    stage: StageName
    status: Literal["ok", "failed"]
    started_at: AwareDatetime
    ended_at: AwareDatetime
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)


class RunAttempt(MetadataModel):
    schema_version: str = "1.0"
    attempt_id: RunAttemptId
    run_key: RunKey
    state: RunState
    host: str = Field(min_length=1)
    oceanos_version: str = Field(min_length=1)
    oceanos_git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    acolite_exit_code: int | None
    stages: list[StageResult]
    failure: FailureRecord | None


class FlagBit(MetadataModel):
    name: str = Field(min_length=1)
    bit: int = Field(ge=0)
    meaning: str = Field(min_length=1)
    source_setting: str = Field(min_length=1)


class FlagSpec(MetadataModel):
    bits: tuple[FlagBit, ...]
    usable_mask_value: int = Field(ge=0)


class AncillaryEvidence(MetadataModel):
    ancillary_type: str
    uoz: float
    uwv: float
    pressure: float
    wind: float
    fallback_detected: bool


class SunViewGeometry(MetadataModel):
    """Scene-mean solar/view angles in degrees, as recorded in the L2R attributes."""

    sza: float = Field(ge=0, le=90)
    vza: float = Field(ge=0, le=90)
    raa: float = Field(ge=-360, le=360)


class AerosolEvidence(MetadataModel):
    aot550: float
    aerosol_model: str
    dsf_fit_diagnostics: str


class AcoliteRunOutputs(MetadataModel):
    l2r: ArtifactRef
    l2w: ArtifactRef
    log: ArtifactRef
    settings_user: ArtifactRef
    settings_resolved: ArtifactRef
    acolite_version_attr: str
    aerosol: AerosolEvidence
    variables_present: tuple[str, ...]
    l2r_variables: tuple[str, ...]
    variable_units: dict[str, str | None]
    flag_spec: FlagSpec
    ancillary: AncillaryEvidence
    glint_angle_deg: float | None = None
    geometry: SunViewGeometry | None = None


class CoastlineSource(MetadataModel):
    dataset: str = Field(min_length=1)
    version: str = Field(min_length=1)
    sha256: Sha256


class LandMask(MetadataModel):
    """Grid-specific land raster (1 = land) derived once from OCEANOS coastline data."""

    schema_version: str = "1.0"
    grid_id: GridId
    version: str = Field(min_length=1)
    coastline_source: CoastlineSource
    raster: ArtifactRef
    land_pixels: int = Field(ge=0)


class LandMaskRef(MetadataModel):
    version: str = Field(min_length=1)
    sha256: Sha256


class LayerSource(MetadataModel):
    container_role: Literal["l2r", "l2w"]
    container_sha256: Sha256
    variable: str = Field(min_length=1)


class ConformedLayer(MetadataModel):
    """One product layer copied onto the delivery grid (P5)."""

    product_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["continuous", "binary", "bitfield", "display"]
    raster: ArtifactRef
    data_type: Literal["float32", "int32"]
    nodata: Literal["nan"] | None
    unit: str | None
    source: LayerSource
    grid_id: GridId
    method: Literal["copy"]
    grid_coverage_fraction: float = Field(ge=0, le=1)
    land_mask: LandMaskRef | None


class CogProfile(MetadataModel):
    compress: Literal["DEFLATE"] = "DEFLATE"
    predictor: Literal[2, 3]
    overview_resampling: Literal["AVERAGE", "MODE", "NEAREST"]
    blocksize: int = Field(default=256, ge=64, le=4096)
    data_type: Literal["float32", "int32", "uint8"]


class TrueColourSpec(MetadataModel):
    """Display-only RGB from L2R surface reflectance with one stretch for every date (T4)."""

    bands: tuple[str, str, str] = ("B04", "B03", "B02")
    stretch: tuple[float, float]
    gamma: float = Field(gt=0)

    @field_validator("stretch")
    @classmethod
    def ordered_stretch(cls, value: tuple[float, float]) -> tuple[float, float]:
        if not value[0] < value[1]:
            raise ValueError("stretch must be increasing")
        return value


class PublicationProfile(MetadataModel):
    schema_version: str = "1.0"
    version: str = Field(min_length=1)
    continuous: CogProfile
    bitfield: CogProfile
    published_products: tuple[str, ...] = Field(min_length=1)
    display: CogProfile | None = None
    true_colour: TrueColourSpec | None = None

    @property
    def profile_id(self) -> str:
        return _content_id("pub", self.model_dump(mode="json", exclude={"schema_version"}))


def release_id(attempt_id: str, downstream_profile_id: str) -> str:
    """Derive publication identity from one attempt and one downstream profile."""
    return _content_id("rel", {"attempt_id": attempt_id, "downstream_profile_id": downstream_profile_id})


class PublishedAsset(MetadataModel):
    product_key: str = Field(min_length=1)
    href: str = Field(min_length=1)
    sha256: Sha256
    size: int = Field(ge=0)
    media_type: str = Field(min_length=1)
    roles: tuple[str, ...] = Field(min_length=1)
    unit: str | None = None
    nodata: Literal["nan"] | None = None
    data_type: Literal["float32", "int32", "uint8"] | None = None
    overview_resampling: Literal["AVERAGE", "MODE", "NEAREST"] | None = None
    center_wavelength_nm: float | None = Field(default=None, gt=0)

    @field_validator("href")
    @classmethod
    def release_relative_href(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or len(path.parts) != 1:
            raise ValueError("asset href must be a file name inside the release directory")
        return value


class Release(MetadataModel):
    schema_version: str = "1.0"
    release_id: ReleaseId
    observation_id: str = Field(min_length=1)
    attempt_id: RunAttemptId
    run_key: RunKey
    downstream_profile_id: DownstreamProfileId
    tier: AncillaryTier
    visibility: Literal["public", "restricted"]
    assets: tuple[PublishedAsset, ...] = Field(min_length=1)
    quality: ArtifactRef | None
    provenance: ArtifactRef
    supersedes: ReleaseId | None
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class BathymetrySource(MetadataModel):
    dataset: str = Field(min_length=1)
    version: str = Field(min_length=1)
    sha256: Sha256


class AnalysisMask(MetadataModel):
    """Statistics-only mask per grid: coastal buffer plus per-product optically shallow cut (DA-3, B7)."""

    schema_version: str = "1.0"
    grid_id: GridId
    version: str = Field(min_length=1)
    coastal_buffer_m: float = Field(ge=0)
    coastline_source: CoastlineSource
    bathymetry_source: BathymetrySource
    coastal_buffer: ArtifactRef
    depth: ArtifactRef
    water_pixels: int = Field(ge=0)
    analysis_pixels: dict[str, int]
    shallow_exclusion_m: dict[str, float | None]


class AnalysisMaskRef(MetadataModel):
    version: str = Field(min_length=1)
    sha256: Sha256


class UsabilityVerdict(str, Enum):
    USABLE = "usable"
    UNUSABLE = "unusable"


class ProvenanceScene(MetadataModel):
    scene_id: SceneId
    source_id: str = Field(min_length=1)
    sha256: Sha256
    processing_baseline: str | None
    platform: str | None


class ProvenanceAcolite(MetadataModel):
    release_tag: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    version_attribute: str
    settings_user_sha256: Sha256
    settings_resolved_sha256: Sha256


class ProvenanceOceanos(MetadataModel):
    version: str = Field(min_length=1)
    git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    acolite_profile_id: AcoliteProfileId
    downstream_profile_id: DownstreamProfileId
    publication_profile_id: PublicationProfileId
    product_set_version: str = Field(min_length=1)
    quality_policy_version: str = Field(min_length=1)


class ProvenanceAncillary(MetadataModel):
    type: str
    tier: AncillaryTier
    uoz: float
    uwv: float
    pressure: float


class ProvenanceProduct(MetadataModel):
    product_key: str
    acolite_variable: str | tuple[str, ...]
    unit: str | None
    s2_calibrated: bool
    caveat: str | None
    source_sha256: Sha256
    grid_coverage_fraction: float = Field(ge=0, le=1)
    land_mask: LandMaskRef | None
    shallow_exclusion_m: float | None = None


class ProvenanceTimestamps(MetadataModel):
    acquired: AwareDatetime | None
    archived: AwareDatetime
    published: AwareDatetime


class ProvenanceRecord(MetadataModel):
    """Minimal self-contained lineage for one release (contracts §5)."""

    schema_version: str = "1.0"
    observation_id: str
    release_id: ReleaseId
    attempt_id: RunAttemptId
    run_key: RunKey
    scenes: tuple[ProvenanceScene, ...] = Field(min_length=1)
    acolite: ProvenanceAcolite
    oceanos: ProvenanceOceanos
    ancillary: ProvenanceAncillary
    glint_angle_deg: float | None
    products: tuple[ProvenanceProduct, ...] = Field(min_length=1)
    timestamps: ProvenanceTimestamps
    analysis_mask: AnalysisMaskRef | None = None
    quality_verdict: UsabilityVerdict | None = None
    derivations: tuple[str, ...] = ()
    scientific_label: str | None = None


class RangeRule(MetadataModel):
    product_key: str = Field(min_length=1)
    min: float
    max: float
    max_offending_fraction: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self) -> RangeRule:
        if not self.min < self.max:
            raise ValueError("range rule min must be below max")
        return self


class QualityPolicy(MetadataModel):
    """Versioned observation-usability policy (DA-2, amended by V8)."""

    schema_version: str = "1.0"
    version: str = Field(min_length=1)
    min_valid_fraction: float = Field(ge=0, le=1)
    min_grid_coverage: float = Field(ge=0, le=1)
    cloud_dilation_px: int = Field(ge=0, le=50)
    aot550_max: float = Field(gt=0)
    allowed_aerosol_models: tuple[str, ...] = Field(min_length=1)
    max_negative_rhos_fraction: float = Field(ge=0, le=1)
    max_residual_swir_rhow: float = Field(gt=0)
    range_rules: tuple[RangeRule, ...] = ()
    reject_on_ancillary_fallback: bool = True
    coastal_buffer_m: float = Field(ge=0)
    min_analysis_pixels: int = Field(ge=1)
    basis: dict[str, str] = Field(default_factory=dict)


class ObservationStatus(str, Enum):
    EXCLUDED_SCENE_CLOUD = "excluded_scene_cloud"
    INCOMPLETE_COVERAGE = "incomplete_coverage"
    PENDING = "pending"
    PROCESSING_FAILED = "processing_failed"
    NO_USABLE_OBSERVATION = "no_usable_observation"
    USABLE = "usable"


class FlagStatistics(MetadataModel):
    water_pixels: int = Field(ge=0)
    valid_pixels: int = Field(ge=0)
    per_bit_counts: dict[str, int]


class RangeViolation(MetadataModel):
    product_key: str
    rule: RangeRule
    offending_fraction: float = Field(ge=0, le=1)


class ProductQuality(MetadataModel):
    product_key: str
    analysis_pixels: int = Field(ge=0)
    valid_pixels: int = Field(ge=0)
    valid_fraction: float = Field(ge=0, le=1)
    gates_verdict: bool


class QualityReport(MetadataModel):
    schema_version: str = "1.0"
    observation_id: str = Field(min_length=1)
    attempt_id: RunAttemptId
    policy_version: str = Field(min_length=1)
    grid_coverage_fraction: float = Field(ge=0, le=1)
    flags: FlagStatistics
    products: tuple[ProductQuality, ...]
    negative_rhos_fraction: float = Field(ge=0, le=1)
    residual_swir_rhow_p90: float | None
    aot550: float
    aerosol_model: str
    glint_angle_deg: float | None
    range_violations: tuple[RangeViolation, ...]
    ancillary: AncillaryEvidence
    verdict: UsabilityVerdict
    status: ObservationStatus
    reasons: tuple[str, ...]


class SeriesStatistics(MetadataModel):
    valid_pixels: int = Field(ge=0)
    valid_fraction: float = Field(ge=0, le=1)
    mean: float
    median: float
    p10: float
    p90: float
    std: float


class SeriesPoint(MetadataModel):
    zone_id: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    datetime: AwareDatetime
    product_key: str = Field(min_length=1)
    unit: str | None
    status: ObservationStatus
    statistics: SeriesStatistics | None
    release_id: ReleaseId | None
    tier: AncillaryTier
