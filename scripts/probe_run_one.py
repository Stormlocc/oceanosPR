"""Real runtime probe: one observation end to end.

    uv run python scripts/probe_run_one.py [--scene-key scene_a] [--force-reprocess]

Prerequisites, each verified before anything runs:
  - the project environment (``uv sync``);
  - the pinned ACOLITE installation, its LUTs and ``~/.netrc``
    (``scripts/acolite_env.py --check``);
  - the OCEANOS-owned CUDEM reference tiles
    (``scripts/fetch_reference_data.py --check``);
  - ``.work/oceanos-pr-mvp/spikes/scenes.json`` from Phase 1, for the scene to run;
  - network access to CDSE (discovery and a ~800 MB SAFE) and to EarthData ancillary;
  - writes under ``data/`` as configured by ``configs/mvp.yaml``.

The pipeline steps run in process through the OCEANOS CLI, which is the only
orchestrator; nothing here reimplements a stage.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from oceanos.__main__ import main as cli_main
from oceanos.config import load_config
from oceanos.pipeline.run_one import latest_release_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
DEFAULT_CONFIG = REPO_ROOT / "configs/mvp.yaml"
DEFAULT_SCENES = REPO_ROOT / ".work/oceanos-pr-mvp/spikes/scenes.json"
PRODUCT_NAME = re.compile(r"^(S2[ABC])_MSIL1C_(\d{8}T\d{6})_N\d{4}_R(\d{3})_")


def overpass_window(scene: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return the inclusive search window and the overpass id of a recorded scene."""
    match = PRODUCT_NAME.match(scene["Name"])
    if match is None:
        raise ValueError(f"cannot derive the overpass id from {scene['Name']}")
    start = date.fromisoformat(scene["ContentDate"]["Start"][:10])
    return start.isoformat(), (start + timedelta(days=1)).isoformat(), f"{match[1]}_{match[2]}_R{match[3]}"


def script(name: str, *arguments: str) -> int:
    """Run another script in this interpreter's environment."""
    return subprocess.run([sys.executable, str(SCRIPTS_DIR / name), *arguments], check=False).returncode


def cli(arguments: list[str]) -> int:
    """Run one CLI command in process; the CLI reports errors through SystemExit."""
    try:
        return int(cli_main(arguments))
    except SystemExit as exit_signal:
        return int(exit_signal.code or 0)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe and return the first non-zero exit code."""
    parser = argparse.ArgumentParser(description="Run one observation end to end against the real services.")
    parser.add_argument("--scenes", type=Path, default=DEFAULT_SCENES, help="scenes.json recorded in Phase 1")
    parser.add_argument("--scene-key", default="scene_a", help="key of the scene to run")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="OCEANOS configuration file")
    parser.add_argument("--force-reprocess", action="store_true", help="rerun ACOLITE for an already processed overpass")
    args = parser.parse_args(argv)

    config = str(args.config)
    for status in (
        script("acolite_env.py", "--check", "--config", config),
        script("fetch_reference_data.py", "all", "--check", "--config", config),
    ):
        if status:
            return status

    if not args.scenes.is_file():
        print(f"probe: missing {args.scenes}", file=sys.stderr)
        return 1
    scenes = json.loads(args.scenes.read_text(encoding="utf-8"))
    if args.scene_key not in scenes:
        print(f"probe: {args.scenes} has no scene {args.scene_key}", file=sys.stderr)
        return 1

    start, end, overpass = overpass_window(scenes[args.scene_key])
    print(f"probe: overpass {overpass} ({start}..{end})")

    run_one = ["pipeline", "run-one", "--overpass", overpass, "--config", config]
    if args.force_reprocess:
        run_one.append("--force-reprocess")
    for command in (
        ["grid", "build", "--config", config],
        ["scenes", "search", "--start", start, "--end", end, "--config", config],
        run_one,
    ):
        status = cli(command)
        if status:
            return status

    release_dir = latest_release_dir(load_config(args.config), overpass)
    return script("verify_release.py", str(release_dir))


if __name__ == "__main__":
    raise SystemExit(main())
