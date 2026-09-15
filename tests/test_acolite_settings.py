"""ACOLITE configuration, profile identity, probe, and rendering contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from rasterio.crs import CRS
from rasterio.transform import from_origin

from oceanos.acolite import InstallationProbe, SettingsRenderer, SubprocessAcoliteRunner
from oceanos.acolite.settings import limit_for_grid
from oceanos.config import (
    ConfigurationError,
    load_acolite_parameter_set,
    load_config,
    load_product_set,
)
from oceanos.domain import (
    AcolitePin,
    AcoliteProfile,
    AncillaryTier,
    OwnedSettings,
    run_key,
)
from oceanos.processing.grid import DeliveryGrid, GridSpec
from oceanos.storage import WriterLock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIN_COMMIT = "f73cbe73887c2b114d9d3c70865effee73871525"
PARAMETERS = (
    "rhow_*", "Rrs_*", "rhorc_*", "tur_nechad2016", "spm_nechad2016",
    "chl_re_gons740", "fai", "fait", "ndvi",
)


def _grid() -> DeliveryGrid:
    transform = from_origin(703_660, 1_987_980, 10, 10)
    return DeliveryGrid(
        grid_id="grid-0123456789ab",
        aoi_id="aoi-la-parguera-0123456789ab",
        spec=GridSpec(
            CRS.from_epsg(32619), 10, (703_660, 1_985_420, 706_220, 1_987_980),
            256, 256, transform,
        ),
        anchor=(0, 0), buffer_m=0, created_at=datetime(2026, 9, 15, tzinfo=UTC),
    )


def _owned(parameters: tuple[str, ...] = PARAMETERS, *, merge_tiles: bool = False) -> OwnedSettings:
    return OwnedSettings(
        limit=limit_for_grid(_grid()), merge_tiles=merge_tiles,
        l2w_parameters=parameters, ancillary_type="GMAO_MERRA2_MET",
    )


def test_mvp_loads_pinned_acolite_and_versioned_product_configs() -> None:
    settings = load_config(PROJECT_ROOT / "configs/mvp.yaml")
    parameters = load_acolite_parameter_set(PROJECT_ROOT / "configs/acolite_parameters.yaml")
    products = load_product_set(PROJECT_ROOT / "configs/products.yaml", parameters)

    assert settings.acolite.release_tag == "20260421.0"
    assert settings.acolite.commit_sha == PIN_COMMIT
    assert settings.acolite.timeout_seconds == 1_200
    assert parameters.version == "1"
    assert parameters.parameters == PARAMETERS
    assert [(spec.product_key, spec.publish) for spec in products.specs] == [
        ("tur_nechad2016", "cog"), ("l2_flags", "cog"),
    ]


def test_product_config_rejects_parameter_outside_render_set(tmp_path: Path) -> None:
    path = tmp_path / "products.yaml"
    path.write_text(
        "version: '0'\nspecs:\n  - product_key: invented\n"
        "    acolite_parameter: invented_algorithm\n    variable_pattern: invented\n"
        "    kind: continuous\n    unit: '1'\n    masked_by_acolite: false\n"
        "    land_masked: false\n    shallow_exclusion_m: null\n"
        "    accepted_range: null\n    display_range: null\n"
        "    s2_calibrated: false\n    publish: cog\n    caveat: null\n",
        encoding="utf-8",
    )
    parameters = load_acolite_parameter_set(PROJECT_ROOT / "configs/acolite_parameters.yaml")

    with pytest.raises(ConfigurationError, match="outside AcoliteParameterSet"):
        load_product_set(path, parameters)


def test_owned_settings_reject_unapproved_or_empty_values() -> None:
    with pytest.raises(ValidationError):
        OwnedSettings(limit=(0, 0, 0, 0), merge_tiles=False, l2w_parameters=(),
                      ancillary_type="GMAO_MERRA2_MET")
    with pytest.raises(ValidationError):
        OwnedSettings(limit=(0, 0, 0, 0), merge_tiles=False, l2w_parameters=PARAMETERS,
                      ancillary_type="GMAO_MERRA2_MET", polygon="x")


def test_parameter_change_changes_profile_and_run_identity() -> None:
    pin = AcolitePin(release_tag="20260421.0", commit_sha=PIN_COMMIT)
    base = AcoliteProfile(
        acolite=pin, settings=_owned(), parameter_set_version="1",
        grid_id="grid-0123456789ab", ancillary_tier=AncillaryTier.FINAL,
        contract_version="1",
    )
    changed = base.model_copy(update={"settings": _owned(PARAMETERS + ("extra",))})

    assert base.profile_id != changed.profile_id
    assert run_key("aoi-x-0123456789ab/S2A_20260702T150741_R082",
                   "inp-0123456789abcdef", base.profile_id) != run_key(
                       "aoi-x-0123456789ab/S2A_20260702T150741_R082",
                       "inp-0123456789abcdef", changed.profile_id,
                   )


def test_renderer_writes_only_owned_and_per_attempt_keys(tmp_path: Path) -> None:
    renderer = SettingsRenderer()
    inputs = [tmp_path / "z.SAFE.zip", tmp_path / "a.SAFE.zip"]
    text = renderer.render(
        _owned(merge_tiles=True), inputs=inputs, output=tmp_path / "workspace",
        runid="att-20260915T120000Z-01234567", grid=_grid(),
    )
    rendered = dict(line.split("=", 1) for line in text.splitlines())

    assert list(rendered) == [
        "inputfile", "output", "runid", "limit", "merge_tiles",
        "extract_inputfile", "s2_target_res", "l2w_parameters",
        "delete_extracted_input", "rgb_rhot", "rgb_rhos",
        "l2w_mask_threshold", "dsf_residual_glint_correction",
        "l2w_mask_water_parameters", "dsf_aot_estimate", "ancillary_type",
        "l1r_delete_netcdf", "netcdf_compression",
    ]
    assert rendered["inputfile"] == f"{inputs[1]},{inputs[0]}"
    south, west, north, east = map(float, rendered["limit"].split(","))
    assert south < 17.9472103 and west < -67.0770034
    assert north > 17.9704856 and east > -67.0526810
    assert rendered["l2w_parameters"] == ",".join(PARAMETERS)
    assert not any("land" in key for key in rendered)


def test_renderer_omits_merge_tiles_for_single_input(tmp_path: Path) -> None:
    text = SettingsRenderer().render(
        _owned(), inputs=[tmp_path / "one.SAFE.zip"], output=tmp_path / "workspace",
        runid="att-20260915T120000Z-01234567", grid=_grid(),
    )
    assert "merge_tiles=" not in text


def test_renderer_rejects_profile_limit_that_differs_from_grid(tmp_path: Path) -> None:
    owned = _owned().model_copy(update={"limit": (0.0, 0.0, 0.0, 0.0)})
    with pytest.raises(ValueError, match="delivery grid limit"):
        SettingsRenderer().render(
            owned, inputs=[tmp_path / "one.SAFE.zip"], output=tmp_path / "workspace",
            runid="att-20260915T120000Z-01234567", grid=_grid(),
        )


def test_probe_reports_pin_version_and_prerequisites(tmp_path: Path) -> None:
    root = tmp_path / "acolite"
    (root / ".git").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config/config.txt").write_text("version=20260421.0\n", encoding="utf-8")
    launcher = root / "launch_acolite.py"
    launcher.write_text("", encoding="utf-8")
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    luts = root / "data/LUT/ACOLITE-LUT-202110"
    for sensor in ("S2A_MSI", "S2B_MSI", "S2C_MSI_V4"):
        (luts / sensor).mkdir(parents=True)
        (luts / sensor / "lut.nc").write_text("x", encoding="utf-8")
    external = tmp_path / "external/gshhg"
    external.mkdir(parents=True)
    (external / "gshhg.zip").write_text("x", encoding="utf-8")
    netrc = tmp_path / ".netrc"
    netrc.write_text("machine earthdata login x password y\n", encoding="utf-8")

    probe = InstallationProbe(commit_reader=lambda _: PIN_COMMIT)
    result = probe.probe(
        pin=AcolitePin(release_tag="20260421.0", commit_sha=PIN_COMMIT),
        root=root, python_executable=python, launcher=launcher, luts_dir=root / "data/LUT",
        external_dir=tmp_path / "external", netrc_path=netrc, disk_path=tmp_path,
        required_disk_bytes=1,
    )

    assert result.observed_commit == PIN_COMMIT
    assert result.config_version_line == "version=20260421.0"
    assert result.luts_present == {"S2A_MSI", "S2B_MSI", "S2C_MSI"}


def test_subprocess_runner_records_child_and_terminates_timed_out_group(tmp_path: Path) -> None:
    launcher = tmp_path / "launch_acolite.py"
    launcher.write_text(
        "import sys, time\nprint('stdout evidence', flush=True)\n"
        "print('stderr evidence', file=sys.stderr, flush=True)\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    settings = tmp_path / "settings.txt"
    settings.write_text("x=y\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    lock = WriterLock(tmp_path / "state/writer.lock")

    with lock.hold("att-20260915T120000Z-01234567"):
        outcome = SubprocessAcoliteRunner().run(
            python_executable=Path(__import__("sys").executable), launcher=launcher,
            settings_path=settings, workspace=workspace, timeout_seconds=0.1,
            runid="att-20260915T120000Z-01234567", lock=lock,
        )
        holder = lock.inspect().holder

    assert outcome.timed_out is True
    assert outcome.log_path == "run.log"
    assert holder is not None and holder.child_pid is not None
    assert holder.child_pid == holder.child_pgid
    assert (workspace / outcome.log_path).read_text(encoding="utf-8").splitlines() == [
        "stdout evidence", "stderr evidence",
    ]


def test_subprocess_runner_activates_geospatial_paths_from_interpreter_prefix(tmp_path: Path) -> None:
    import os
    import sys

    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "share/proj").mkdir(parents=True)
    (prefix / "share/gdal").mkdir()
    (prefix / "lib/gdalplugins").mkdir(parents=True)
    python = prefix / "bin/python"
    python.symlink_to(sys.executable)
    launcher = tmp_path / "launch_acolite.py"
    launcher.write_text(
        "import os\n"
        "print(os.environ.get('PROJ_DATA'))\n"
        "print(os.environ.get('GDAL_DATA'))\n"
        "print(os.environ.get('GDAL_DRIVER_PATH'))\n",
        encoding="utf-8",
    )
    settings = tmp_path / "settings.txt"
    settings.write_text("x=y\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    lock = WriterLock(tmp_path / "state/writer.lock")

    with lock.hold("att-20260915T120000Z-01234567"):
        outcome = SubprocessAcoliteRunner().run(
            python_executable=python, launcher=launcher, settings_path=settings,
            workspace=workspace, timeout_seconds=5,
            runid="att-20260915T120000Z-01234567", lock=lock,
        )

    assert outcome.exit_code == 0
    assert (workspace / "run.log").read_text(encoding="utf-8").splitlines() == [
        os.fspath(prefix / "share/proj"), os.fspath(prefix / "share/gdal"),
        os.fspath(prefix / "lib/gdalplugins"),
    ]
