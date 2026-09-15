"""Minimal settings rendering for the pinned ACOLITE CLI."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol

from pyproj import CRS, Transformer

from oceanos.domain import OwnedSettings


class _GridSpec(Protocol):
    @property
    def crs(self) -> object: ...
    @property
    def resolution(self) -> float: ...
    @property
    def bounds(self) -> tuple[float, float, float, float]: ...


class _DeliveryGrid(Protocol):
    @property
    def spec(self) -> _GridSpec: ...


def _format(value: object) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, tuple):
        return ",".join(_format(item) for item in value)
    return str(value)


def limit_for_grid(grid: _DeliveryGrid) -> tuple[float, float, float, float]:
    """Return S,W,N,E: delivery grid bounds in EPSG:4326, expanded outward by one pixel."""
    west, south, east, north = grid.spec.bounds
    pixel = grid.spec.resolution
    transformer = Transformer.from_crs(CRS.from_user_input(grid.spec.crs), "EPSG:4326", always_xy=True)
    lon_west, lat_south, lon_east, lat_north = transformer.transform_bounds(
        west - pixel, south - pixel, east + pixel, north + pixel, densify_pts=21,
    )
    return (lat_south, lon_west, lat_north, lon_east)


class SettingsRenderer:
    """Render only owned settings and per-attempt paths."""

    def render(
        self, owned: OwnedSettings, *, inputs: list[Path], output: Path,
        runid: str, grid: _DeliveryGrid,
    ) -> str:
        if not inputs or not owned.l2w_parameters:
            raise ValueError("ACOLITE input and processing parameter sets must be non-empty")
        if owned.merge_tiles != (len(inputs) > 1):
            raise ValueError("merge_tiles must exactly reflect the selected input count")
        if any(path.suffix.lower() != ".zip" for path in inputs):
            raise ValueError("ACOLITE inputs must be complete SAFE zip archives")
        # The limit is part of AcoliteProfile identity, so it must be the one ACOLITE receives.
        if owned.limit != limit_for_grid(grid):
            raise ValueError("owned limit must equal the delivery grid limit")

        values: list[tuple[str, object]] = [
            ("inputfile", ",".join(str(path) for path in sorted(inputs))),
            ("output", output),
            ("runid", runid),
            ("limit", owned.limit),
        ]
        if owned.merge_tiles:
            values.append(("merge_tiles", True))
        values.extend([
            ("extract_inputfile", owned.extract_inputfile),
            ("s2_target_res", owned.s2_target_res),
            ("l2w_parameters", owned.l2w_parameters),
            ("delete_extracted_input", owned.delete_extracted_input),
            ("rgb_rhot", owned.rgb_rhot),
            ("rgb_rhos", owned.rgb_rhos),
            ("l2w_mask_threshold", owned.l2w_mask_threshold),
            ("dsf_residual_glint_correction", owned.dsf_residual_glint_correction),
            ("l2w_mask_water_parameters", owned.l2w_mask_water_parameters),
            ("dsf_aot_estimate", owned.dsf_aot_estimate),
            ("ancillary_type", owned.ancillary_type),
            ("l1r_delete_netcdf", owned.l1r_delete_netcdf),
            ("netcdf_compression", owned.netcdf_compression),
        ])
        return "".join(f"{key}={_format(value)}\n" for key, value in values)

    def write(
        self, path: Path, owned: OwnedSettings, *, inputs: list[Path], output: Path,
        runid: str, grid: _DeliveryGrid,
    ) -> Path:
        """Atomically write one rendered settings file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}-", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(self.render(owned, inputs=inputs, output=output, runid=runid, grid=grid))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return path
