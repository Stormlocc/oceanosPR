# OCEANOS PR MVP — Implementation handoff

Durable execution record between implementation sessions. Git, PLAN phase tags and tests remain
authoritative; this file records what they cannot.

## PAUSED — clean-up applied (2026-09-17)

**Implementation is still deliberately stopped after Phase 3.** On 2026-09-17 the user asked for a
full clean-up of the repository before Phase 4. It is done and verified. **Phase 4 is still the next
unit and still `[TODO]`.** No stage, contract, pinned value, acceptance criterion or phase boundary
moved.

- **Branch:** `feat/oceanos-pr-mvp`. The clean-up is one commit on it.
- **Full record:** PLAN.md, "Resolved after lock (limpieza integral, 2026-09-17)" — eight numbered
  sections, each with the evidence that what was removed was dead.
- **Reader-facing summary:** `README.md`, "Limpieza integral (2026-09-17)".

**The one contract change, authorised by the user:** GSHHG was retired
(`FailureCode.GSHHG_MISSING`, `AcoliteInstallation.gshhg_present`, the `InstallationProbe` check
and parameter, `fetch_reference_data.py gshhg`, and the dead `pyogrio` dependency that only existed
to read its shapefile — `pandas` went with it). This was a Phase 7 item; the user was asked and
chose to pull it forward. The Phase 1 fixture-selection artifacts (`gshhg_clip.geojson`,
`window.json` counts, their tests, the generator's clip step) were **kept on purpose** as frozen
provenance and now say so in their docstrings.

**One thing that needs a decision before Phase 6 runs.** Phase 6 and decision D-5 specify a
*GSHHG* coastline GeoJSON as the viewer's map context. GSHHG is no longer fetched. The recommended
substitute is the **0 m contour of the pinned CUDEM tiles** — already the land mask's own boundary,
so no new dependency and no change to D-5's intent (no external basemap). Recorded in PLAN.md at the
Phase 6 item and on the D-5 row; **not decided.**

**What else changed** (detail in PLAN.md):

| Area | Change |
| --- | --- |
| Dead code | `record_materialization`, `EXCLUDING_FLAGS`, the three module-level `CogProfile`s, `docs/examples/scenes.json`, `tests/test_package.py`, the `data/**/.gitignore` placeholders |
| Duplication | `file_sha256`/`artifact_ref` moved to `oceanos.storage` (was 7 copies); `L1C_COLLECTION`, `layout_for`, the MSI band order, the media types and `MetadataModel` unified |
| Legibility | `__import__("re")` removed, function-local imports hoisted, `_validate_safe` split, `fetch.py`'s `StorageLayout` mutation removed, `domain.py` forward refs reordered, 3 `raise ... from exc` added |
| Public API | `storage._boot_id`/`_proc_start_time` → `boot_id`/`process_start_time`, closing the private-import item below |
| Tooling | ruff widened from the default `E4/E7/E9/F` to 14 rule families at `line-length = 140`; `[tool.pytest.ini_options]` added; `referencing` declared as a dev dependency |
| `.gitignore` | Bug fixed: `catalog/` was also ignoring `src/oceanos/catalog/`. All root patterns anchored |
| Types | `uv run mypy src`: 56 → 22 errors, **all 22 missing third-party stubs**; no real type errors left |
| Docs | `architecture.md` rewritten; frozen-snapshot banners on `SUMMARY.md` and `CURRENT_STATE.md`; the amended Brief decisions (Q5, Q7, Q13) marked; README/CLAUDE.md/design sections synced |
| Quarantine | `.quarantine-20260916/` cut from 2.5 GB to 36 KB; only `aoi-slices-descartadas/` kept, on the user's instruction |

**Verification at this commit:**

| Command | Result |
| --- | --- |
| `uv run pytest -q` | 183 passed (185 before; `test_package.py` and the `extract()` test went with their targets) |
| `uv run ruff check src tests scripts` | clean, at the widened rule set |
| `uv run mypy src/oceanos/acolite src/oceanos/domain.py src/oceanos/pipeline src/oceanos/storage.py src/oceanos/timeseries` | clean, 17 files |
| `uv run mypy src` | 22 errors, all missing third-party stubs |
| `uv run python -m oceanos aoi info --config configs/mvp.yaml` | exit 0 |
| `uv run python scripts/acolite_env.py --check` | exit 0, pin `f73cbe73…` |
| `uv run python scripts/fetch_reference_data.py all --check` | exit 0, 4 CUDEM tiles |
| `git ls-files -i -c --exclude-standard` | empty |

The real ACOLITE probe was **not** re-run: it downloads ~800 MB and runs ACOLITE, and nothing on the
processing path changed. The last real verdicts remain those under "Phase 3 closure record".

**Untracked by design, and still present:** `.agents/`, `data/`, `.work/`, `catalog/`,
`.superpowers/`, `.quarantine-20260916/aoi-slices-descartadas/`, and the user's own in-progress AOI
work (`configs/w2c_south*.yaml`, `configs/aoi/w2c_south*.geojson`, `configs/aoi_other_format/`).
None of it was touched.

**Exact next action:** start Phase 4 by reading its PLAN section; it runs only when the user hands it
over.

## PAUSED (2026-09-16)

**Implementation is deliberately stopped after Phase 3.** The user is pausing to study the codebase
in depth before Phase 4 begins. This is not a blocked or failed state: every phase through 3 is
complete, tagged and verified.

- **Branch:** `feat/oceanos-pr-mvp`, merged into `master` at this point. The OD2 merge gate was
  opened early by the user; Phase 7 keeps its own gate and the branch merges again when the MVP
  finishes. Implementation never happens directly on `master`.
- **Published:** the repository is pushed to the user's GitHub remote. `master` and
  `feat/oceanos-pr-mvp` both exist there; nothing is merged beyond the point described above.
- **Next unit when work resumes:** Phase 4 (index, orchestration, retention, bounded backfill),
  still `[TODO]`, not started. Read its PLAN section first; it runs only when the user hands it over.
- **Legacy retirement was pulled forward** from Phase 7 at the user's request, and `catalog/` is no
  longer versioned. Both are recorded in PLAN.md, "Resolved after lock (legacy retirement pulled
  forward + study pause, 2026-09-16)", with the full evidence table.

**What changed in the working tree at the pause:**

| Change | Detail |
| --- | --- |
| Removed | `src/oceanos/catalog/sentinel2.py`, `tests/test_scenes.py`, `tests/test_normalize.py` |
| Removed | `normalize_band` + `_is_gdal_dataset_name` from `processing/normalize.py`; `build_grid` from `processing/grid.py`; both re-exports from `processing/__init__.py`; `Sentinel2Provider` from `catalog/__init__.py` |
| Changed | `LocalSceneCatalog` default `source_provider` is now `"CdseODataProvider"` (two call sites); `tests/test_local_catalog.py` asserts it |
| Moved | `test_gridspec_rejects_inconsistent_bounds` from `tests/test_normalize.py` to `tests/test_grid.py` |
| Untracked | `catalog/` removed from the index and added to `.gitignore`; the working tree is untouched |
| Docs | this section, the PLAN section named above, the `docs/architecture.md` scope header, the `README.md` status block |

**Verification at the pause:**

| Command | Result |
| --- | --- |
| `uv run pytest -q` | 185 passed (230 before the removals; 45 removed tests) |
| `uv run ruff check src tests scripts` | clean |
| `uv run mypy src/oceanos/acolite src/oceanos/domain.py src/oceanos/pipeline` | clean, 14 files |
| `uv run python -m oceanos aoi info --config configs/mvp.yaml` | exit 0 |

The real ACOLITE probe was **not** re-run for this clean-up: it downloads ~800 MB and runs ACOLITE,
and nothing on the processing path changed. The last real verdicts remain those recorded under
"Phase 3 closure record" below.

**Reading order when work resumes:** this section, then PLAN.md Phase 4, then the design sections
that phase names. The durable execution record is still version control, the PLAN phase tags, the
tests and this file - never chat history.

**Note on the repository root.** `IMPLEMENTATION_HANDOFF.md` at the root is a **pointer only**. It
was a duplicate frozen at Phase 1 while Phases 2.2, 2.3 and 3 updated this file; it was reduced to a
redirect on 2026-09-15. This file, under `docs/topics/oceanos-pr-mvp/`, is the live record.

## State (2026-09-15)

- **Branch:** `feat/oceanos-pr-mvp`.
- **Last completed unit:** Phase 3 (quality, masks, full product set, provenance), commit
  `Fase 3: calidad, máscaras, set completo de productos y procedencia`. DA-6 approved by the user.
- **Next unit:** Phase 4 (index, orchestration, retention, bounded backfill). Not started.
- **Untracked by design:** `.agents/`, `data/`, `.work/`.
- **Operational scripts are Python.** The four `.sh` scripts were removed on 2026-09-15; see the
  section below and PLAN.md, "Resolved after lock (operational scripts in Python)".

## Script refactor (2026-09-15, outside the phase sequence)

The user asked for the repository to hold no bash and for the operational entry points to be as
simple as possible. This changed tooling only: no stage, contract, pinned value or acceptance
criterion moved, and Phase 4 remains the next unit.

| Removed | Replacement |
| --- | --- |
| `scripts/acolite_env.sh` | `scripts/acolite_env.py` (`--check` default, `--install`, `--dry-run`) |
| `scripts/fetch_gshhg.sh` | `scripts/fetch_reference_data.py gshhg [--check]` |
| `scripts/fetch_bathymetry.sh` | `scripts/fetch_reference_data.py bathymetry [--check]` |
| `scripts/probe_run_one.sh` | `scripts/probe_run_one.py` (`--scenes` / `--scene-key` flags) |
| `tests/test_phase1_scripts.py` | `tests/test_scripts.py` (no test spawns `bash`) |

- The ACOLITE pin has one source, `configs/mvp.yaml`; `acolite_env.py --check` reuses
  `InstallationProbe` and adds the clean-checkout rule, the `~/.netrc` mode and machines, and the
  `environment.yml` import check. It creates nothing.
- `probe_run_one.py` drives the CLI in process instead of spawning `uv run` five times.
- `scripts/verify_release.py` and `scripts/make_acolite_fixtures.py` were not touched.

**Verification of this refactor:**

| Command | Result |
| --- | --- |
| `uv run pytest -q` | 230 passed |
| `uv run ruff check src tests scripts` | clean |
| `uv run mypy scripts/*.py src/oceanos` | only the pre-existing missing PyYAML stub, also reported for `config/loader.py:9` |
| `uv run python scripts/acolite_env.py --check` | exit 0, pin `f73cbe73…`, 19 dependencies reported |
| `uv run python scripts/fetch_reference_data.py all --check` | exit 0, GSHHG and the 4 CUDEM tiles match their pinned SHA-256 |

The real probe was **not** re-run for this refactor: it downloads ~800 MB and runs ACOLITE. Records
dated before 2026-09-15 name the former `.sh` paths and are left as written.

## Phase 3 closure record

**Done in the working tree (uncommitted):**
- Research + user decisions recorded in `design/design-threads.md` ("DA-3 / DA-2 — Phase 3 values"):
  CUDEM 1/9″ PR 2022v2, 7 m shallow cut (tur/spm/chl), strict glint gates (neg rhos ≤ 0.10, SWIR p90
  ≤ 0.02), AOT ≤ 0.5, chl published with strong caveat. Research artifact (memory tier):
  `.work/oceanos-pr-mvp/bathymetry-research/RESEARCH.md`; measurements:
  `.work/oceanos-pr-mvp/spikes/phase3_measurements.json`.
- Code: `configs/{quality,publication}.yaml`, `configs/products.yaml` v1, `scripts/fetch_bathymetry.sh`
  (tiles downloaded, checksums pinned from two mirrors), `processing/masks.py` AnalysisMask,
  `processing/quality.py`, `timeseries/`, `publishing/true_colour.py`, `pipeline/downstream.py`
  (P5–P8 from archive), `pipeline/republish.py` + CLI `pipeline republish`, `run_one` refactor,
  loaders, domain types, glint angle moved from `acolite.verify` to an OCEANOS derivation.
- Tests: `test_quality.py`, `test_masks.py`, `test_release_visibility.py`, `test_provenance.py`,
  `test_republish.py`, fixture `tests/fixtures/bathymetry/cudem_window.tif`; 2.2/2.3 tests adapted.
  The `cloudy/` fixture lacks the full product set, so the visibility test injects its real
  `l2_flags` at P5 (documented in the test).
- Untracked by design and not to commit: `catalog/` changes from the probes (user decision pending).

**Last verification:**

| Command | Result |
| --- | --- |
| `uv run pytest -q` | 219 passed |
| `uv run ruff check src tests scripts` | clean |
| strict mypy (acolite, domain, pipeline, timeseries, storage) | clean |
| `uv run pytest --run-acolite -q tests/acolite_golden` | 1 passed |
| `scripts/probe_run_one.sh --force-reprocess` (scene A) + provenance-keys check | exit 0 / ok |
| `SCENE_KEY=scene_d scripts/probe_run_one.sh` | exit 0 |

**Real verdicts:** scene A `rel-69d853c675bdbd36` unusable (residual glint: neg rhos 0.203, SWIR p90
0.052; AOT 0.276) → restricted release. Scene D `rel-c9360406b16324a0` unusable (AOT 0.629, SWIR
0.059, valid fraction 0.055) → restricted release.

**Scene G (2026-09-15 ~21:35 UTC):** `rel-0618349a4f7d239f` usable, public, 8 COGs (AOT 0.055 MOD1,
neg rhos 0.017, SWIR p90 0.0006, tur median 1.46 FNU, valid 0.973; chl valid 0.16).

**DA-1 conflict — RESOLVED with the user (2026-09-15):** GSHHG was displaced ≈ 380 m S / 150 m W
over La Parguera. The user approved the recommendation: `LandMask` v2 and `AnalysisMask` v2 coastal
buffer now derive from CUDEM (elevation > 0 m); recorded as "DA-1 amendment" in
`design/design-threads.md` and noted in the PLAN. Tests updated (fixture window land 539, water
outside buffer 58 481); 219 passed. Releases republished from the archive with
`pipeline republish --range 2026-01-01 2026-12-31` (no ACOLITE, 19 s), all `verify_release` OK:
A `rel-359d2f776a8351b6` restricted, D `rel-ce4029b14157ff75` restricted, G `rel-2f3c296ee79e133c`
public (tur valid 0.974, median 1.48 FNU). AOI land 670 426 px; tur/spm/chl analysis 894 902 px.
Review page updated: https://claude.ai/artifact/AD6sZhVtYFbtcpghGhot6r (Version 2).

**DA-6:** approved by the user (2026-09-15).

**Open items carried to later phases:** `catalog/` changes from probes are uncommitted (user decision
pending); GSHHG fetch script and `env.gshhg_missing` probe check are now unused by the pipeline
(Phase 7 clean-up); SAFE/workspace retention is Phase 4 P9 (≈ 2.3 GB SAFE + work dirs in `data/`).

**Exact next action:** start Phase 4 by reading its PLAN section; it runs only when the user hands it
over.

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

- ~~`uv run mypy src` reports errors in modules predating the MVP~~ **resolved 2026-09-17:** the 22
  remaining errors are all missing third-party stubs (`rasterio`, `shapely`, `yaml`); no real type
  error is left. `publishing` and `processing` are still outside the strict override list, so they
  are checked without `strict = true`.
- ~~`archive.py` imports private `_boot_id`/`_proc_start_time` from `oceanos.storage`.~~ **resolved
  2026-09-17:** both are public (`boot_id`, `process_start_time`).

## Last verification (Phase 2.3 commit tree)

| Command | Result |
| --- | --- |
| `uv run pytest -q` | 197 passed |
| PLAN 2.3 focused tests (conform, land_mask, publish, publish_rollback, pipeline_run_one) | 21 passed |
| `uv run pytest -q tests/test_architecture.py` | 4 passed |
| `scripts/probe_run_one.sh` (real CDSE + ACOLITE) | exit 0 |
| `uv run ruff check src tests scripts` | clean |
| `uv run mypy src/oceanos/acolite src/oceanos/domain.py src/oceanos/pipeline` | clean |
