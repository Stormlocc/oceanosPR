#!/usr/bin/env python3
"""Trim the pinned real ACOLITE runs into the committed Phase 1 fixtures.

Run this with the ACOLITE micromamba interpreter.  The only non-stdlib Python
dependency is netCDF4; the environment's ``ogr2ogr`` executable clips the
coastline.  There is deliberately no import of ACOLITE itself.

GSHHG note: the ``gshhg_clip.geojson`` this writes is the **frozen Phase 1 record**
of how the fixture window was chosen, under the coastline source in force then.
The pipeline's land mask moved to CUDEM with the DA-1 amendment and GSHHG was
retired from production (PLAN, 2026-09-17), so the clip is provenance, not
behaviour: regenerating it needs a GSHHG archive supplied by hand via ``--gshhg``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

FIXTURE_SIZE = 256
DEFAULT_ROW = 341
DEFAULT_COLUMN = 251
COASTAL_BUFFER_M = 150
GSHHG_VERSION = "2.3.7"
GSHHG_ARCHIVE_SHA256 = "8dbbe7e071e77e9e75f2d639239099ebca8d5c16d6a07df8169729d49f15cf41"
SPATIAL_VARIABLES = frozenset({"transverse_mercator", "x", "y", "lon", "lat"})
L2W_VARIANT_VARIABLES = SPATIAL_VARIABLES | {"l2_flags"}


def _spacing(values: Sequence[float]) -> float:
    if len(values) < 2:
        raise ValueError("a spatial coordinate needs at least two values")
    return float(values[1] - values[0])


def _updated_spatial_attributes(
    attrs: dict[str, Any],
    *,
    x: Sequence[float],
    y: Sequence[float],
    lon: Any,
    lat: Any,
    row: int,
    column: int,
) -> dict[str, Any]:
    """Return global attributes made coherent with a cropped spatial window."""
    width = len(x)
    height = len(y)
    if width != FIXTURE_SIZE or height != FIXTURE_SIZE:
        raise ValueError(f"fixture window must be {FIXTURE_SIZE}x{FIXTURE_SIZE}")

    x_spacing = _spacing(x)
    y_spacing = _spacing(y)
    updated = dict(attrs)
    updated["global_dims"] = [height, width]
    updated["data_dimensions"] = [height, width]
    updated["data_elements"] = height * width
    if "sub" in attrs:
        source_sub = attrs["sub"]
        updated["sub"] = [
            int(source_sub[0]) + column,
            int(source_sub[1]) + row,
            width,
            height,
        ]
    updated["xrange"] = [float(x[0] - x_spacing / 2), float(x[-1] + x_spacing / 2)]
    updated["yrange"] = [float(y[0] - y_spacing / 2), float(y[-1] + y_spacing / 2)]
    updated["limit"] = [
        float(lat.min()),
        float(lon.min()),
        float(lat.max()),
        float(lon.max()),
    ]
    return updated


def _find_one(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected one {pattern!r} in {directory}, found {len(matches)}")
    return matches[0]


def _variable_slices(dimensions: Sequence[str], *, row: int, column: int, size: int) -> tuple[Any, ...]:
    slices: list[Any] = []
    for dimension in dimensions:
        if dimension == "y":
            slices.append(slice(row, row + size))
        elif dimension == "x":
            slices.append(slice(column, column + size))
        else:
            slices.append(slice(None))
    return tuple(slices)


def _include_variable(
    name: str,
    included: frozenset[str] | None,
    dropped_prefixes: tuple[str, ...],
    included_prefixes: tuple[str, ...] = (),
) -> bool:
    lowered = name.lower()
    if any(lowered.startswith(prefix.lower()) for prefix in dropped_prefixes):
        return False
    return included is None or name in included or any(
        lowered.startswith(prefix.lower()) for prefix in included_prefixes
    )


def _crop_netcdf(
    source_path: Path,
    destination_path: Path,
    *,
    row: int,
    column: int,
    size: int,
    drop_prefixes: tuple[str, ...] = (),
    include_variables: frozenset[str] | None = None,
    include_prefixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    # Deferred on purpose: the offline suite imports this module without netCDF4,
    # which only exists in the ACOLITE interpreter this script runs under.
    from netCDF4 import Dataset  # noqa: PLC0415  # type: ignore[import-not-found]

    with Dataset(source_path) as source:
        if row < 0 or column < 0 or row + size > len(source.dimensions["y"]) or column + size > len(source.dimensions["x"]):
            raise ValueError(f"crop {row=}, {column=}, {size=} is outside {source_path}")

        x = source.variables["x"][column : column + size]
        y = source.variables["y"][row : row + size]
        lon = source.variables["lon"][row : row + size, column : column + size]
        lat = source.variables["lat"][row : row + size, column : column + size]
        attrs = {name: source.getncattr(name) for name in source.ncattrs()}
        attrs = _updated_spatial_attributes(
            attrs,
            x=x,
            y=y,
            lon=lon,
            lat=lat,
            row=row,
            column=column,
        )

        with Dataset(destination_path, "w", format="NETCDF4") as destination:
            for name, dimension in source.dimensions.items():
                length = size if name in {"x", "y"} else len(dimension)
                destination.createDimension(name, None if dimension.isunlimited() else length)
            destination.setncatts(attrs)

            for name, variable in source.variables.items():
                if not _include_variable(name, include_variables, drop_prefixes, include_prefixes):
                    continue
                fill_value = variable.getncattr("_FillValue") if "_FillValue" in variable.ncattrs() else None
                options: dict[str, Any] = {}
                if variable.ndim:
                    options.update(zlib=True, complevel=9, shuffle=True)
                if fill_value is not None:
                    options["fill_value"] = fill_value
                output = destination.createVariable(name, variable.datatype, variable.dimensions, **options)
                output.setncatts(
                    {attribute: variable.getncattr(attribute) for attribute in variable.ncattrs() if attribute != "_FillValue"}
                )
                slices = _variable_slices(variable.dimensions, row=row, column=column, size=size)
                output[...] = variable[slices]

    return {
        "projected_bounds": {
            "west": attrs["xrange"][0],
            "south": attrs["yrange"][1],
            "east": attrs["xrange"][1],
            "north": attrs["yrange"][0],
        },
        "geographic_limit": {
            "south": attrs["limit"][0],
            "west": attrs["limit"][1],
            "north": attrs["limit"][2],
            "east": attrs["limit"][3],
        },
        "pixel_size": [float(_spacing(x)), float(_spacing(y))],
        "crs": "EPSG:32619",
    }


def _copy_run_evidence(source: Path, destination: Path, *, resolved_required: bool = True) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    patterns = ["*_log_file.txt", "*_l1r_settings_user.txt"]
    if resolved_required:
        patterns.append("*_l2r_settings.txt")
    for pattern in patterns:
        evidence = _find_one(source, pattern)
        shutil.copy2(evidence, destination / evidence.name)


def _environment_executable(name: str, *, python_executable: Path | None = None) -> Path:
    sibling = (python_executable or Path(sys.executable)).with_name(name)
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return sibling
    discovered = shutil.which(name)
    if discovered is not None:
        return Path(discovered)
    raise RuntimeError(f"{name} is required from the ACOLITE environment")


def _crop_run(
    source: Path,
    destination: Path,
    *,
    row: int,
    column: int,
    size: int,
    l2r: bool = True,
    l2w: bool = True,
    drop_l2w_prefixes: tuple[str, ...] = (),
    l2r_variables: frozenset[str] | None = None,
    l2w_variables: frozenset[str] | None = None,
    l2w_prefixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {}
    if l2r:
        source_l2r = _find_one(source, "*_L2R.nc")
        metadata = _crop_netcdf(
            source_l2r,
            destination / source_l2r.name,
            row=row,
            column=column,
            size=size,
            include_variables=l2r_variables,
        )
    if l2w:
        source_l2w = _find_one(source, "*_L2W.nc")
        l2w_metadata = _crop_netcdf(
            source_l2w,
            destination / source_l2w.name,
            row=row,
            column=column,
            size=size,
            drop_prefixes=drop_l2w_prefixes,
            include_variables=l2w_variables,
            include_prefixes=l2w_prefixes,
        )
        metadata = metadata or l2w_metadata
    _copy_run_evidence(source, destination)
    return metadata


def _write_gshhg_clip(source: Path, destination: Path, projected_bounds: dict[str, float]) -> None:
    """Write the coastline needed to reproduce the fixture's 150 m buffer."""
    ogr2ogr = _environment_executable("ogr2ogr")
    clip_bounds = {
        "west": projected_bounds["west"] - COASTAL_BUFFER_M,
        "south": projected_bounds["south"] - COASTAL_BUFFER_M,
        "east": projected_bounds["east"] + COASTAL_BUFFER_M,
        "north": projected_bounds["north"] + COASTAL_BUFFER_M,
    }
    with tempfile.TemporaryDirectory(prefix=".gshhg-clip-", dir=destination.parent) as temporary:
        projected = Path(temporary) / "gshhg_projected.geojson"
        subprocess.run(
            [
                str(ogr2ogr),
                "-f",
                "GeoJSON",
                str(projected),
                str(source),
                "-spat",
                str(clip_bounds["west"]),
                str(clip_bounds["south"]),
                str(clip_bounds["east"]),
                str(clip_bounds["north"]),
                "-spat_srs",
                "EPSG:32619",
                "-t_srs",
                "EPSG:32619",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                str(ogr2ogr),
                "-f",
                "GeoJSON",
                str(destination),
                str(projected),
                "-clipsrc",
                str(clip_bounds["west"]),
                str(clip_bounds["south"]),
                str(clip_bounds["east"]),
                str(clip_bounds["north"]),
                "-t_srs",
                "EPSG:4326",
                "-lco",
                "RFC7946=YES",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    document = json.loads(destination.read_text(encoding="utf-8"))
    if not document.get("features"):
        raise ValueError("the selected window produced an empty GSHHG clip")
    document["oceanos_provenance"] = {
        "dataset": "GSHHG full-resolution level-1 land polygons",
        "version": GSHHG_VERSION,
        "archive_sha256": GSHHG_ARCHIVE_SHA256,
        "selection_buffer_m": COASTAL_BUFFER_M,
    }
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-f", type=Path, required=True)
    parser.add_argument("--run-b2", type=Path, required=True)
    parser.add_argument("--run-d2", type=Path, required=True)
    parser.add_argument("--run-e", type=Path, required=True)
    parser.add_argument("--gshhg", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--row", type=int, default=DEFAULT_ROW)
    parser.add_argument("--column", type=int, default=DEFAULT_COLUMN)
    parser.add_argument("--size", type=int, default=FIXTURE_SIZE)
    parser.add_argument("--land-pixels", type=int, default=3434)
    parser.add_argument("--coastal-buffer-pixels", type=int, default=8352)
    parser.add_argument("--water-outside-buffer-pixels", type=int, default=53750)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.size != FIXTURE_SIZE:
        raise ValueError(f"the approved fixture size is exactly {FIXTURE_SIZE}")
    if args.land_pixels <= 0 or args.coastal_buffer_pixels <= 0:
        raise ValueError("the fixture must contain land and the 150 m coastal buffer")
    if args.water_outside_buffer_pixels < 20000:
        raise ValueError("the fixture needs at least 20,000 water pixels outside the coastal buffer")
    if args.output.exists():
        raise FileExistsError(f"refusing to replace existing fixture directory: {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".acolite-fixtures-", dir=args.output.parent) as temporary:
        staging = Path(temporary) / args.output.name
        success_metadata = _crop_run(
            args.run_f,
            staging / "success",
            row=args.row,
            column=args.column,
            size=args.size,
        )
        _crop_run(
            args.run_b2,
            staging / "ancillary_fallback",
            row=args.row,
            column=args.column,
            size=args.size,
            l2r_variables=SPATIAL_VARIABLES,
            l2w_variables=L2W_VARIANT_VARIABLES,
            l2w_prefixes=("tur_nechad2016",),
        )
        _crop_run(
            args.run_f,
            staging / "missing_variable",
            row=args.row,
            column=args.column,
            size=args.size,
            l2r_variables=SPATIAL_VARIABLES,
            l2w_variables=L2W_VARIANT_VARIABLES,
            drop_l2w_prefixes=("tur_nechad2016",),
        )
        _crop_run(
            args.run_d2,
            staging / "cloudy",
            row=args.row,
            column=args.column,
            size=args.size,
            l2r_variables=SPATIAL_VARIABLES,
            l2w_variables=L2W_VARIANT_VARIABLES,
            l2w_prefixes=("tur_nechad2016",),
        )
        _copy_run_evidence(args.run_e, staging / "skipped", resolved_required=False)
        _write_gshhg_clip(args.gshhg, staging / "gshhg_clip.geojson", success_metadata["projected_bounds"])

        window = {
            "schema_version": 1,
            "source_run": "F",
            "row_offset": args.row,
            "column_offset": args.column,
            "width": args.size,
            "height": args.size,
            **success_metadata,
            "geometric_counts": {
                "land_pixels": args.land_pixels,
                "coastal_buffer_150m_pixels": args.coastal_buffer_pixels,
                "water_outside_buffer_pixels": args.water_outside_buffer_pixels,
            },
        }
        (staging / "window.json").write_text(json.dumps(window, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        shutil.move(staging, args.output)

    print(f"Wrote ACOLITE fixtures to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
