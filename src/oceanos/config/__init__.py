"""Typed configuration for OCEANOS."""

from oceanos.config.loader import ConfigurationError, load_config
from oceanos.config.models import OceanosSettings

__all__ = ["ConfigurationError", "OceanosSettings", "load_config"]

