# OCEANOS PR MVP — Implementation handoff

Durable execution record between implementation sessions. Git, PLAN phase tags and tests remain
authoritative; this file records what they cannot.

## State (2026-09-15)

- **Branch:** `feat/oceanos-pr-mvp`.
- **Last completed unit:** Phase 2.3 (conformance, minimal release, runtime probe), commit
  `Fase 2.3: conformidad, release mínima y probe real`. Phase 2 container is `[DONE]`.
- **Next unit:** Phase 3 (quality, masks, full product set, provenance). Not started.
- **Untracked by design:** `.agents/`, `data/`, `.work/`.

## Phase 2.3 closure notes

- Implemented by Claude Code (explicit hand-off).
- **Pre-flight consumer check:** `normalize_band` and `build_grid` are consumed only by
  `tests/test_normalize.py` (plus the `processing` re-export); `processing` had no
  `catalog`/`ingestion` imports left after 2.1.
- **Real probe passed** (`scripts/probe_run_one.sh`, exit 0) on `S2A_20260702T150741_R082`:
  release `rel-84db141ffe999375`, run key `run-5f7012fae36382be`, full AOI grid 1602 × 1125,
  `grid_coverage_fraction` 1.0 (ACOLITE output phase-aligned on the full AOI, V1 holds),
  758 738 land pixels, median turbidity 4.2 FNU, ancillary `GMAO_MERRA2_MET` (tier final),
  `verify_release.py` OK. The SAFE (801 MB) stays in `data/raw` until P9 exists (Phase 4).
- **Two defects found by the real probe and fixed before commit:**
  1. The default installation probe measured free disk on the not-yet-created `data/work`, so
     `shutil.disk_usage` failed and reported 0 bytes (`env.disk_insufficient`). The work tier is now
     created before measuring. The failed attempt remains in `attempts.jsonl` as `failed`.
  2. Releases were published owner-only (`mkdtemp`/`NamedTemporaryFile` modes). `publish_release`
     now sets directories 0755 and files 0644; the probe release was corrected by hand to match.
- **Decisions within the PLAN (flag if you disagree):**
  - Reconciliation *repairs* only inside `pipeline run-one` (under the writer lock). The other
    mutating commands (`grid build`, `scenes search|acquire`, `catalog add`) and
    `pipeline latest-release` run it read-only and refuse a broken state, because they do not hold
    the writer lock and must not race a publisher.
  - Crash semantics: an uncaught exception during P5–P8 is not recorded as `internal.unexpected`; the
    attempt stays non-terminal and the next run marks it `abandoned` via stale-lock recovery.
    Revisit when Phase 4 adds orchestration retries.
  - Phase 2 placeholders in `DownstreamProfile`: `quality_policy_version="0-hardcoded-usable"`,
    `analysis_mask_version="none"`. `Release.quality` is `None` and the STAC Item omits
    `oceanos:valid_fraction` and `oceanos:scientific_label`; Phase 3 fills them.
  - COG blocksize 256 with `OVERVIEW_COUNT` forced to ≥ 1 so small grids still get an overview.
  - Ancillary tier cut-over is a module constant (`FINAL_ANCILLARY_AFTER = 50 d`, Brief assumption).
- **Observed for Phase 3:** on the real run `l2_flags` has bit 0 (SWIR threshold, informational
  per V8) set on ~99 % of pixels; the quality policy must not treat bit 0 as invalidating.
- **Not done here (later phases):** workspace/SAFE retention (P9), index transaction (Phase 4),
  `true_colour`, `quality.json`.

## Known, pre-existing

- `uv run mypy src` reports errors in modules predating the MVP (`aoi`, `catalog/*`,
  `config/loader`, `processing/*`, `__main__`); `publishing` and `processing` are not in the strict
  mypy override list. Strict modules (`acolite`, `domain`, `pipeline`) type-check clean.
- `archive.py` imports private `_boot_id`/`_proc_start_time` from `oceanos.storage`.

## Last verification (Phase 2.3 commit tree)

| Command | Result |
| --- | --- |
| `uv run pytest -q` | 197 passed |
| PLAN 2.3 focused tests (conform, land_mask, publish, publish_rollback, pipeline_run_one) | 21 passed |
| `uv run pytest -q tests/test_architecture.py` | 4 passed |
| `scripts/probe_run_one.sh` (real CDSE + ACOLITE) | exit 0 |
| `uv run ruff check src tests scripts` | clean |
| `uv run mypy src/oceanos/acolite src/oceanos/domain.py src/oceanos/pipeline` | clean |

## Exact next action

Start Phase 3 by reading its PLAN section and `design/contracts.md` P6/P7 (quality policy, masks,
true colour). Scientific thresholds need user review (PLAN runs Phase 3 in the main session).
