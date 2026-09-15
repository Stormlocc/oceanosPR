# OCEANOS PR MVP — Implementation handoff

Durable execution record between implementation sessions. Git, PLAN phase tags and tests remain
authoritative; this file records what they cannot.

## State (2026-09-15)

- **Branch:** `feat/oceanos-pr-mvp`.
- **Last completed unit:** Phase 2.2 (ACOLITE adapter, verification, archive), commit
  `Fase 2.2: adaptador ACOLITE, verificación y archivo` on top of `af63ded` (Phase 2.1).
- **Next unit:** Phase 2.3 (conformance, minimal release, runtime probe). Not started.
- **Untracked by design:** `.agents/`.

## Phase 2.2 closure notes

- Implemented by Codex; the agent ran out of context before committing. Claude Code reviewed the
  staged diff, fixed one defect and committed.
- **Defect fixed:** `SettingsRenderer` recomputed `limit` from the grid and ignored
  `OwnedSettings.limit`, so `AcoliteProfile`/`RunKey` could carry a limit ACOLITE never received.
  `oceanos.acolite.settings.limit_for_grid` is now the single derivation (contracts.md, `limit` =
  grid bounds → EPSG:4326 + 1 px); the renderer rejects a profile whose limit differs. Callers in
  2.3 must build `OwnedSettings(limit=limit_for_grid(grid), …)`.
- **Runner environment:** `SubprocessAcoliteRunner` derives `PROJ_DATA`, `GDAL_DATA`,
  `GDAL_DRIVER_PATH` and `PATH` from the configured interpreter prefix and sets `PROJ_NETWORK=ON`.
  No micromamba path is hard-coded in `src/`; the only machine path is `configs/mvp.yaml`.

## Known, pre-existing

- `uv run mypy src` reports 59 errors in modules predating the MVP (`aoi`, `catalog/*`,
  `config/loader`, `processing/*`, `__main__`). Measured identical at `af63ded`, so not a 2.2
  regression. New modules (`acolite`, `domain`, `pipeline`) type-check clean.
- `archive.py` imports private `_boot_id`/`_proc_start_time` from `oceanos.storage`; candidate for a
  public helper when storage is next touched.

## Last verification (Phase 2.2 commit tree)

| Command | Result |
| --- | --- |
| `uv run pytest -q` | 176 passed |
| PLAN 2.2 focused tests (settings, verify, mapping, archive, writer_lock) | 27 passed |
| `uv run pytest -q tests/test_architecture.py` | 4 passed |
| `uv run pytest --run-acolite -q tests/acolite_golden` | 1 passed (real ACOLITE, 19 s) |
| `uv run ruff check src tests` | clean |
| `uv run mypy src/oceanos/acolite src/oceanos/domain.py src/oceanos/pipeline` | clean |

## Exact next action

Start Phase 2.3 with its first item: the pre-flight consumer check for `normalize_band` and
`build_grid`, recorded in the commit message.
