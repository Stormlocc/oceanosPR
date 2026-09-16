"""Golden execution against the pinned local ACOLITE and Phase 1 scene A."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin
from support.fake_acolite import FakeAcoliteRunner

from oceanos.acolite import (
    InstallationProbe,
    RunVerifier,
    SettingsRenderer,
    SubprocessAcoliteRunner,
)
from oceanos.acolite.settings import limit_for_grid
from oceanos.config import load_acolite_parameter_set, load_config
from oceanos.domain import (
    AcoliteInstallation,
    AcolitePin,
    AcoliteRunOutputs,
    OwnedSettings,
)
from oceanos.processing.grid import DeliveryGrid, GridSpec
from oceanos.storage import WriterLock

pytestmark = pytest.mark.acolite
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = PROJECT_ROOT / "tests/fixtures/acolite"
SCENE_A = PROJECT_ROOT / ".work/oceanos-pr-mvp/spikes/safe/S2A_MSIL1C_20260702T150741_N0512_R082_T19QGV_20260702T214456.zip"
ATTEMPT = "att-20260915T120000Z-01234567"


def _grid() -> DeliveryGrid:
    window = json.loads((FIXTURES / "window.json").read_text(encoding="utf-8"))
    bounds = window["projected_bounds"]
    transform = from_origin(bounds["west"], bounds["north"], 10, 10)
    return DeliveryGrid(
        grid_id="grid-0123456789ab", aoi_id="aoi-la-parguera-0123456789ab",
        spec=GridSpec(CRS.from_epsg(32619), 10, (
            bounds["west"], bounds["south"], bounds["east"], bounds["north"],
        ), window["width"], window["height"], transform),
        anchor=(0, 0), buffer_m=0, created_at=datetime.now(UTC),
    )


def test_scene_a_matches_phase1_names_units_and_flag_spec(tmp_path: Path) -> None:
    settings = load_config(PROJECT_ROOT / "configs/mvp.yaml")
    parameters = load_acolite_parameter_set(PROJECT_ROOT / "configs/acolite_parameters.yaml")
    if not SCENE_A.is_file():
        pytest.fail(f"Phase 1 scene A prerequisite missing: {SCENE_A}")
    probe = InstallationProbe().probe(
        pin=AcolitePin(release_tag=settings.acolite.release_tag, commit_sha=settings.acolite.commit_sha),
        root=settings.acolite.root, python_executable=settings.acolite.python_executable,
        launcher=settings.acolite.launcher, luts_dir=settings.acolite.luts_dir,
        external_dir=settings.acolite.external_dir, netrc_path=Path.home() / ".netrc",
        disk_path=tmp_path, required_disk_bytes=3 * SCENE_A.stat().st_size,
    )
    if not isinstance(probe, AcoliteInstallation):
        pytest.fail(f"ACOLITE probe prerequisite failed: {probe.model_dump(mode='json')}")

    workspace = tmp_path / "run"
    owned = OwnedSettings(
        limit=limit_for_grid(_grid()), merge_tiles=False,
        l2w_parameters=parameters.parameters, ancillary_type="GMAO_MERRA2_MET",
    )
    rendered = SettingsRenderer().write(
        tmp_path / "settings.txt", owned, inputs=[SCENE_A], output=workspace,
        runid=ATTEMPT, grid=_grid(),
    )
    lock = WriterLock(tmp_path / "state/writer.lock")
    with lock.hold(ATTEMPT):
        outcome = SubprocessAcoliteRunner().run(
            python_executable=settings.acolite.python_executable,
            launcher=settings.acolite.launcher, settings_path=rendered,
            workspace=workspace, timeout_seconds=settings.acolite.timeout_seconds,
            runid=ATTEMPT, lock=lock,
        )
    actual = RunVerifier().verify(
        workspace=workspace, attempt_id=ATTEMPT, platform="S2A",
        release_tag=settings.acolite.release_tag, parameters=parameters.parameters,
        outcome=outcome,
    )
    expected_outcome = FakeAcoliteRunner(FIXTURES, "success").run(tmp_path / "expected")
    expected = RunVerifier().verify(
        workspace=tmp_path / "expected", attempt_id=expected_outcome.runid,
        platform="S2A", release_tag=settings.acolite.release_tag,
        parameters=parameters.parameters, outcome=expected_outcome,
    )

    assert isinstance(actual, AcoliteRunOutputs), actual
    assert isinstance(expected, AcoliteRunOutputs), expected
    assert actual.variables_present == expected.variables_present
    assert actual.variable_units == expected.variable_units
    assert actual.flag_spec == expected.flag_spec
