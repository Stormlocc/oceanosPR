#!/usr/bin/env bash
# Fetch the OCEANOS-owned GSHHG land polygons with a fixed accepted checksum.
set -euo pipefail

readonly GSHHG_URL="https://www.soest.hawaii.edu/pwessel/gshhg/gshhg-shp-2.3.7.zip"
readonly GSHHG_ARCHIVE="gshhg-shp-2.3.7.zip"
readonly GSHHG_SIZE="149157845"
readonly GSHHG_SHA256="8dbbe7e071e77e9e75f2d639239099ebca8d5c16d6a07df8169729d49f15cf41"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly TARGET_DIR="${SCRIPT_DIR}/../data/external/gshhg"
readonly ARCHIVE_PATH="${TARGET_DIR}/${GSHHG_ARCHIVE}"

usage() {
    printf 'Usage: %s [--check]\n' "${0##*/}"
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

verify_archive() {
    [[ -f "${ARCHIVE_PATH}" ]] || fail "GSHHG archive is missing: ${ARCHIVE_PATH}"
    [[ "$(stat -c '%s' "${ARCHIVE_PATH}")" == "${GSHHG_SIZE}" ]] || fail "GSHHG archive size does not match ${GSHHG_SIZE}: ${ARCHIVE_PATH}"
    [[ "$(sha256sum "${ARCHIVE_PATH}" | awk '{print $1}')" == "${GSHHG_SHA256}" ]] || fail "GSHHG archive checksum does not match the pinned SHA-256"
}

verify_members() {
    local extension
    for extension in shp shx dbf prj; do
        [[ -f "${TARGET_DIR}/GSHHS_shp/f/GSHHS_f_L1.${extension}" ]] || fail "GSHHG reference data is missing: ${TARGET_DIR}/GSHHS_shp/f/GSHHS_f_L1.${extension}"
    done
}

check() {
    verify_archive
    verify_members
    printf 'GSHHG reference data check passed.\n'
}

extract_members() {
    local extraction_dir
    extraction_dir="$(mktemp -d "${TARGET_DIR}/.gshhg-extract.XXXXXX")"
    trap 'rm -rf "${extraction_dir}"' EXIT
    python3 - "${ARCHIVE_PATH}" "${extraction_dir}" <<'PY'
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

archive = Path(sys.argv[1])
destination = Path(sys.argv[2])
members = [f"GSHHS_shp/f/GSHHS_f_L1.{extension}" for extension in ("shp", "shx", "dbf", "prj")]

with zipfile.ZipFile(archive) as source:
    invalid_member = source.testzip()
    if invalid_member is not None:
        raise SystemExit(f"GSHHG ZIP CRC failure: {invalid_member}")
    available = set(source.namelist())
    missing = sorted(set(members) - available)
    if missing:
        raise SystemExit(f"GSHHG ZIP is missing required members: {', '.join(missing)}")
    for member in members:
        source.extract(member, destination)
PY
    mkdir -p "${TARGET_DIR}/GSHHS_shp/f"
    local extension
    for extension in shp shx dbf prj; do
        mv "${extraction_dir}/GSHHS_shp/f/GSHHS_f_L1.${extension}" "${TARGET_DIR}/GSHHS_shp/f/"
    done
    trap - EXIT
    rm -rf "${extraction_dir}"
}

fetch() {
    mkdir -p "${TARGET_DIR}"
    if [[ ! -f "${ARCHIVE_PATH}" ]]; then
        local partial_path="${ARCHIVE_PATH}.part"
        rm -f "${partial_path}"
        curl --fail --location --retry 3 --output "${partial_path}" "${GSHHG_URL}"
        mv "${partial_path}" "${ARCHIVE_PATH}"
    fi
    verify_archive
    if [[ ! -f "${TARGET_DIR}/GSHHS_shp/f/GSHHS_f_L1.shp" ]]; then
        extract_members
    fi
    verify_members
    printf 'GSHHG reference data is ready at %s\n' "${TARGET_DIR}"
}

case "${1:-}" in
    --check)
        [[ "$#" == "1" ]] || { usage >&2; exit 2; }
        check
        ;;
    "")
        fetch
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
