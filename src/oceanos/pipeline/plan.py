"""Pure, deterministic minimal tile-cover selection."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from typing import Any

from pyproj import Transformer
from shapely.geometry import box, shape  # type: ignore[import-untyped]
from shapely.ops import transform, unary_union  # type: ignore[import-untyped]

from oceanos.catalog.models import SceneMetadata
from oceanos.domain import (
    AcquiredScene,
    FailureCode,
    InputSet,
    TileCandidate,
    TileCoverage,
    input_set_id,
)
from oceanos.processing.grid import DeliveryGrid


class SelectionError(RuntimeError):
    """An overpass cannot form one complete, consistent delivery input."""

    def __init__(self, code: FailureCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")


def group_overpasses(scenes: Sequence[SceneMetadata]) -> dict[str, tuple[SceneMetadata, ...]]:
    """Group scenes by validated provider-derived overpass identity."""
    groups: dict[str, list[SceneMetadata]] = {}
    for scene in scenes:
        if scene.overpass_id is None:
            raise SelectionError(FailureCode.MIXED_OVERPASS, f"scene {scene.scene_id} has no OverpassId")
        groups.setdefault(scene.overpass_id, []).append(scene)
    return {
        overpass: tuple(sorted(members, key=lambda item: (item.mgrs_tile or "", item.scene_id)))
        for overpass, members in sorted(groups.items())
    }


def _grid_polygon(grid: DeliveryGrid) -> Any:
    projected = box(*grid.spec.bounds)
    transformer = Transformer.from_crs(grid.spec.crs, 4326, always_xy=True)
    return transform(transformer.transform, projected)


def _validate_overpass(scenes: Sequence[SceneMetadata]) -> None:
    if not scenes:
        raise SelectionError(FailureCode.INCOMPLETE_TILE_SET, "no candidate scenes")
    if len(scenes) > 4:
        raise ValueError("minimal-cover selection supports at most four candidates")
    if any(scene.processing_level != "Level-1C" for scene in scenes):
        raise SelectionError(FailureCode.NOT_L1C, "every candidate must be Level-1C")
    identity = {
        (scene.platform, scene.datatake_id, scene.relative_orbit, scene.overpass_id)
        for scene in scenes
    }
    if len(identity) != 1 or any(value is None for value in next(iter(identity))):
        raise SelectionError(
            FailureCode.MIXED_OVERPASS,
            "candidate scenes disagree on platform, datatake, orbit, or OverpassId",
        )
    if any(scene.mgrs_tile is None for scene in scenes):
        raise SelectionError(FailureCode.MIXED_OVERPASS, "every candidate must have an MGRS tile")


def select_minimal_cover_with_scenes(
    scenes: Sequence[SceneMetadata], grid: DeliveryGrid,
) -> tuple[TileCoverage, tuple[SceneMetadata, ...]]:
    """Return coverage plus the exact scene identities in its winning subset."""
    _validate_overpass(scenes)
    polygon = _grid_polygon(grid)
    ordered = sorted(scenes, key=lambda scene: (scene.mgrs_tile or "", scene.scene_id))
    candidate_records = []
    for scene in ordered:
        assert scene.mgrs_tile is not None
        candidate_records.append(TileCandidate(
            scene_id=scene.scene_id, mgrs_tile=scene.mgrs_tile,
            footprint=scene.geometry.model_dump(mode="json"), cloud_cover=scene.cloud_cover,
            aoi_fraction=min(1.0, shape(scene.geometry.model_dump()).intersection(polygon).area / polygon.area),
        ))
    candidates = tuple(candidate_records)
    winning: tuple[SceneMetadata, ...] | None = None
    for count in range(1, len(ordered) + 1):
        covers = [
            subset for subset in combinations(ordered, count)
            if unary_union([shape(scene.geometry.model_dump()) for scene in subset]).covers(polygon)
        ]
        if covers:
            winning = min(
                covers,
                key=lambda subset: (
                    max(scene.cloud_cover if scene.cloud_cover is not None else float("inf") for scene in subset),
                    tuple(sorted(scene.mgrs_tile or "" for scene in subset)),
                    tuple(sorted(scene.scene_id for scene in subset)),
                ),
            )
            break
    if winning is None:
        raise SelectionError(FailureCode.INCOMPLETE_TILE_SET, "no candidate subset covers the delivery grid")
    coverage = TileCoverage(
        candidates=candidates,
        selected=tuple(sorted(scene.mgrs_tile for scene in winning if scene.mgrs_tile is not None)),
        selected_scene_ids=tuple(sorted(scene.scene_id for scene in winning)),
        covers_grid=True,
    )
    return coverage, tuple(sorted(winning, key=lambda scene: scene.scene_id))


def select_minimal_cover(scenes: Sequence[SceneMetadata], grid: DeliveryGrid) -> TileCoverage:
    """Return the exact smallest candidate subset covering the delivery grid."""
    coverage, _ = select_minimal_cover_with_scenes(scenes, grid)
    return coverage


def build_input_set(
    overpass_id: str, scenes: Sequence[AcquiredScene], coverage: TileCoverage,
) -> InputSet:
    """Construct the verified A1/A2 handoff from the selected acquisitions."""
    ordered = tuple(sorted(scenes, key=lambda scene: scene.scene_id))
    clouds = {
        candidate.scene_id: candidate.cloud_cover
        for candidate in coverage.candidates
        if candidate.scene_id in {scene.scene_id for scene in ordered}
    }
    discovery_cloud_cover = (
        max(cloud for cloud in clouds.values() if cloud is not None)
        if clouds and all(cloud is not None for cloud in clouds.values())
        else None
    )
    return InputSet(
        input_set_id=input_set_id(ordered), overpass_id=overpass_id,
        scenes=ordered, coverage=coverage, discovery_cloud_cover=discovery_cloud_cover,
    )
