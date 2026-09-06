"""Pydantic models for project configuration."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, field_validator
from pyproj import CRS
from pyproj.exceptions import CRSError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


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
    raw_dir: Path
    intermediate_dir: Path
    products_dir: Path
    catalog_dir: Path
    default_crs: str
    aoi: AOISettings

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

    def resolve_paths(self, base_dir: Path) -> "OceanosSettings":
        """Return a copy whose paths are absolute and normalized.

        Args:
            base_dir: Base for a relative ``data_root``.
        """

        resolved_base = base_dir.expanduser().resolve()
        data_root = self._resolve(self.data_root, resolved_base)
        return self.model_copy(
            update={
                "data_root": data_root,
                "raw_dir": self._resolve(self.raw_dir, data_root),
                "intermediate_dir": self._resolve(self.intermediate_dir, data_root),
                "products_dir": self._resolve(self.products_dir, data_root),
                "catalog_dir": self._resolve(self.catalog_dir, data_root),
                "aoi": self.aoi.model_copy(
                    update={"path": self._resolve(self.aoi.path, resolved_base)}
                ),
            }
        )

    @staticmethod
    def _resolve(path: Path, parent: Path) -> Path:
        expanded = path.expanduser()
        return expanded.resolve() if expanded.is_absolute() else (parent / expanded).resolve()
