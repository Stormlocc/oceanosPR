"""Pure exact-cover planning tests."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import Affine, array_bounds
from shapely.geometry import box, mapping
from shapely.ops import transform

from oceanos.catalog import SceneMetadata
from oceanos.domain import (
    AcquiredScene,
    ArtifactRef,
    InputSet,
    TileCoverage,
    input_set_id,
)
from oceanos.pipeline.plan import (
    SelectionError,
    select_minimal_cover,
    select_minimal_cover_with_scenes,
)
from oceanos.processing.grid import DeliveryGrid, GridSpec


def delivery_grid() -> DeliveryGrid:
    affine = Affine(10, 0, 500000, 0, -10, 100)
    spec = GridSpec(CRS.from_epsg(32619), 10, array_bounds(10, 10, affine), 10, 10, affine)
    return DeliveryGrid(grid_id="grid-0123456789ab", aoi_id="aoi-test-0123456789ab", spec=spec, anchor=(0, 0), buffer_m=0, created_at=datetime.now(UTC))


def scene(tile: str, footprint, cloud: float = 10, *, platform: str = "S2A", datatake: str = "GS2A_20260702T150741_057594_N05.12", orbit: int = 82) -> SceneMetadata:
    return SceneMetadata(
        scene_id=f"S2A_MSIL1C_20260702T150741_N0512_R082_T{tile}_X", collection="sentinel-2-l1c",
        platform=platform, datetime="2026-07-02T15:07:41Z", geometry=mapping(footprint), bbox=footprint.bounds,
        cloud_cover=cloud, source_catalog="https://catalogue.example", processing_level="Level-1C",
        processing_baseline="05.12", relative_orbit=orbit, datatake_id=datatake,
        overpass_id="S2A_20260702T150741_R082", mgrs_tile=tile, source_id=tile,
    )


def footprints():
    transformer = Transformer.from_crs(32619, 4326, always_xy=True)
    whole = transform(transformer.transform, box(500000, 0, 500100, 100))
    west = transform(transformer.transform, box(499990, -10, 500055, 110))
    east = transform(transformer.transform, box(500045, -10, 500110, 110))
    return whole, west, east


def acquired(source: SceneMetadata, *, verified: bool = True) -> AcquiredScene:
    digest = sha256(source.scene_id.encode()).hexdigest()
    return AcquiredScene(
        scene_id=source.scene_id,
        source_id=source.source_id or "source",
        archive=ArtifactRef(
            role="source", relpath=f"sentinel2-l1c/{digest}/{source.scene_id}.zip",
            sha256=digest, size=1, media_type="application/zip",
        ),
        provider_md5_verified=verified,
        safe_members_verified=verified,
        verified_at=datetime.now(UTC),
    )


def input_set(scenes: tuple[AcquiredScene, ...], coverage, *, overpass: str = "S2A_20260702T150741_R082") -> InputSet:
    return InputSet(
        input_set_id=input_set_id(scenes), overpass_id=overpass,
        scenes=scenes, coverage=coverage, discovery_cloud_cover=10,
    )


def test_exact_minimal_cover_prefers_lower_cloud_then_tile_id() -> None:
    _, west, east = footprints()
    coverage = select_minimal_cover([
        scene("19QGA", west, 10), scene("19QGB", east, 20), scene("19QGC", east, 5),
    ], delivery_grid())
    assert coverage.selected == ("19QGA", "19QGC")
    assert coverage.covers_grid is True
    assert coverage.candidates[0].aoi_fraction == pytest.approx(0.55, abs=0.02)


def test_one_complete_tile_beats_any_multi_tile_set() -> None:
    whole, west, east = footprints()
    coverage = select_minimal_cover([scene("19QGA", west), scene("19QGB", east), scene("19QGV", whole, 99)], delivery_grid())
    assert coverage.selected == ("19QGV",)


def test_incomplete_or_mixed_overpass_is_rejected() -> None:
    _, west, east = footprints()
    with pytest.raises(SelectionError, match="input.incomplete_tile_set"):
        select_minimal_cover([scene("19QGA", west)], delivery_grid())
    with pytest.raises(SelectionError, match="input.mixed_overpass"):
        select_minimal_cover([scene("19QGA", west), scene("19QGB", east, platform="S2B")], delivery_grid())


def test_input_set_requires_exactly_the_selected_acquired_scenes() -> None:
    whole, west, _ = footprints()
    selected = scene("19QGV", whole)
    coverage = select_minimal_cover([selected], delivery_grid())

    with pytest.raises(ValueError, match="selected acquired scenes"):
        input_set((), coverage)

    different = acquired(scene("19QGA", west))
    with pytest.raises(ValueError, match="selected acquired scenes"):
        input_set((different,), coverage)


def test_input_set_rejects_wrong_overpass_and_unverified_handoff() -> None:
    whole, _, _ = footprints()
    selected = scene("19QGV", whole)
    coverage = select_minimal_cover([selected], delivery_grid())
    verified = acquired(selected)

    with pytest.raises(ValueError, match="same overpass"):
        input_set((verified,), coverage, overpass="S2A_20260703T150741_R082")

    unverified = verified.model_copy(update={"safe_members_verified": False})
    with pytest.raises(ValueError, match="verified"):
        input_set((unverified,), coverage)


def test_coverage_persists_exact_winning_scene_identity() -> None:
    whole, _, _ = footprints()
    base = scene("19QGV", whole)
    winner = base.model_copy(update={"scene_id": f"{base.scene_id}_A", "cloud_cover": 1})
    loser = base.model_copy(update={"scene_id": f"{base.scene_id}_B", "cloud_cover": 20})
    coverage, winning = select_minimal_cover_with_scenes([loser, winner], delivery_grid())

    assert tuple(scene.scene_id for scene in winning) == (winner.scene_id,)
    assert coverage.selected_scene_ids == (winner.scene_id,)
    assert TileCoverage.model_validate_json(coverage.model_dump_json()) == coverage


def test_input_set_rejects_verified_loser_from_same_selected_tile() -> None:
    whole, _, _ = footprints()
    base = scene("19QGV", whole)
    winner = base.model_copy(update={"scene_id": f"{base.scene_id}_A", "cloud_cover": 1})
    loser = base.model_copy(update={"scene_id": f"{base.scene_id}_B", "cloud_cover": 20})
    coverage, _ = select_minimal_cover_with_scenes([loser, winner], delivery_grid())
    acquired_winner = acquired(winner)
    acquired_loser = acquired(loser)
    selected_input = input_set((acquired_winner,), coverage)

    assert InputSet.model_validate_json(selected_input.model_dump_json()) == selected_input
    assert selected_input.input_set_id != input_set_id((acquired_loser,))
    with pytest.raises(ValueError, match="winning scene identities"):
        input_set((acquired_loser,), coverage)
