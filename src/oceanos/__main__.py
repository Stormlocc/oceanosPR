"""Command-line wiring for AOI, grid, CDSE discovery, SAFE acquisition and one-observation runs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path

from oceanos.aoi import AOIError, get_bounds, load_aoi, validate_aoi
from oceanos.catalog import (
    CdseODataProvider,
    LocalCatalogError,
    LocalSceneCatalog,
    SceneMetadata,
    SceneProviderError,
    SceneSearchResult,
)
from oceanos.config import (
    ConfigurationError,
    load_acolite_parameter_set,
    load_config,
    load_product_set,
)
from oceanos.ingestion import AcquisitionError, acquire_scene
from oceanos.ingestion.cdse_auth import CdseTokenClient
from oceanos.pipeline.plan import (
    SelectionError,
    build_input_set,
    group_overpasses,
    select_minimal_cover_with_scenes,
)
from oceanos.pipeline.run_one import (
    PipelineError,
    check_releases,
    latest_release_dir,
    run_one,
)
from oceanos.processing.grid import DeliveryGrid, build_delivery_grid
from oceanos.publishing import ReconcileError
from oceanos.storage import StorageLayout, WriterLockedError

L1C_COLLECTION = "sentinel-2-l1c"


def build_parser() -> argparse.ArgumentParser:
    """Build the command parser."""
    parser = argparse.ArgumentParser(
        prog="python -m oceanos",
        description="NASA OCEANOS Puerto Rico project CLI.",
    )
    commands = parser.add_subparsers(dest="command")

    aoi = commands.add_parser("aoi", help="Inspect configured Areas Of Interest")
    aoi_commands = aoi.add_subparsers(dest="aoi_command", required=True)
    info = aoi_commands.add_parser("info", help="Load, validate, and describe the AOI")
    info.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    info.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))

    grid = commands.add_parser("grid", help="Manage the AOI delivery grid")
    grid_commands = grid.add_subparsers(dest="grid_command", required=True)
    grid_build = grid_commands.add_parser("build", help="Build the stable AOI delivery grid")
    grid_build.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))

    scenes = commands.add_parser("scenes", help="Discover and acquire Sentinel-2 L1C scenes")
    scene_commands = scenes.add_subparsers(dest="scenes_command", required=True)
    search = scene_commands.add_parser("search", help="Discover L1C metadata through CDSE OData")
    search.add_argument("--start", required=True)
    search.add_argument("--end", required=True)
    search.add_argument("--cloud-cover-max", type=float)
    search.add_argument("--output", type=Path)
    search.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))
    search.add_argument("--catalog-dir", type=Path)

    acquire = scene_commands.add_parser("acquire", help="Acquire selected SAFE products for an overpass")
    acquire.add_argument("--overpass", required=True)
    acquire.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))
    acquire.add_argument("--catalog-dir", type=Path)
    acquire.add_argument("--raw-dir", type=Path)
    acquire.add_argument("--timeout", type=float, default=60)

    overpasses = scene_commands.add_parser("overpasses", help="List discovered local overpasses")
    overpasses.add_argument("--start", required=True)
    overpasses.add_argument("--end", required=True)
    overpasses.add_argument("--count", action="store_true")
    overpasses.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))
    overpasses.add_argument("--catalog-dir", type=Path)

    pipeline = commands.add_parser("pipeline", help="Process and publish observations")
    pipeline_commands = pipeline.add_subparsers(dest="pipeline_command", required=True)
    run = pipeline_commands.add_parser("run-one", help="Acquire, process and publish one overpass")
    run.add_argument("--overpass", required=True)
    run.add_argument("--force-reprocess", action="store_true")
    run.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))
    latest = pipeline_commands.add_parser("latest-release", help="Print the current release directory")
    latest.add_argument("--overpass", required=True)
    latest.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))

    catalog = commands.add_parser("catalog", help="Maintain the local scene catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    add = catalog_commands.add_parser("add")
    add.add_argument("scenes_file", type=Path)
    listing = catalog_commands.add_parser("list")
    for command in (add, listing):
        command.add_argument("--config", type=Path, default=Path("configs/mvp.yaml"))
        command.add_argument("--catalog-dir", type=Path)
    return parser


def _print_scenes(scenes: list[SceneMetadata]) -> None:
    rows = [["SCENE ID", "TILE", "PLATFORM", "DATETIME (UTC)", "CLOUD %", "ONLINE"]]
    for scene in scenes:
        rows.append([
            scene.scene_id, scene.mgrs_tile or "—", scene.platform or "—", scene.datetime.isoformat(),
            f"{scene.cloud_cover:.1f}" if scene.cloud_cover is not None else "—",
            "yes" if scene.online else "no",
        ])
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for index, row in enumerate(rows):
        print(" | ".join(value.ljust(width) for value, width in zip(row, widths)))
        if index == 0:
            print("-+-".join("-" * width for width in widths))
    print(f"{len(scenes)} scene(s) found." if scenes else "0 scenes found.")


def _dates(start: str, end: str) -> tuple[datetime, datetime]:
    try:
        lower = datetime.combine(date.fromisoformat(start), time.min, UTC) if len(start) == 10 else datetime.fromisoformat(start)
        upper = datetime.combine(date.fromisoformat(end), time.max, UTC) if len(end) == 10 else datetime.fromisoformat(end)
        if lower.tzinfo is None or upper.tzinfo is None or lower > upper:
            raise ValueError
        return lower.astimezone(UTC), upper.astimezone(UTC)
    except ValueError as exc:
        raise ValueError("start/end must be ordered ISO dates or timezone-aware datetimes") from exc


def _catalog(settings, override: Path | None) -> LocalSceneCatalog:
    return LocalSceneCatalog(override or settings.catalog_dir, collection_id=L1C_COLLECTION)


def _layout(settings) -> StorageLayout:
    storage = settings.storage
    return StorageLayout(
        raw=storage.raw, work=storage.work, archive=storage.archive, products=storage.products,
        superseded=storage.superseded, state=storage.state,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, call one domain operation, and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "aoi":
            settings = load_config(args.config)
            aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
            validate_aoi(aoi)
            if args.json:
                print(json.dumps({
                    "aoi_id": aoi.aoi_id, "name": aoi.name, "crs": aoi.crs.to_string(),
                    "bounds": list(get_bounds(aoi)), "geometry": aoi.to_geojson()["geometry"],
                    "validation": "valid",
                }, allow_nan=False))
            else:
                print(f"Name: {aoi.name}")
                print(f"AOI ID: {aoi.aoi_id}")
                print(f"CRS: {aoi.crs.to_string()}")
                print(f"Bounds: {get_bounds(aoi)}")
                print(f"Geometry type: {aoi.geometry.geom_type}")
                print("Validation: valid")
        elif args.command == "grid":
            settings = load_config(args.config)
            check_releases(settings)
            aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
            grid = build_delivery_grid(aoi)
            path = _layout(settings).grid_json(aoi.aoi_id)
            grid.save(path)
            print(f"Grid: {grid.grid_id}; {grid.spec.width} x {grid.spec.height}; {path}")
        elif args.command == "scenes" and args.scenes_command == "search":
            settings = load_config(args.config)
            check_releases(settings)
            aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
            discovery = settings.scenes
            provider = CdseODataProvider(
                discovery.catalogue_url, discovery.download_url, timeout=discovery.timeout,
                max_retries=discovery.max_retries, page_size=discovery.page_size,
            )
            scenes = provider.search(
                aoi, args.start, args.end,
                cloud_cover_max=args.cloud_cover_max if args.cloud_cover_max is not None else discovery.cloud_cover_max,
            )
            catalog = _catalog(settings, args.catalog_dir)
            for scene in scenes:
                catalog.add_scene(scene, source_provider="CdseODataProvider")
            if args.output is not None:
                SceneSearchResult(scenes=scenes).save(args.output)
            _print_scenes(scenes)
        elif args.command == "scenes" and args.scenes_command == "overpasses":
            settings = load_config(args.config)
            start, end = _dates(args.start, args.end)
            scenes = _catalog(settings, args.catalog_dir).search_local_catalog(
                start_datetime=start, end_datetime=end, collection=L1C_COLLECTION,
            )
            overpasses = tuple(group_overpasses(scenes))
            if args.count:
                print(len(overpasses))
            else:
                print("\n".join(overpasses))
        elif args.command == "scenes" and args.scenes_command == "acquire":
            settings = load_config(args.config)
            check_releases(settings)
            catalog = _catalog(settings, args.catalog_dir)
            groups = group_overpasses(catalog.search_local_catalog(collection=L1C_COLLECTION))
            if args.overpass not in groups:
                raise ValueError(f"overpass not found in local catalog: {args.overpass}")
            aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
            grid = DeliveryGrid.load(_layout(settings).grid_json(aoi.aoi_id))
            coverage, selected_scenes = select_minimal_cover_with_scenes(groups[args.overpass], grid)
            token = CdseTokenClient(settings.scenes.identity_url)
            raw_root = args.raw_dir or settings.storage.raw
            acquired = []
            for scene in selected_scenes:
                manifest = acquire_scene(
                    scene, raw_root, token_provider=token, catalog=catalog,
                    timeout=args.timeout, max_retries=settings.scenes.max_retries,
                )
                acquired.append(manifest.acquired)
                print(f"Acquired: {scene.scene_id}; {manifest.acquired.archive.relpath}")
            selected_input = build_input_set(args.overpass, acquired, coverage)
            print(f"Input set: {selected_input.input_set_id}; scenes: {len(selected_input.scenes)}")
        elif args.command == "pipeline" and args.pipeline_command == "run-one":
            settings = load_config(args.config)
            parameters = load_acolite_parameter_set(args.config.parent / "acolite_parameters.yaml")
            products = load_product_set(args.config.parent / "products.yaml", parameters)
            result = run_one(
                settings, args.overpass, parameters=parameters, products=products,
                force_reprocess=args.force_reprocess,
            )
            print(f"{result.status.capitalize()}: {result.release_id}; run key: {result.run_key}; {result.release_dir}")
        elif args.command == "pipeline" and args.pipeline_command == "latest-release":
            settings = load_config(args.config)
            print(latest_release_dir(settings, args.overpass))
        elif args.command == "catalog":
            settings = load_config(args.config)
            if args.catalog_command == "add":
                check_releases(settings)
            catalog = _catalog(settings, args.catalog_dir)
            if args.catalog_command == "add":
                result = SceneSearchResult.model_validate_json(args.scenes_file.read_text(encoding="utf-8"))
                inserted = sum(catalog.add_scene(scene) for scene in result.scenes)
                print(f"Added: {inserted}; already present: {len(result.scenes) - inserted}")
            else:
                _print_scenes(catalog.search_local_catalog())
    except (
        AcquisitionError, AOIError, ConfigurationError, LocalCatalogError, PipelineError, ReconcileError,
        SceneProviderError, SelectionError, WriterLockedError, OSError, ValueError,
    ) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
