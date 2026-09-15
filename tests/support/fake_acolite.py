"""Fixture-backed substitute for the external ACOLITE process."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from oceanos.acolite import ProcessOutcome


class FakeAcoliteRunner:
    """Copy one Phase 1 fixture variant into an isolated workspace."""

    def __init__(self, fixture_root: Path, variant: str) -> None:
        self.fixture_root = fixture_root
        self.variant = variant

    def run(self, workspace: Path, *, runid: str | None = None) -> ProcessOutcome:
        source = self.fixture_root / self.variant
        workspace.mkdir(parents=True, exist_ok=True)
        files = tuple(path for path in source.iterdir() if path.is_file())
        log_source = next(path for path in files if path.name.endswith("_log_file.txt"))
        match = re.match(r"acolite_run_(.+)_log_file\.txt", log_source.name)
        assert match is not None
        source_runid = match.group(1)
        selected_runid = runid or source_runid
        for path in files:
            name = path.name.replace(source_runid, selected_runid)
            shutil.copy2(path, workspace / name)
        return ProcessOutcome(
            runid=selected_runid, exit_code=0, duration_seconds=0,
            log_path=f"acolite_run_{selected_runid}_log_file.txt", timed_out=False,
        )
