"""Load OCEANOS settings from YAML and environment variables."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from oceanos.config.models import OceanosSettings

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Raised when a configuration file cannot be loaded or validated."""


def load_config(config_path: str | Path, *, base_dir: str | Path | None = None) -> OceanosSettings:
    """Load, validate, and resolve a YAML configuration.

    Environment variables prefixed with ``OCEANOS_`` override YAML fields. If
    ``base_dir`` is omitted, the parent of the configuration directory is used.
    No directories are created by this function.

    Raises:
        ConfigurationError: If the file is absent, malformed, or invalid.
    """

    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {path}")

    try:
        with path.open("r", encoding="utf-8") as stream:
            raw_values: Any = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read configuration file: {path}") from exc

    if not isinstance(raw_values, dict):
        raise ConfigurationError(f"Configuration must contain a YAML mapping: {path}")

    try:
        settings = OceanosSettings(**raw_values)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration in {path}: {exc}") from exc

    root = Path(base_dir).expanduser().resolve() if base_dir is not None else path.parent.parent
    resolved = settings.resolve_paths(root)
    logger.info(
        "configuration_loaded",
        extra={
            "config_path": str(path),
            "project_name": resolved.project_name,
            "data_root": str(resolved.data_root),
        },
    )
    return resolved

