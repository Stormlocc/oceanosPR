"""One observation end to end: A1 → A2 → P1–P4 under the writer lock, then P5–P8 downstream."""

from __future__ import annotations

import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

import oceanos
from oceanos.acolite import (
    InstallationProbe,
    RunVerifier,
    SettingsRenderer,
    SubprocessAcoliteRunner,
)
from oceanos.acolite.products import ancillary_type_for
from oceanos.acolite.runner import ProcessOutcome
from oceanos.acolite.settings import limit_for_grid
from oceanos.aoi import load_aoi
from oceanos.catalog import LocalSceneCatalog, SceneMetadata
from oceanos.config import OceanosSettings
from oceanos.domain import (
    AcoliteInstallation,
    AcoliteParameterSet,
    AcolitePin,
    AcoliteProfile,
    AcoliteRunOutputs,
    AcquiredScene,
    AncillaryTier,
    FailureCode,
    FailureRecord,
    FailureScope,
    OwnedSettings,
    ProductSet,
    PublicationProfile,
    QualityPolicy,
    RunAttempt,
    RunState,
    StageName,
    StageResult,
    run_key,
)
from oceanos.pipeline.archive import ArchiveStore, AttemptsLedger, recover_stale_attempt
from oceanos.pipeline.downstream import (
    DownstreamInputs,
    PipelineError,
    load_archived_outputs,
    publish_downstream,
)
from oceanos.pipeline.plan import (
    build_input_set,
    group_overpasses,
    select_minimal_cover_with_scenes,
)
from oceanos.processing.grid import DeliveryGrid
from oceanos.processing.quality import specular_angle_deg
from oceanos.publishing import current_release_id, reconcile
from oceanos.publishing.release import FaultHook
from oceanos.storage import StorageLayout, WriterLock

L1C_COLLECTION = "sentinel-2-l1c"
CONTRACT_VERSION = "1"
# Brief assumption: final (reanalysis) ancillary data are used once a scene is this old.
FINAL_ANCILLARY_AFTER = timedelta(days=50)

AcquireFn = Callable[[SceneMetadata], AcquiredScene]
ProbeFn = Callable[[], AcoliteInstallation | FailureRecord]
RunAcoliteFn = Callable[[Path, Path, str, WriterLock], ProcessOutcome]

__all__ = ["PipelineError", "RunOneDependencies", "RunOneResult", "check_releases", "latest_release_dir", "run_one"]


@dataclass(frozen=True)
class RunOneResult:
    status: Literal["published", "skipped"]
    run_key: str
    release_id: str
    release_dir: Path
    attempt_id: str | None
    visibility: Literal["public", "restricted"] | None = None


@dataclass
class RunOneDependencies:
    """External effects, substituted in tests (T24)."""

    acquire: AcquireFn
    probe: ProbeFn
    run_acolite: RunAcoliteFn
    git_sha: Callable[[], str]
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    verifier: RunVerifier = field(default_factory=RunVerifier)


def _project_git_sha() -> str:
    root = Path(oceanos.__file__).resolve().parents[2]
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()


def default_dependencies(settings: OceanosSettings, catalog: LocalSceneCatalog) -> RunOneDependencies:
    """Wire the real CDSE acquisition, installation probe and ACOLITE subprocess."""
    from oceanos.ingestion import acquire_scene
    from oceanos.ingestion.cdse_auth import CdseTokenClient

    token = CdseTokenClient(settings.scenes.identity_url)
    config = settings.acolite

    def acquire(scene: SceneMetadata) -> AcquiredScene:
        return acquire_scene(
            scene, settings.storage.raw, token_provider=token, catalog=catalog,
            max_retries=settings.scenes.max_retries,
        ).acquired

    def probe() -> AcoliteInstallation | FailureRecord:
        # The scratch tier may not exist before the first attempt; measure the disk it will use.
        settings.storage.work.mkdir(parents=True, exist_ok=True)
        return InstallationProbe().probe(
            pin=AcolitePin(release_tag=config.release_tag, commit_sha=config.commit_sha),
            root=config.root, python_executable=config.python_executable, launcher=config.launcher,
            luts_dir=config.luts_dir, external_dir=config.external_dir,
            netrc_path=Path.home() / ".netrc", disk_path=settings.storage.work,
            required_disk_bytes=10 * 1024**3,
        )

    def run_acolite(settings_path: Path, workspace: Path, runid: str, lock: WriterLock) -> ProcessOutcome:
        return SubprocessAcoliteRunner().run(
            python_executable=config.python_executable, launcher=config.launcher,
            settings_path=settings_path, workspace=workspace,
            timeout_seconds=config.timeout_seconds, runid=runid, lock=lock,
        )

    return RunOneDependencies(acquire=acquire, probe=probe, run_acolite=run_acolite, git_sha=_project_git_sha)


def layout_for(settings: OceanosSettings) -> StorageLayout:
    storage = settings.storage
    return StorageLayout(
        raw=storage.raw, work=storage.work, archive=storage.archive, products=storage.products,
        superseded=storage.superseded, state=storage.state,
    )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _failure(code: FailureCode, stage: StageName, message: str, evidence: list[str] | None = None,
             *, scope: FailureScope = FailureScope.OBSERVATION, retryable: bool = False) -> FailureRecord:
    return FailureRecord(
        code=code, scope=scope, stage=stage.value, message=message, evidence=evidence or [],
        retryable=retryable, occurred_at=datetime.now(UTC),
    )


class _AttemptRecorder:
    """Append every attempt transition to the ledger (DA #8)."""

    def __init__(self, ledger: AttemptsLedger, attempt: RunAttempt) -> None:
        self.ledger = ledger
        self.attempt = attempt
        self._stage_started = datetime.now(UTC)

    def advance(self, stage: StageName, state: RunState, **detail: object) -> None:
        result = StageResult(
            stage=stage, status="ok", started_at=self._stage_started, ended_at=datetime.now(UTC),
            detail=dict(detail),
        )
        self.attempt = self.attempt.model_copy(update={"state": state, "stages": [*self.attempt.stages, result]})
        self.ledger.append(self.attempt)
        self._stage_started = datetime.now(UTC)

    def fail(self, stage: StageName, failure: FailureRecord) -> PipelineError:
        result = StageResult(
            stage=stage, status="failed", started_at=self._stage_started, ended_at=datetime.now(UTC),
            detail={"code": failure.code.value},
        )
        self.attempt = self.attempt.model_copy(update={
            "state": RunState.FAILED, "stages": [*self.attempt.stages, result], "failure": failure,
        })
        self.ledger.append(self.attempt)
        return PipelineError(failure)


def _tier(scene_datetime: datetime, now: datetime) -> AncillaryTier:
    return AncillaryTier.FINAL if now - scene_datetime >= FINAL_ANCILLARY_AFTER else AncillaryTier.PROVISIONAL


def run_one(
    settings: OceanosSettings, overpass_id: str, *, parameters: AcoliteParameterSet,
    products: ProductSet, policy: QualityPolicy, publication: PublicationProfile,
    force_reprocess: bool = False, dependencies: RunOneDependencies | None = None,
    fault: FaultHook | None = None,
) -> RunOneResult:
    """Publish one observation for ``overpass_id`` from a prior grid build and scene search."""
    layout = layout_for(settings)
    aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
    grid_path = layout.grid_json(aoi.aoi_id)
    if not grid_path.is_file():
        raise ValueError(f"delivery grid missing; run `grid build` first: {grid_path}")
    grid = DeliveryGrid.load(grid_path)
    catalog = LocalSceneCatalog(settings.catalog_dir, collection_id=L1C_COLLECTION)
    groups = group_overpasses(catalog.search_local_catalog(collection=L1C_COLLECTION))
    if overpass_id not in groups:
        raise ValueError(f"overpass not in local catalog; run `scenes search` covering it first: {overpass_id}")
    deps = dependencies or default_dependencies(settings, catalog)

    # A1 + A2: selection and verified acquisition are idempotent and precede the lock.
    coverage, selected = select_minimal_cover_with_scenes(groups[overpass_id], grid)
    acquired = [deps.acquire(scene) for scene in selected]
    input_set = build_input_set(overpass_id, acquired, coverage)

    now = deps.now()
    scene_datetime = min(scene.datetime for scene in selected)
    tier = _tier(scene_datetime, now)
    owned = OwnedSettings(
        limit=limit_for_grid(grid), merge_tiles=len(input_set.scenes) > 1,
        l2w_parameters=parameters.parameters, ancillary_type=ancillary_type_for(tier),
    )
    pin = AcolitePin(release_tag=settings.acolite.release_tag, commit_sha=settings.acolite.commit_sha)
    profile = AcoliteProfile(
        acolite=pin, settings=owned, parameter_set_version=parameters.version,
        grid_id=grid.grid_id, ancillary_tier=tier, contract_version=CONTRACT_VERSION,
    )
    observation_id = f"{aoi.aoi_id}/{overpass_id}"
    key = run_key(observation_id, input_set.input_set_id, profile.profile_id)

    ledger = AttemptsLedger(layout.state / "ledger" / "attempts.jsonl")
    current = current_release_id(layout, aoi.aoi_id, overpass_id)
    published_for_key = any(
        attempt.run_key == key and attempt.state is RunState.PUBLISHED for attempt in ledger.latest().values()
    )
    if published_for_key and current is not None and not force_reprocess:
        return RunOneResult(
            status="skipped", run_key=key, release_id=current,
            release_dir=layout.release_dir(aoi.aoi_id, overpass_id, current), attempt_id=None,
        )

    attempt_id = f"att-{now.strftime('%Y%m%dT%H%M%SZ')}-{key[4:12]}"
    lock = WriterLock(layout.writer_lock)
    recover_stale_attempt(lock=lock, ledger=ledger, staging=layout.work / "staging")
    with lock.hold(attempt_id):
        reconcile(layout, aoi.aoi_id, repair=True)
        current = current_release_id(layout, aoi.aoi_id, overpass_id)
        recorder = _AttemptRecorder(ledger, RunAttempt(
            attempt_id=attempt_id, run_key=key, state=RunState.PLANNED, host=socket.gethostname(),
            oceanos_version=oceanos.__version__, oceanos_git_sha=deps.git_sha(),
            acolite_exit_code=None, stages=[], failure=None,
        ))
        recorder.advance(StageName.PLAN, RunState.PLANNED, input_set_id=input_set.input_set_id,
                         acolite_profile_id=profile.profile_id, tier=tier.value)

        # P1 preflight: SAFE re-verification, then the installation probe.
        inputs: list[Path] = []
        for scene in input_set.scenes:
            archive = layout.raw / scene.archive.relpath
            if not archive.is_file() or _file_sha256(archive) != scene.archive.sha256:
                raise recorder.fail(StageName.PREFLIGHT, _failure(
                    FailureCode.CHECKSUM_MISMATCH, StageName.PREFLIGHT, "SAFE SHA-256 re-verification failed",
                    [scene.scene_id], retryable=True,
                ))
            inputs.append(archive)
        installation = deps.probe()
        if isinstance(installation, FailureRecord):
            raise recorder.fail(StageName.PREFLIGHT, installation)
        recorder.advance(StageName.PREFLIGHT, RunState.PREFLIGHTED)

        # P2 execute.
        workspace = layout.work_attempt_dir(attempt_id)
        settings_path = SettingsRenderer().write(
            workspace / "oceanos_settings.txt", owned, inputs=inputs, output=workspace,
            runid=attempt_id, grid=grid,
        )
        outcome = deps.run_acolite(settings_path, workspace, attempt_id, lock)
        recorder.attempt = recorder.attempt.model_copy(update={"acolite_exit_code": outcome.exit_code})
        recorder.advance(StageName.EXECUTE, RunState.EXECUTED, duration_seconds=outcome.duration_seconds)

        # P3 verify: success comes from artifacts and logs, never from the exit code.
        verified = deps.verifier.verify(
            workspace=workspace, attempt_id=attempt_id, platform=overpass_id[:3],  # type: ignore[arg-type]
            release_tag=pin.release_tag, parameters=parameters.parameters, outcome=outcome,
        )
        if isinstance(verified, FailureRecord):
            raise recorder.fail(StageName.VERIFY, verified)
        outputs: AcoliteRunOutputs = verified
        if outputs.geometry is not None:
            outputs = outputs.model_copy(update={"glint_angle_deg": specular_angle_deg(outputs.geometry)})
        recorder.advance(StageName.VERIFY, RunState.VERIFIED)

        # P4 archive (irreversible, I2).
        archive_dir = ArchiveStore(layout).commit(
            aoi_id=aoi.aoi_id, overpass_id=overpass_id, attempt=recorder.attempt, profile=profile,
            input_set=input_set, installation=installation, workspace=workspace, outputs=outputs,
        )
        archived_at = datetime.now(UTC)
        recorder.advance(StageName.ARCHIVE, RunState.ARCHIVED, archive=archive_dir.relative_to(layout.archive).as_posix())
        manifest = load_archived_outputs(layout, aoi.aoi_id, overpass_id, attempt_id)
        archived_outputs = AcoliteRunOutputs.model_validate(manifest["outputs"])

        result = publish_downstream(
            DownstreamInputs(
                settings=settings, layout=layout, aoi_id=aoi.aoi_id, overpass_id=overpass_id, grid=grid,
                grid_dir=grid_path.parent, catalog=catalog, attempt_id=attempt_id, run_key=key,
                oceanos_git_sha=recorder.attempt.oceanos_git_sha, profile=profile, input_set=input_set,
                installation_commit=installation.observed_commit, outputs=archived_outputs,
                archived_at=archived_at, scene_datetime=scene_datetime, products=products, policy=policy,
                publication=publication, current_release_id=current,
            ),
            advance=recorder.advance, fail=recorder.fail, fault=fault,
        )
    visibility: Literal["public", "restricted"] = "public" if result.report.verdict.value == "usable" else "restricted"
    return RunOneResult(
        status="published", run_key=key, release_id=result.release_id, release_dir=result.release_dir,
        attempt_id=attempt_id, visibility=visibility,
    )


def check_releases(settings: OceanosSettings) -> None:
    """Read-only reconciliation at the start of a mutating command; refuses a broken state."""
    aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
    reconcile(layout_for(settings), aoi.aoi_id, repair=False)


def latest_release_dir(settings: OceanosSettings, overpass_id: str) -> Path:
    """Return the current release directory recorded by the derived STAC Item."""
    layout = layout_for(settings)
    aoi = load_aoi(settings.aoi.path, name=settings.aoi.name, target_crs=settings.aoi.target_crs)
    reconcile(layout, aoi.aoi_id, repair=False)
    current = current_release_id(layout, aoi.aoi_id, overpass_id)
    if current is None:
        raise ValueError(f"no current release for overpass: {overpass_id}")
    return layout.release_dir(aoi.aoi_id, overpass_id, current)
