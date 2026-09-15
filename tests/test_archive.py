"""P4 archive and append-only attempt ledger preserve exact provenance."""

from __future__ import annotations

import json
from pathlib import Path

from support.fake_acolite import FakeAcoliteRunner

from oceanos.acolite import RunVerifier
from oceanos.domain import (
    AcolitePin,
    AcoliteProfile,
    AcoliteRunOutputs,
    AncillaryTier,
    OwnedSettings,
    RunAttempt,
    RunState,
)
from oceanos.pipeline.archive import ArchiveStore, AttemptsLedger
from oceanos.storage import StorageLayout

FIXTURES = Path(__file__).parent / "fixtures/acolite"
ATTEMPT_ID = "att-20260915T030258Z-01234567"
PARAMETERS = ("rhow_*", "Rrs_*", "rhorc_*", "tur_nechad2016", "spm_nechad2016", "chl_re_gons740", "fai", "fait", "ndvi")


def _attempt(state: RunState) -> RunAttempt:
    return RunAttempt(
        attempt_id=ATTEMPT_ID, run_key="run-0123456789abcdef", state=state,
        host="test-host", oceanos_version="0.1.0", oceanos_git_sha="a" * 40,
        acolite_exit_code=0, stages=[], failure=None,
    )


def _profile() -> AcoliteProfile:
    return AcoliteProfile(
        acolite=AcolitePin(release_tag="20260421.0", commit_sha="f73cbe73887c2b114d9d3c70865effee73871525"),
        settings=OwnedSettings(limit=(0, 0, 0, 0), merge_tiles=False,
                               l2w_parameters=PARAMETERS, ancillary_type="GMAO_MERRA2_MET"),
        parameter_set_version="1", grid_id="grid-0123456789ab",
        ancillary_tier=AncillaryTier.FINAL, contract_version="1",
    )


def test_archive_commits_only_allowlisted_files_and_manifest(tmp_path: Path) -> None:
    layout = StorageLayout.from_data_root(tmp_path)
    workspace = layout.work_attempt_dir(ATTEMPT_ID)
    outcome = FakeAcoliteRunner(FIXTURES, "success").run(workspace, runid=ATTEMPT_ID)
    (workspace / "large-unapproved.tmp").write_text("leave me", encoding="utf-8")
    outputs = RunVerifier().verify(
        workspace=workspace, attempt_id=ATTEMPT_ID, platform="S2A",
        release_tag="20260421.0", parameters=PARAMETERS, outcome=outcome,
    )
    assert isinstance(outputs, AcoliteRunOutputs)

    archived = ArchiveStore(layout).commit(
        aoi_id="aoi-la-parguera-0123456789ab",
        overpass_id="S2A_20260702T150741_R082", attempt=_attempt(RunState.VERIFIED),
        profile=_profile(), input_set={"input_set_id": "inp-0123456789abcdef"},
        installation={"observed_commit": "f73cbe73887c2b114d9d3c70865effee73871525",
                      "config_version_line": "version=20260421.0"},
        workspace=workspace, outputs=outputs,
    )

    assert {path.name for path in archived.iterdir()} == {
        next(workspace.glob("*_L2R.nc")).name,
        next(workspace.glob("*_L2W.nc")).name,
        "run.log", "l1r_settings_user.txt", "l2r_settings.txt", "run-manifest.json",
    }
    assert (workspace / "large-unapproved.tmp").is_file()
    manifest = json.loads((archived / "run-manifest.json").read_text(encoding="utf-8"))
    assert not any(str(tmp_path) in value for value in manifest["archived_files"])
    assert {
        manifest["outputs"][key]["relpath"]
        for key in ("l2r", "l2w", "log", "settings_user", "settings_resolved")
    } <= set(manifest["archived_files"])


def test_attempt_ledger_appends_and_fsyncs_every_transition(monkeypatch, tmp_path: Path) -> None:
    calls: list[int] = []
    monkeypatch.setattr("oceanos.pipeline.archive.os.fsync", calls.append)
    ledger = AttemptsLedger(tmp_path / "state/ledger/attempts.jsonl")

    ledger.append(_attempt(RunState.PLANNED))
    ledger.append(_attempt(RunState.FAILED))

    rows = [json.loads(line) for line in ledger.path.read_text(encoding="utf-8").splitlines()]
    assert [row["state"] for row in rows] == ["planned", "failed"]
    assert len(calls) == 2
