"""Downstream re-entry (DA-4): rebuild P5–P8 from the archive without ACOLITE or the SAFE."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from oceanos.aoi import load_aoi
from oceanos.catalog import L1C_COLLECTION, LocalSceneCatalog
from oceanos.config import OceanosSettings
from oceanos.domain import (
    AcoliteProfile,
    AcoliteRunOutputs,
    InputSet,
    ProductSet,
    PublicationProfile,
    QualityPolicy,
    Release,
    release_id,
)
from oceanos.pipeline.downstream import (
    DownstreamInputs,
    archived_at,
    downstream_profile,
    load_archived_outputs,
    publish_downstream,
)
from oceanos.pipeline.run_one import layout_for
from oceanos.processing.grid import DeliveryGrid
from oceanos.publishing import current_release_id, read_item, reconcile
from oceanos.publishing.release import FaultHook
from oceanos.storage import WriterLock


@dataclass(frozen=True)
class RepublishResult:
    overpass_id: str
    status: Literal["published", "unchanged"]
    release_id: str
    visibility: Literal["public", "restricted"] | None


def overpasses_in_range(settings: OceanosSettings, start: datetime, end: datetime) -> list[str]:
    """Overpasses with a current release whose observation datetime lies in [start, end]."""
    layout = layout_for(settings)
    aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
    items_dir = layout.products / aoi.aoi_id / "stac" / "items"
    selected = []
    for path in sorted(items_dir.glob("*.json")) if items_dir.is_dir() else []:
        item = read_item(layout.products / aoi.aoi_id, path.stem)
        if item is None:
            continue
        observed = datetime.fromisoformat(item["properties"]["datetime"])
        if start <= observed <= end:
            selected.append(path.stem)
    return selected


def republish(
    settings: OceanosSettings, overpass_id: str, *, products: ProductSet, policy: QualityPolicy,
    publication: PublicationProfile, fault: FaultHook | None = None,
) -> RepublishResult:
    """Publish a new release from the current release's archived attempt when the downstream profile changed."""
    layout = layout_for(settings)
    aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
    grid_path = layout.grid_json(aoi.aoi_id)
    grid = DeliveryGrid.load(grid_path)
    current = current_release_id(layout, aoi.aoi_id, overpass_id)
    if current is None:
        raise ValueError(f"no current release to republish for overpass: {overpass_id}")
    release = Release.model_validate_json(
        (layout.release_dir(aoi.aoi_id, overpass_id, current) / "release.json").read_text(encoding="utf-8")
    )
    attempt_id = release.attempt_id
    candidate = release_id(attempt_id, downstream_profile(products, policy, publication).profile_id)
    if candidate == current:
        return RepublishResult(overpass_id=overpass_id, status="unchanged", release_id=current, visibility=release.visibility)

    manifest = load_archived_outputs(layout, aoi.aoi_id, overpass_id, attempt_id)
    outputs = AcoliteRunOutputs.model_validate(manifest["outputs"])
    profile = AcoliteProfile.model_validate(manifest["acolite_profile"])
    input_set = InputSet.model_validate(manifest["input_set"])
    attempt = manifest["attempt"]
    installation = manifest["installation"]
    assert isinstance(attempt, dict) and isinstance(installation, dict)
    catalog = LocalSceneCatalog(settings.catalog_dir, collection_id=L1C_COLLECTION)
    scene_times = [scene.datetime for scene in (catalog.get_scene(item.scene_id) for item in input_set.scenes) if scene is not None]
    if not scene_times:
        raise ValueError(f"scene metadata for {overpass_id} is missing from the local catalog")

    lock = WriterLock(layout.writer_lock)
    with lock.hold(attempt_id):
        reconcile(layout, aoi.aoi_id, repair=True)
        result = publish_downstream(
            DownstreamInputs(
                settings=settings, layout=layout, aoi_id=aoi.aoi_id, overpass_id=overpass_id, grid=grid,
                grid_dir=grid_path.parent, catalog=catalog, attempt_id=attempt_id, run_key=str(manifest["run_key"]),
                oceanos_git_sha=str(attempt["oceanos_git_sha"]), profile=profile, input_set=input_set,
                installation_commit=str(installation["observed_commit"]), outputs=outputs,
                archived_at=archived_at(layout, aoi.aoi_id, overpass_id, attempt_id), scene_datetime=min(scene_times),
                products=products, policy=policy, publication=publication,
                current_release_id=current_release_id(layout, aoi.aoi_id, overpass_id),
            ),
            fault=fault,
        )
    visibility: Literal["public", "restricted"] = "public" if result.report.verdict.value == "usable" else "restricted"
    return RepublishResult(overpass_id=overpass_id, status="published", release_id=result.release_id, visibility=visibility)


__all__ = ["RepublishResult", "overpasses_in_range", "republish"]
