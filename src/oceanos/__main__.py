"""Command-line entry point for ``python -m oceanos``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from oceanos.aoi import AOIError, get_bounds, load_aoi, validate_aoi
from oceanos.catalog import SceneMetadata, SceneProviderError, SceneSearchResult, Sentinel2Provider
from oceanos.config import ConfigurationError, load_config


def build_parser() -> argparse.ArgumentParser:
    """Build the minimal OCEANOS command-line parser."""

    parser = argparse.ArgumentParser(
        prog="python -m oceanos",
        description=(
            "NASA OCEANOS Puerto Rico project CLI. "
            "Configurable Areas Of Interest and Sentinel-2 scene discovery."
        ),
    )
    commands = parser.add_subparsers(dest="command")
    aoi = commands.add_parser("aoi", help="Inspect configured Areas Of Interest")
    aoi_commands = aoi.add_subparsers(dest="aoi_command", required=True)
    info = aoi_commands.add_parser("info", help="Load, validate, and describe the AOI")
    info.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))
    scenes = commands.add_parser("scenes", help="Discover scenes without downloading imagery")
    scene_commands = scenes.add_subparsers(dest="scenes_command", required=True)
    search = scene_commands.add_parser("search", help="Search Sentinel-2 STAC metadata")
    search.add_argument("--start", required=True, help="YYYY-MM-DD or ISO datetime with timezone")
    search.add_argument("--end", required=True, help="YYYY-MM-DD (whole UTC day included) or ISO datetime")
    search.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))
    search.add_argument("--collection", help="Override the configured STAC collection")
    search.add_argument("--cloud-cover-max", type=float, help="Maximum scene cloud percentage (0–100)")
    search.add_argument("--output", type=Path, help="Write normalized scene metadata as JSON")
    return parser


def _print_scenes(scenes: list[SceneMetadata]) -> None:
    rows = [["SCENE ID", "COLLECTION", "PLATFORM", "DATETIME (UTC)", "CLOUD %", "ASSETS"]]
    for scene in scenes:
        rows.append([
            scene.scene_id, scene.collection, scene.platform or "—",
            scene.datetime.isoformat(),
            f"{scene.cloud_cover:.1f}" if scene.cloud_cover is not None else "—",
            str(len(scene.assets)),
        ])
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for index, row in enumerate(rows):
        print(" | ".join(value.ljust(width) for value, width in zip(row, widths)))
        if index == 0:
            print("-+-".join("-" * width for width in widths))
    print(f"{len(scenes)} scene(s) found." if scenes else "0 scenes found.")


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
    elif args.command == "scenes":
        try:
            settings = load_config(args.config)
            aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
            discovery = settings.scenes
            provider = Sentinel2Provider(
                discovery.catalog_url, timeout=discovery.timeout,
                max_retries=discovery.max_retries, page_size=discovery.page_size,
            )
            scenes = provider.search(
                aoi, args.start, args.end,
                args.collection if args.collection is not None else discovery.collection,
                args.cloud_cover_max if args.cloud_cover_max is not None else discovery.cloud_cover_max,
            )
            if args.output is not None:
                SceneSearchResult(scenes=scenes).save(args.output)
        except (ConfigurationError, SceneProviderError, ValueError, OSError) as exc:
            parser.exit(1, f"Error: {exc}\n")
        _print_scenes(scenes)
        if args.output is not None:
            print(f"Normalized metadata saved to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
