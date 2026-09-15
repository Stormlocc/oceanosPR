"""Immutable release commit, supersession ledger and crash reconciliation (DA-5, B1)."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from oceanos.domain import MetadataModel, ReleaseId
from oceanos.publishing.stac import read_item, write_item
from oceanos.storage import StorageLayout

FaultHook = Callable[[str], None]


class ReconcileError(RuntimeError):
    """Published state is inconsistent and cannot be repaired automatically."""


class ReleaseEvent(MetadataModel):
    schema_version: str = "1.0"
    event: Literal["release_published", "release_superseded", "orphan_removed"]
    release_id: ReleaseId
    observation_id: str = Field(min_length=1)
    supersedes: ReleaseId | None = None
    occurred_at: AwareDatetime


class ReleaseLedger:
    """Append-only, fsynced release events; the rebuild source for releases."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: ReleaseEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event.model_dump(mode="json"), sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def events(self) -> list[ReleaseEvent]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as stream:
            return [ReleaseEvent.model_validate_json(line) for line in stream if line.strip()]

    def published(self) -> set[str]:
        return {event.release_id for event in self.events() if event.event == "release_published"}


def release_ledger(layout: StorageLayout) -> ReleaseLedger:
    return ReleaseLedger(layout.state / "ledger" / "releases.jsonl")


def _no_fault(_: str) -> None:
    return None


def current_release_id(layout: StorageLayout, aoi_id: str, overpass_id: str) -> str | None:
    item = read_item(layout.products / aoi_id, overpass_id)
    if item is None:
        return None
    value = item["properties"]["oceanos:release_id"]
    return str(value)


def _supersede(
    layout: StorageLayout, ledger: ReleaseLedger, aoi_id: str, overpass_id: str, release: str,
) -> None:
    source = layout.release_dir(aoi_id, overpass_id, release)
    destination = layout.superseded_release_dir(aoi_id, overpass_id, release)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    os.replace(source, destination)
    ledger.append(ReleaseEvent(
        event="release_superseded", release_id=release, observation_id=f"{aoi_id}/{overpass_id}",
        occurred_at=datetime.now(UTC),
    ))


def publish_release(
    *, layout: StorageLayout, aoi_id: str, overpass_id: str, release_id: str,
    staged_dir: Path, item: dict[str, Any], supersedes: str | None,
    fault: FaultHook = _no_fault,
) -> Path:
    """Commit a staged release; the previous release stays served until the last step."""
    destination = layout.release_dir(aoi_id, overpass_id, release_id)
    if destination.exists():
        raise FileExistsError(f"release directories are immutable: {destination}")
    ledger = release_ledger(layout)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Staging comes from mkdtemp/NamedTemporaryFile (owner-only); published releases are world-readable.
    staged_dir.chmod(0o755)
    for path in staged_dir.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    # 1. The new release directory appears, not yet referenced by the Item.
    os.replace(staged_dir, destination)
    fault("release_dir")
    # 2. The Item atomically switches to the new release.
    write_item(item, layout.products / aoi_id, aoi_id)
    fault("stac_item")
    ledger.append(ReleaseEvent(
        event="release_published", release_id=release_id, observation_id=f"{aoi_id}/{overpass_id}",
        supersedes=supersedes, occurred_at=datetime.now(UTC),
    ))
    # 3. Index transaction: added in Phase 4.
    fault("index")
    # 4. Only now does the previous release leave the served tier.
    for sibling in sorted(destination.parent.iterdir()):
        if sibling.is_dir() and not sibling.name.startswith(".") and sibling.name != release_id:
            _supersede(layout, ledger, aoi_id, overpass_id, sibling.name)
    return destination


class ReconcileReport(MetadataModel):
    orphans_removed: list[str] = Field(default_factory=list)
    superseded: list[str] = Field(default_factory=list)
    published_events_added: list[str] = Field(default_factory=list)
    broken: list[str] = Field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.orphans_removed or self.superseded or self.published_events_added or self.broken)


def reconcile(layout: StorageLayout, aoi_id: str, *, repair: bool) -> ReconcileReport:
    """Restore I3 after a crash inside ``publish_release``.

    With ``repair=False`` nothing is changed: the report lists what would be done, and a
    broken state (an Item pointing at a missing release) raises ``ReconcileError``.
    """
    report = ReconcileReport()
    releases_root = layout.products / aoi_id / "releases"
    items_root = layout.products / aoi_id / "stac" / "items"
    overpasses = sorted({
        *(path.name for path in releases_root.iterdir() if path.is_dir()),
        *(path.stem for path in items_root.glob("*.json")),
    }) if releases_root.exists() or items_root.exists() else []
    ledger = release_ledger(layout)
    published = ledger.published()
    for overpass_id in overpasses:
        current = current_release_id(layout, aoi_id, overpass_id)
        overpass_dir = releases_root / overpass_id
        if current is not None and not (overpass_dir / current).is_dir():
            report.broken.append(f"{overpass_id}: current release {current} is missing")
            continue
        if not overpass_dir.is_dir():
            continue
        for release_dir in sorted(overpass_dir.iterdir()):
            name = release_dir.name
            if not release_dir.is_dir() or name.startswith("."):
                continue
            if name == current:
                if name not in published:
                    report.published_events_added.append(name)
                    if repair:
                        ledger.append(ReleaseEvent(
                            event="release_published", release_id=name,
                            observation_id=f"{aoi_id}/{overpass_id}", occurred_at=datetime.now(UTC),
                        ))
            elif name in published:
                report.superseded.append(name)
                if repair:
                    _supersede(layout, ledger, aoi_id, overpass_id, name)
            else:
                report.orphans_removed.append(name)
                if repair:
                    shutil.rmtree(release_dir)
                    ledger.append(ReleaseEvent(
                        event="orphan_removed", release_id=name,
                        observation_id=f"{aoi_id}/{overpass_id}", occurred_at=datetime.now(UTC),
                    ))
    if report.broken:
        raise ReconcileError("; ".join(report.broken))
    return report
