#!/usr/bin/env bash
# Prepare and validate the ACOLITE installation pinned by the OCEANOS MVP.
set -euo pipefail

readonly ACOLITE_TAG="20260421.0"
readonly ACOLITE_COMMIT="f73cbe73887c2b114d9d3c70865effee73871525"
readonly ACOLITE_REPOSITORY="https://github.com/acolite/acolite.git"
readonly ACOLITE_ROOT="${HOME}/acolite"
readonly ACOLITE_BACKUP="${HOME}/acolite.main-d61c8de"
readonly MICROMAMBA="${HOME}/.local/bin/micromamba"
readonly ACOLITE_ENV="${HOME}/micromamba/envs/acolite"
readonly LUT_DIR="${ACOLITE_ROOT}/data/LUT"

usage() {
    printf 'Usage: %s [--check|--dry-run]\n' "${0##*/}"
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_pinned_checkout() {
    [[ -d "${ACOLITE_ROOT}/.git" ]] || fail "ACOLITE checkout is missing: ${ACOLITE_ROOT}"
    local observed
    observed="$(git -C "${ACOLITE_ROOT}" rev-parse HEAD)"
    [[ "${observed}" == "${ACOLITE_COMMIT}" ]] || fail "ACOLITE commit is ${observed}, expected ${ACOLITE_COMMIT}"
}

check_version_line() {
    local config="${ACOLITE_ROOT}/config/config.txt"
    [[ -f "${config}" ]] || fail "ACOLITE config is missing: ${config}"
    [[ "$(grep -c '^version=20260421\.0$' "${config}")" == "1" ]] || fail "${config} must contain exactly one version=20260421.0 line"
}

check_checkout_status() {
    local status
    status="$(git -C "${ACOLITE_ROOT}" status --porcelain)"
    [[ "${status}" == " M config/config.txt" ]] || fail "ACOLITE checkout must only modify config/config.txt; got: ${status:-clean}"
}

check_luts() {
    [[ -d "${LUT_DIR}" ]] || fail "ACOLITE LUT directory is missing: ${LUT_DIR}"
    find "${LUT_DIR}" -type f -print -quit | grep -q . || fail "ACOLITE LUT directory is empty: ${LUT_DIR}"
}

check_netrc() {
    local netrc="${HOME}/.netrc"
    [[ -f "${netrc}" ]] || fail "credentials file is missing: ${netrc}"
    [[ "$(stat -c '%a' "${netrc}")" == "600" ]] || fail "${netrc} must have mode 600"
    grep -Eq '^[[:space:]]*machine[[:space:]]+earthdata([[:space:]]|$)' "${netrc}" || fail "${netrc} lacks machine earthdata"
    grep -Eq '^[[:space:]]*machine[[:space:]]+cdse([[:space:]]|$)' "${netrc}" || fail "${netrc} lacks machine cdse"
}

check_environment() {
    [[ -x "${MICROMAMBA}" ]] || fail "micromamba is missing: ${MICROMAMBA}"
    [[ -x "${ACOLITE_ENV}/bin/python" || -x "${ACOLITE_ENV}/bin/python3" ]] || fail "ACOLITE environment is missing: ${ACOLITE_ENV}"

    "${MICROMAMBA}" run -p "${ACOLITE_ENV}" python - "${ACOLITE_ROOT}/environment.yml" <<'PY'
from __future__ import annotations

import importlib
import importlib.metadata
import sys
from pathlib import Path

IMPORTS = {
    "python": "sys",
    "pyresample": "pyresample",
    "cartopy": "cartopy",
    "scipy": "scipy",
    "numpy": "numpy",
    "pyhdf": "pyhdf",
    "gdal": "osgeo.gdal",
    "libgdal-jp2openjpeg": "osgeo.gdal",
    "libgdal-netcdf": "osgeo.gdal",
    "netcdf4": "netCDF4",
    "h5py": "h5py",
    "pygrib": "pygrib",
    "requests": "requests",
    "matplotlib": "matplotlib",
    "scikit-image": "skimage",
    "pyproj": "pyproj",
    "zarr": "zarr",
    "fsspec": "fsspec",
    "aiohttp": "aiohttp",
}

dependencies = []
in_dependencies = False
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith("dependencies:"):
        in_dependencies = True
        continue
    if in_dependencies and line and not line.startswith((" ", "\t", "-")):
        break
    stripped = line.strip()
    if in_dependencies and stripped.startswith("- "):
        dependencies.append(stripped[2:].split("=", maxsplit=1)[0])

for dependency in dependencies:
    module = IMPORTS.get(dependency)
    if module is None:
        raise SystemExit(f"No import check mapping for environment dependency: {dependency}")
    importlib.import_module(module)
    if dependency == "python":
        version = sys.version.split()[0]
    else:
        distribution = {"netcdf4": "netCDF4", "scikit-image": "scikit-image"}.get(dependency, dependency)
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = "provided by a conda package"
    print(f"environment dependency: {dependency}={version}")
PY
}

check() {
    require_pinned_checkout
    check_version_line
    check_checkout_status
    check_luts
    check_netrc
    check_environment
    printf 'ACOLITE environment check passed.\n'
}

prepare() {
    if [[ -e "${ACOLITE_ROOT}" ]]; then
        if [[ -d "${ACOLITE_ROOT}/.git" ]] && [[ "$(git -C "${ACOLITE_ROOT}" rev-parse HEAD)" == "${ACOLITE_COMMIT}" ]]; then
            printf 'Using existing pinned ACOLITE checkout: %s\n' "${ACOLITE_ROOT}"
        else
            [[ ! -e "${ACOLITE_BACKUP}" ]] || fail "backup already exists; refusing to overwrite: ${ACOLITE_BACKUP}"
            mv "${ACOLITE_ROOT}" "${ACOLITE_BACKUP}"
            printf 'Preserved prior ACOLITE checkout at %s\n' "${ACOLITE_BACKUP}"
        fi
    fi

    if [[ ! -d "${ACOLITE_ROOT}/.git" ]]; then
        git clone --branch "${ACOLITE_TAG}" "${ACOLITE_REPOSITORY}" "${ACOLITE_ROOT}"
    fi
    require_pinned_checkout

    local config="${ACOLITE_ROOT}/config/config.txt"
    grep -qxF "version=${ACOLITE_TAG}" "${config}" || printf 'version=%s\n' "${ACOLITE_TAG}" >> "${config}"

    if [[ ! -x "${ACOLITE_ENV}/bin/python" && ! -x "${ACOLITE_ENV}/bin/python3" ]]; then
        "${MICROMAMBA}" create --yes --prefix "${ACOLITE_ENV}" --file "${ACOLITE_ROOT}/environment.yml"
    fi
    "${MICROMAMBA}" run -p "${ACOLITE_ENV}" python "${ACOLITE_ROOT}/launch_acolite.py" --retrieve_luts --sensor S2A_MSI,S2B_MSI,S2C_MSI
}

case "${1:-}" in
    --check)
        [[ "$#" == "1" ]] || { usage >&2; exit 2; }
        check
        ;;
    --dry-run)
        [[ "$#" == "1" ]] || { usage >&2; exit 2; }
        printf 'Would prepare ACOLITE tag %s at commit %s.\n' "${ACOLITE_TAG}" "${ACOLITE_COMMIT}"
        printf 'Would preserve %s at %s when it is not already pinned.\n' "${ACOLITE_ROOT}" "${ACOLITE_BACKUP}"
        printf 'Would retrieve Sentinel-2 LUTs in %s.\n' "${ACOLITE_ENV}"
        ;;
    "")
        prepare
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
