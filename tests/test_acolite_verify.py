"""Offline verifier tests over real-derived ACOLITE fixture variants."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.fake_acolite import FakeAcoliteRunner

from oceanos.acolite import ProcessOutcome, RunVerifier
from oceanos.domain import AcoliteRunOutputs, FailureCode

FIXTURES = Path(__file__).parent / "fixtures/acolite"
PIN = "20260421.0"
ATTEMPT = "att-20260915T030258Z-spike0001"
PARAMETERS = (
    "rhow_*", "Rrs_*", "rhorc_*", "tur_nechad2016", "spm_nechad2016",
    "chl_re_gons740", "fai", "fait", "ndvi",
)


def _verify(tmp_path: Path, variant: str, *, platform: str = "S2A"):
    workspace = tmp_path / variant
    outcome = FakeAcoliteRunner(FIXTURES, variant).run(workspace)
    return RunVerifier().verify(
        workspace=workspace, attempt_id=outcome.runid, platform=platform,
        release_tag=PIN, parameters=PARAMETERS, outcome=outcome,
    )


def test_success_fixture_returns_verified_outputs_and_reads_rhorc_from_l2r(tmp_path: Path) -> None:
    result = _verify(tmp_path, "success")

    assert isinstance(result, AcoliteRunOutputs)
    assert "rhorc_665" in result.l2r_variables
    assert result.settings_resolved.relpath.endswith("_l2r_settings.txt")
    assert result.flag_spec.usable_mask_value == 47
    assert result.aerosol.aerosol_model == "ACOLITE-LUT-202110-MOD2"
    assert result.ancillary.fallback_detected is False
    assert result.glint_angle_deg == pytest.approx(22.1310663539)


def test_skipped_fixture_with_zero_exit_is_failure(tmp_path: Path) -> None:
    result = _verify(tmp_path, "skipped")

    assert result.code is FailureCode.ACOLITE_SKIPPED
    assert "exit_code=0" in result.evidence
    assert any("Longitude limits outside" in line for line in result.evidence)


def test_missing_requested_variable_is_failure(tmp_path: Path) -> None:
    result = _verify(tmp_path, "missing_variable")
    assert result.code is FailureCode.ACOLITE_MISSING_VARIABLE


def test_ancillary_defaults_are_deferred_failure(tmp_path: Path) -> None:
    result = _verify(tmp_path, "ancillary_fallback", platform="S2B")
    assert result.code is FailureCode.ACOLITE_ANCILLARY_FALLBACK
    assert result.retryable is True


def test_nonzero_process_outcome_is_not_accepted(tmp_path: Path) -> None:
    workspace = tmp_path / "empty"
    workspace.mkdir()
    result = RunVerifier().verify(
        workspace=workspace, attempt_id=ATTEMPT, platform="S2A", release_tag=PIN,
        parameters=PARAMETERS,
        outcome=ProcessOutcome(runid=ATTEMPT, exit_code=2, duration_seconds=1,
                               log_path="run.log", timed_out=False),
    )
    assert result.code is FailureCode.ACOLITE_NONZERO_EXIT


def test_resolved_settings_must_preserve_the_complete_parameter_set(tmp_path: Path) -> None:
    workspace = tmp_path / "tampered"
    outcome = FakeAcoliteRunner(FIXTURES, "success").run(workspace)
    resolved = next(workspace.glob("*_l2r_settings.txt"))
    text = resolved.read_text(encoding="utf-8")
    resolved.write_text(text.replace(",ndvi\n", "\n"), encoding="utf-8")

    result = RunVerifier().verify(
        workspace=workspace, attempt_id=outcome.runid, platform="S2A",
        release_tag=PIN, parameters=PARAMETERS, outcome=outcome,
    )

    assert result.code is FailureCode.ACOLITE_MISSING_VARIABLE
    assert result.evidence == ["resolved l2w_parameters differ from requested set"]


def test_malformed_resolved_settings_returns_failure_record(tmp_path: Path) -> None:
    workspace = tmp_path / "malformed"
    outcome = FakeAcoliteRunner(FIXTURES, "success").run(workspace)
    resolved = next(workspace.glob("*_l2r_settings.txt"))
    lines = [
        line for line in resolved.read_text(encoding="utf-8").splitlines()
        if not line.startswith("flag_exponent_swir=")
    ]
    resolved.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = RunVerifier().verify(
        workspace=workspace, attempt_id=outcome.runid, platform="S2A",
        release_tag=PIN, parameters=PARAMETERS, outcome=outcome,
    )

    assert result.code is FailureCode.ACOLITE_MISSING_VARIABLE
    assert result.evidence == ["invalid or incomplete output metadata"]


def test_benign_processing_log_line_is_not_a_skip(tmp_path: Path) -> None:
    workspace = tmp_path / "benign-log"
    outcome = FakeAcoliteRunner(FIXTURES, "success").run(workspace)
    log = workspace / outcome.log_path
    with log.open("a", encoding="utf-8") as stream:
        stream.write("Processing of auxiliary metadata completed\n")

    result = RunVerifier().verify(
        workspace=workspace, attempt_id=outcome.runid, platform="S2A",
        release_tag=PIN, parameters=PARAMETERS, outcome=outcome,
    )

    assert isinstance(result, AcoliteRunOutputs)
