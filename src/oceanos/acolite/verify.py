"""Assert ACOLITE CLI success from artifacts, metadata, and logs."""

from __future__ import annotations

import fnmatch
import math
import warnings
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

import rasterio  # type: ignore[import-untyped]

from oceanos.acolite.mapping import Platform, science_wavelengths
from oceanos.acolite.runner import ProcessOutcome
from oceanos.domain import (
    AcoliteRunOutputs,
    AerosolEvidence,
    AncillaryEvidence,
    ArtifactRef,
    FailureCode,
    FailureRecord,
    FailureScope,
    FlagBit,
    FlagSpec,
)

_SKIP_FRAGMENTS = (
    "File not recognised",
    "Multi granule files are no longer supported", "No footprint files found",
    "Longitude/Latitude limits outside", "Longitude limits outside",
    "Time difference too large", "Sensors do not match",
)


def _is_skip_line(line: str) -> bool:
    unsupported_processing = "Processing of" in line and "not supported" in line
    return unsupported_processing or any(fragment in line for fragment in _SKIP_FRAGMENTS)
_FLAG_ROWS = (
    ("swir_threshold", "flag_exponent_swir", "SWIR threshold exceeded", "l2w_mask", True),
    ("cirrus", "flag_exponent_cirrus", "cirrus threshold exceeded", "l2w_mask_cirrus", True),
    ("high_toa", "flag_exponent_toa", "high TOA reflectance", "l2w_mask_high_toa", True),
    ("negative_surface_reflectance", "flag_exponent_negative", "negative surface reflectance", "l2w_mask_negative_rhow", True),
    ("out_of_scene", "flag_exponent_outofscene", "outside source scene", "", False),
    ("mixed_pixel", "flag_exponent_mixed", "mixed-resolution pixel", "l2w_mask_mixed", True),
    ("dem_shadow", "flag_exponent_dem_shadow", "terrain shadow", "l2w_mask_dem_shadow", True),
)


def _artifact(path: Path, workspace: Path, role: str, media_type: str) -> ArtifactRef:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return ArtifactRef(
        role=role, relpath=path.relative_to(workspace).as_posix(), sha256=digest.hexdigest(),
        size=path.stat().st_size, media_type=media_type,
    )


def _settings(path: Path) -> dict[str, str]:
    return {
        key.strip(): value.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
        for key, value in [line.split("=", 1)]
    }


def _truth(value: str | None) -> bool:
    return value is not None and value.lower() == "true"


def _flag_spec(path: Path) -> FlagSpec:
    values = _settings(path)
    bits: list[FlagBit] = []
    usable_mask_value = 0
    for name, exponent_key, meaning, enabled_key, include in _FLAG_ROWS:
        exponent = int(values[exponent_key])
        bits.append(FlagBit(name=name, bit=exponent, meaning=meaning, source_setting=exponent_key))
        if include and _truth(values.get(enabled_key)):
            usable_mask_value |= 1 << exponent
    return FlagSpec(bits=tuple(bits), usable_mask_value=usable_mask_value)


def _inventory(path: Path) -> tuple[tuple[str, ...], dict[str, str | None], dict[str, str]]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(path) as container:
            subdatasets = tuple(container.subdatasets)
    names: list[str] = []
    units: dict[str, str | None] = {}
    tags: dict[str, str] = {}
    for subdataset in subdatasets:
        name = subdataset.rsplit(":", 1)[-1]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
            with rasterio.open(subdataset) as dataset:
                names.append(name)
                units[name] = dataset.units[0]
                if not tags:
                    tags = dataset.tags()
    return tuple(names), units, tags


def _expected_unit(name: str) -> str | None:
    if name.startswith(("rhorc_", "rhow_", "Rrs_")) or name in {"fai", "fait", "ndvi"}:
        return "1"
    if name.startswith("TUR_Nechad2016_"):
        return "FNU"
    if name.startswith("SPM_Nechad2016_"):
        return "g m-3"
    if name == "chl_re_gons740":
        return "mg m-3"
    return None


def _glint_angle(tags: dict[str, str]) -> float:
    sza = math.radians(float(tags["NC_GLOBAL#sza"]))
    vza = math.radians(float(tags["NC_GLOBAL#vza"]))
    raa = math.radians(float(tags["NC_GLOBAL#raa"]))
    cosine = math.cos(sza) * math.cos(vza) + math.sin(sza) * math.sin(vza) * math.cos(raa)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


class RunVerifier:
    """Verify the exact P2 artifacts and build portable output provenance."""

    @staticmethod
    def _failure(
        code: FailureCode, message: str, evidence: list[str], *,
        scope: FailureScope = FailureScope.OBSERVATION, retryable: bool = False,
    ) -> FailureRecord:
        return FailureRecord(
            code=code, scope=scope, stage="verify", message=message, evidence=evidence,
            retryable=retryable, occurred_at=datetime.now(UTC),
        )

    def verify(
        self, *, workspace: Path, attempt_id: str, platform: Platform,
        release_tag: str, parameters: tuple[str, ...], outcome: ProcessOutcome,
    ) -> AcoliteRunOutputs | FailureRecord:
        if outcome.timed_out:
            return self._failure(FailureCode.ACOLITE_TIMEOUT, "ACOLITE exceeded its wall-clock limit", [f"exit_code={outcome.exit_code}"], retryable=True)
        if outcome.exit_code != 0:
            return self._failure(FailureCode.ACOLITE_NONZERO_EXIT, "ACOLITE exited nonzero", [f"exit_code={outcome.exit_code}"], retryable=True)

        log = workspace / outcome.log_path
        try:
            log_lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            log_lines = []
        matched = [line for line in log_lines if _is_skip_line(line)]
        if matched:
            return self._failure(FailureCode.ACOLITE_SKIPPED, "ACOLITE skipped the input", [f"exit_code={outcome.exit_code}", *matched])

        l2r_files = tuple(workspace.glob("*_L2R.nc"))
        l2w_files = tuple(workspace.glob("*_L2W.nc"))
        user_files = tuple(workspace.glob(f"acolite_run_{attempt_id}_l1r_settings_user.txt"))
        resolved_files = tuple(workspace.glob(f"acolite_run_{attempt_id}_l2r_settings.txt"))
        if any(len(files) != 1 for files in (l2r_files, l2w_files, user_files, resolved_files)) or not log.is_file():
            return self._failure(
                FailureCode.ACOLITE_MISSING_OUTPUT, "expected exactly one output of each required kind",
                [f"l2r={len(l2r_files)}", f"l2w={len(l2w_files)}", f"settings_user={len(user_files)}", f"settings_resolved={len(resolved_files)}"],
                retryable=True,
            )
        l2r, l2w, settings_user, settings_resolved = l2r_files[0], l2w_files[0], user_files[0], resolved_files[0]
        try:
            l2r_names, l2r_units, l2r_tags = _inventory(l2r)
            l2w_names, l2w_units, l2w_tags = _inventory(l2w)
            resolved_values = _settings(settings_resolved)
        except (OSError, ValueError, rasterio.errors.RasterioError):
            return self._failure(
                FailureCode.ACOLITE_MISSING_VARIABLE, "output metadata cannot be read",
                ["invalid or incomplete output metadata"],
            )

        version = l2r_tags.get("NC_GLOBAL#acolite_version", "")
        if version != release_tag or l2w_tags.get("NC_GLOBAL#acolite_version") != release_tag:
            return self._failure(
                FailureCode.ACOLITE_VERSION_ATTR_MISMATCH, "NetCDF version attribute does not match pin",
                [f"l2r={version}", f"l2w={l2w_tags.get('NC_GLOBAL#acolite_version', '')}"],
                scope=FailureScope.BATCH, retryable=True,
            )

        def numeric(name: str) -> float:
            return float(l2r_tags[f"NC_GLOBAL#{name}"])

        try:
            ancillary = AncillaryEvidence(
                ancillary_type=resolved_values.get("ancillary_type", "unknown"),
                uoz=numeric("uoz"), uwv=numeric("uwv"), pressure=numeric("pressure"), wind=numeric("wind"),
                fallback_detected=(numeric("uoz"), numeric("uwv"), numeric("pressure"), numeric("wind")) == (0.3, 1.5, 1013.25, 2.0),
            )
        except (KeyError, ValueError):
            return self._failure(
                FailureCode.ACOLITE_MISSING_VARIABLE, "output metadata is incomplete",
                ["invalid or incomplete output metadata"],
            )
        if ancillary.fallback_detected:
            return self._failure(
                FailureCode.ACOLITE_ANCILLARY_FALLBACK, "ACOLITE used default ancillary values",
                ["uoz=0.3", "uwv=1.5", "pressure=1013.25", "wind=2.0"], retryable=True,
            )
        if tuple(resolved_values.get("l2w_parameters", "").split(",")) != parameters:
            return self._failure(
                FailureCode.ACOLITE_MISSING_VARIABLE,
                "resolved settings do not preserve the requested parameter set",
                ["resolved l2w_parameters differ from requested set"],
            )

        required: list[tuple[str, Literal["l2r", "l2w"]]] = [("l2_flags", "l2w")]
        wavelengths = science_wavelengths(platform)
        for parameter in parameters:
            if parameter == "rhorc_*":
                required.extend((f"rhorc_{wave}", "l2r") for wave in wavelengths)
            elif parameter in {"rhow_*", "Rrs_*"}:
                prefix = parameter[:-1]
                required.extend((f"{prefix}{wave}", "l2w") for wave in wavelengths)
            elif parameter == "tur_nechad2016":
                required.append(("TUR_Nechad2016_*", "l2w"))
            elif parameter == "spm_nechad2016":
                required.append(("SPM_Nechad2016_*", "l2w"))
            else:
                required.append((parameter, "l2w"))
        missing = [
            pattern for pattern, level in required
            if not any(fnmatch.fnmatch(name, pattern) for name in (l2r_names if level == "l2r" else l2w_names))
        ]
        if missing:
            return self._failure(FailureCode.ACOLITE_MISSING_VARIABLE, "requested variables are missing", sorted(missing))

        all_units = {**l2r_units, **l2w_units}
        unit_mismatches = sorted(
            f"{name}: expected={expected}, observed={observed}"
            for name, observed in all_units.items()
            if observed is not None and (expected := _expected_unit(name)) is not None and observed != expected
        )
        if unit_mismatches:
            return self._failure(
                FailureCode.ACOLITE_MISSING_VARIABLE,
                "requested variable units do not match the pinned contract", unit_mismatches,
            )

        try:
            aerosol = AerosolEvidence(
                aot550=numeric("ac_aot_550"),
                aerosol_model=l2r_tags["NC_GLOBAL#ac_model"],
                dsf_fit_diagnostics=l2r_tags["NC_GLOBAL#ac_fit"],
            )
            flag_spec = _flag_spec(settings_resolved)
            glint_angle = _glint_angle(l2r_tags)
        except (KeyError, ValueError, OSError):
            return self._failure(
                FailureCode.ACOLITE_MISSING_VARIABLE, "output metadata is incomplete",
                ["invalid or incomplete output metadata"],
            )
        return AcoliteRunOutputs(
            l2r=_artifact(l2r, workspace, "l2r", "application/x-netcdf"),
            l2w=_artifact(l2w, workspace, "l2w", "application/x-netcdf"),
            log=_artifact(log, workspace, "run_log", "text/plain"),
            settings_user=_artifact(settings_user, workspace, "settings_user", "text/plain"),
            settings_resolved=_artifact(settings_resolved, workspace, "settings_resolved", "text/plain"),
            acolite_version_attr=version, aerosol=aerosol,
            variables_present=tuple(sorted(set(l2r_names) | set(l2w_names))),
            l2r_variables=tuple(sorted(l2r_names)),
            variable_units=all_units, flag_spec=flag_spec,
            ancillary=ancillary, glint_angle_deg=glint_angle,
        )
