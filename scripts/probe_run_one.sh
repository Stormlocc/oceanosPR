#!/usr/bin/env bash
# Real runtime probe: one observation end to end (default scene A; SCENES/SCENE_KEY select another).
#
# Prerequisites (each is checked before anything runs):
#   - uv and the project environment (`uv sync`);
#   - the pinned ACOLITE installation and LUTs (`scripts/acolite_env.sh --check`);
#   - OCEANOS GSHHG data (`scripts/fetch_gshhg.sh --check`);
#   - OCEANOS CUDEM bathymetry tiles (`scripts/fetch_bathymetry.sh --check`);
#   - `~/.netrc` with machines `cdse` and `earthdata`, mode 600;
#   - network access to CDSE (discovery + SAFE download, ~800 MB) and EarthData ancillary;
#   - `.work/oceanos-pr-mvp/spikes/scenes.json` from Phase 1 (scene A date and product name);
#   - writes under `data/` as configured by `configs/mvp.yaml`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SCENES="${SCENES:-.work/oceanos-pr-mvp/spikes/scenes.json}"
CONFIG="${CONFIG:-configs/mvp.yaml}"
SCENE_KEY="${SCENE_KEY:-scene_a}"
RUN_FLAGS=()
case "${1:-}" in
    --force-reprocess) RUN_FLAGS+=(--force-reprocess) ;;
    "") ;;
    *) echo "usage: $0 [--force-reprocess]" >&2; exit 2 ;;
esac

command -v uv >/dev/null || { echo "probe: uv is required" >&2; exit 1; }
[[ -f "$SCENES" ]] || { echo "probe: missing $SCENES" >&2; exit 1; }
[[ -f "$HOME/.netrc" ]] || { echo "probe: missing ~/.netrc" >&2; exit 1; }
scripts/acolite_env.sh --check
scripts/fetch_gshhg.sh --check
scripts/fetch_bathymetry.sh --check

read -r START END OVERPASS < <(uv run python - "$SCENES" "$SCENE_KEY" <<'PY'
import json, re, sys
from datetime import date, timedelta
scene = json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]]
start = date.fromisoformat(scene["ContentDate"]["Start"][:10])
match = re.match(r"^(S2[ABC])_MSIL1C_(\d{8}T\d{6})_N\d{4}_R(\d{3})_", scene["Name"])
if match is None:
    raise SystemExit("probe: cannot derive the overpass id from the scene")
print(start.isoformat(), (start + timedelta(days=1)).isoformat(), f"{match.group(1)}_{match.group(2)}_R{match.group(3)}")
PY
)

echo "probe: overpass $OVERPASS ($START..$END)"
uv run oceanospr grid build --config "$CONFIG"
uv run oceanospr scenes search --start "$START" --end "$END" --config "$CONFIG"
uv run oceanospr pipeline run-one --overpass "$OVERPASS" --config "$CONFIG" "${RUN_FLAGS[@]}"
RELEASE_DIR="$(uv run oceanospr pipeline latest-release --overpass "$OVERPASS" --config "$CONFIG")"
uv run python scripts/verify_release.py "$RELEASE_DIR"
