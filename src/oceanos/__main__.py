"""Command-line entry point for ``python -m oceanos``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from oceanos.aoi import AOIError, get_bounds, load_aoi, validate_aoi
from oceanos.config import ConfigurationError, load_config


def build_parser() -> argparse.ArgumentParser:
    """Build the minimal OCEANOS command-line parser."""

    parser = argparse.ArgumentParser(
        prog="python -m oceanos",
        description=(
            "NASA OCEANOS Puerto Rico project CLI. "
            "Configurable Areas Of Interest."
        ),
    )
    commands = parser.add_subparsers(dest="command")
    aoi = commands.add_parser("aoi", help="Inspect configured Areas Of Interest")
    aoi_commands = aoi.add_subparsers(dest="aoi_command", required=True)
    info = aoi_commands.add_parser("info", help="Load, validate, and describe the AOI")
    info.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "aoi":
        try:
            settings = load_config(args.config).aoi
            aoi = load_aoi(settings.path, name=settings.name, target_crs=settings.target_crs)
            validate_aoi(aoi)
        except (ConfigurationError, AOIError) as exc:
            parser.exit(1, f"Validation: invalid\nError: {exc}\n")
        print(f"Name: {aoi.name}")
        print(f"CRS: {aoi.crs.to_string()}")
        print(f"Bounds: {get_bounds(aoi)}")
        print(f"Geometry type: {aoi.geometry.geom_type}")
        print("Validation: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
