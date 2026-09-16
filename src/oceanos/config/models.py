"""Pydantic models for project configuration."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pyproj import CRS
from pyproj.exceptions import CRSError


class AOISettings(BaseModel):
    """Replaceable AOI input; path is relative to the project base directory."""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: Path
    target_crs: str

    @field_validator("name", "target_crs")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()

    @field_validator("path", mode="before")
    @classmethod
    def nonblank_path(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("path must not be blank")
        return value

    @field_validator("target_crs")
    @classmethod
    def valid_crs(cls, value: str) -> str:
        try:
            crs = CRS.from_user_input(value)
        except CRSError as exc:
            raise ValueError(f"Invalid AOI target CRS: {value}") from exc
        if not (crs.is_geographic or crs.is_projected) or len(crs.axis_info) != 2:
            raise ValueError("AOI target CRS must be two-dimensional and geographic or projected")
        return crs.to_string()


class SceneSearchSettings(BaseModel):
    """Fixed CDSE L1C discovery and acquisition endpoints."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    provider: Literal["cdse"] = "cdse"
    catalogue_url: str = "https://catalogue.dataspace.copernicus.eu/odata/v1"
    download_url: str = "https://download.dataspace.copernicus.eu/odata/v1"
    identity_url: str = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
    cloud_cover_max: float | None = Field(default=None, ge=0, le=100)
    timeout: float = Field(default=30, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)
    page_size: int = Field(default=100, ge=1, le=10000)

    @field_validator("catalogue_url", "download_url", "identity_url")
    @classmethod
    def http_root(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("endpoint must be an HTTP(S) root URL without query or fragment")
        return value.rstrip("/")


class StorageSettings(BaseModel):
    """Tier roots relative to data_root and retention policy values."""

    model_config = ConfigDict(extra="forbid")

    raw: Path = Path("raw")
    work: Path = Path("work")
    archive: Path = Path("archive")
    products: Path = Path("products")
    superseded: Path = Path("superseded")
    state: Path = Path("state")
    failed_workspace_retention_days: int = Field(default=14, ge=0)
    superseded_releases_to_keep: int = Field(default=1, ge=0)


class AcoliteSettings(BaseModel):
    """Pinned local subprocess installation and runtime limit."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    python_executable: Path
    launcher: Path
    root: Path
    release_tag: str = Field(pattern=r"^\d{8}\.\d+$")
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    luts_dir: Path
    external_dir: Path
    timeout_seconds: int = Field(gt=0)

    @field_validator("python_executable", "launcher", "root", "luts_dir", "external_dir", mode="before")
    @classmethod
    def nonblank_path(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("path must not be blank")
        return value


class OceanosSettings(BaseSettings):
    """Validated settings shared by OCEANOS components.

    Relative component directories are interpreted relative to ``data_root`` by
    :meth:`resolve_paths`. Loading settings has no filesystem side effects.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="OCEANOS_",
        case_sensitive=False,
        extra="forbid",
        env_nested_delimiter="__",
    )

    project_name: str
    data_root: Path
    catalog_dir: Path
    default_crs: str
    aoi: AOISettings
    scenes: SceneSearchSettings = Field(default_factory=SceneSearchSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    acolite: AcoliteSettings

    @field_validator("project_name", "default_crs")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        """Reject blank identifiers that would make provenance ambiguous."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Give explicit environment variables precedence over YAML values."""

        del settings_cls
        return env_settings, init_settings, dotenv_settings, file_secret_settings

    def resolve_paths(self, base_dir: Path) -> OceanosSettings:
        """Return a copy whose paths are absolute and normalized.

        Args:
            base_dir: Base for a relative ``data_root``.
        """

        resolved_base = base_dir.expanduser().resolve()
        data_root = self._resolve(self.data_root, resolved_base)
        return self.model_copy(
            update={
                "data_root": data_root,
                "catalog_dir": self._resolve(self.catalog_dir, data_root),
                "storage": self.storage.model_copy(update={
                    field: self._resolve(getattr(self.storage, field), data_root)
                    for field in ("raw", "work", "archive", "products", "superseded", "state")
                }),
                "acolite": self.acolite.model_copy(update={
                    "root": self._resolve(self.acolite.root, resolved_base),
                    "python_executable": self._resolve(self.acolite.python_executable, resolved_base),
                    "launcher": self._resolve(
                        self.acolite.launcher,
                        self._resolve(self.acolite.root, resolved_base),
                    ),
                    "luts_dir": self._resolve(self.acolite.luts_dir, resolved_base),
                    "external_dir": self._resolve(self.acolite.external_dir, resolved_base),
                }),
                "aoi": self.aoi.model_copy(
                    update={"path": self._resolve(self.aoi.path, resolved_base)}
                ),
            }
        )

    @staticmethod
    def _resolve(path: Path, parent: Path) -> Path:
        expanded = path.expanduser()
        return expanded.resolve() if expanded.is_absolute() else (parent / expanded).resolve()
