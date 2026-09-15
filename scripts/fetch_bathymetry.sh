#!/usr/bin/env bash
# Fetch the OCEANOS-owned NOAA NCEI CUDEM bathymetry tiles for the La Parguera AOI with pinned checksums.
#
# Dataset: NOAA NCEI Continuously Updated DEM (CUDEM), 1/9 arc-second Puerto Rico, version 2022v2,
# NAD83 + PRVD02 height (metres, positive up), public domain. NCEI publishes no checksum; the SHA-256
# values below were measured on 2026-09-15 from both the NOAA S3 PDS and the Digital Coast mirror
# (identical bytes). See design/design-threads.md, "DA-3 / DA-2 — Phase 3 values".
set -euo pipefail

readonly S3_BASE="https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/NCEI_ninth_Topobathy_PuertoRico_9525"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly TARGET_DIR="${SCRIPT_DIR}/../data/external/bathymetry/cudem"
readonly TILES=(
    "ncei19_n18x00_w067x00_2022v2.tif 161978725 7b4d211a22104e7f7ef32a5e71a67cbf9403c4dbc9a4b5fdc0be4a51e113d4ed"
    "ncei19_n18x00_w067x25_2022v2.tif 175373802 c5ef52dd3bd102edc0780bd55d110a33d953d8a1bf43dcb0d511636ecb1eb3e4"
    "ncei19_n18x25_w067x00_2022v2.tif 213041389 4f2a1cb5669ee02bcbaaa55ff026750058800257482a26d74d4fd4f032eb0264"
    "ncei19_n18x25_w067x25_2022v2.tif 219311934 5efcd93a1dd900bd0f6cff3c2ac27ff69daf46af52d1ae6ee1d6c40b236d5a18"
)

usage() {
    printf 'Usage: %s [--check]\n' "${0##*/}"
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

verify_tile() {
    local name="$1" size="$2" digest="$3" path="${TARGET_DIR}/$1"
    [[ -f "${path}" ]] || fail "bathymetry tile is missing: ${path}"
    [[ "$(stat -c '%s' "${path}")" == "${size}" ]] || fail "bathymetry tile size does not match ${size}: ${path}"
    [[ "$(sha256sum "${path}" | awk '{print $1}')" == "${digest}" ]] || fail "bathymetry tile checksum does not match the pinned SHA-256: ${name}"
}

check() {
    local entry
    for entry in "${TILES[@]}"; do
        # shellcheck disable=SC2086
        verify_tile ${entry}
    done
    printf 'Bathymetry reference data check passed.\n'
}

fetch() {
    mkdir -p "${TARGET_DIR}"
    local entry name size digest partial
    for entry in "${TILES[@]}"; do
        read -r name size digest <<<"${entry}"
        if [[ -f "${TARGET_DIR}/${name}" ]] && verify_tile "${name}" "${size}" "${digest}" 2>/dev/null; then
            continue
        fi
        partial="${TARGET_DIR}/.${name}.part"
        curl --fail --silent --show-error --location --output "${partial}" "${S3_BASE}/${name}"
        mv "${partial}" "${TARGET_DIR}/${name}"
        verify_tile "${name}" "${size}" "${digest}"
    done
    check
}

case "${1:-}" in
    --check) check ;;
    "") fetch ;;
    -h|--help) usage ;;
    *) usage >&2; exit 2 ;;
esac
