"""Load OCEANOS settings from YAML and environment variables."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from oceanos.config.models import OceanosSettings
from oceanos.domain import (
    AcoliteParameterSet,
    ProductSet,
    PublicationProfile,
    QualityPolicy,
)

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


def _load_yaml_mapping(path_value: str | Path) -> tuple[Path, dict[str, Any]]:
    path = Path(path_value).expanduser().resolve()
    try:
        with path.open("r", encoding="utf-8") as stream:
            values: Any = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read configuration file: {path}") from exc
    if not isinstance(values, dict):
        raise ConfigurationError(f"Configuration must contain a YAML mapping: {path}")
    return path, values


def load_acolite_parameter_set(path: str | Path) -> AcoliteParameterSet:
    """Load the sole versioned source for rendered processing parameters."""
    resolved, values = _load_yaml_mapping(path)
    try:
        return AcoliteParameterSet.model_validate(values)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration in {resolved}: {exc}") from exc


def load_product_set(path: str | Path, parameters: AcoliteParameterSet) -> ProductSet:
    """Load selected publication products and validate their processing source."""
    resolved, values = _load_yaml_mapping(path)
    try:
        products = ProductSet.model_validate(values)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration in {resolved}: {exc}") from exc
    allowed = set(parameters.parameters)
    outside = sorted({
        spec.acolite_parameter for spec in products.specs
        if spec.acolite_parameter is not None and spec.acolite_parameter not in allowed
    })
    if outside:
        raise ConfigurationError(
            f"ProductSpec acolite_parameter outside AcoliteParameterSet: {outside}"
        )
    return products


def load_quality_policy(path: str | Path, products: ProductSet) -> QualityPolicy:
    """Load the versioned quality policy; every range rule must name a known product."""
    resolved, values = _load_yaml_mapping(path)
    try:
        policy = QualityPolicy.model_validate(values)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration in {resolved}: {exc}") from exc
    known = {spec.product_key for spec in products.specs}
    unknown = sorted({rule.product_key for rule in policy.range_rules} - known)
    if unknown:
        raise ConfigurationError(f"QualityPolicy range rules name unknown products: {unknown}")
    return policy


def load_publication_profile(path: str | Path, products: ProductSet) -> PublicationProfile:
    """Load the publication profile; published products must be COG specs of the product set."""
    resolved, values = _load_yaml_mapping(path)
    try:
        profile = PublicationProfile.model_validate(values)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration in {resolved}: {exc}") from exc
    cog = {spec.product_key for spec in products.specs if spec.publish == "cog"}
    outside = sorted(set(profile.published_products) - cog)
    if outside:
        raise ConfigurationError(f"PublicationProfile publishes products that are not COG specs: {outside}")
    if "true_colour" in profile.published_products and (profile.true_colour is None or profile.display is None):
        raise ConfigurationError("PublicationProfile publishes true_colour without a true_colour spec and display COG profile")
    return profile
