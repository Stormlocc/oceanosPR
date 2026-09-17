# Capability matrix — OCEANOS PR, normalization boundary onward

**Status:** rounds 1–2 resolved · 2026-09-14 · branch `master` @ `07ecca4`
**Scope:** `system` (with data and integration concerns folded in). Written by `/planning:design`
(round 1 followed manually from its SKILL.md before the plugin was installed; round 2 via the installed plugin).

**Inputs:** `../PRD.md`, `../CURRENT_STATE.md`, `../PLAN.md` § Brief (LOCKED, Q1–Q18),
`../research/ACOLITE_TECHNICAL_BASELINE.md`, `.work/oceanos-pr-mvp/publication-architecture/`.
Companion artifacts: [`design-threads.md`](design-threads.md) · [`type-inventory.md`](type-inventory.md) ·
[`contracts.md`](contracts.md) · [`topology.md`](topology.md).

**Boundary.** The processing design starts where the pipeline stops today, at spatial
normalization. Q2's L1C acquisition rework was pulled into this same effort (T22, round 2), so the
upstream layer is fully specified in `contracts.md` §1 (stages A0–A2), with evidence verified live
against CDSE.

---

## 1. Capabilities

Each row is one concern. Status of the owning code: **keep** (exists, unchanged), **extend**
(exists, grows), **reshape** (exists, role changes), **new**, **retire**.

| # | Capability | Domain concepts | Invariants | Storage | Owner | Status |
|---|---|---|---|---|---|---|
| C0 | **L1C discovery & acquisition** | CDSE product, tile candidate, footprint, MD5, SAFE members | L2A is never returned (filter fixed in the adapter). A SAFE is used only after MD5 + member checks; SHA-256 is its identity. | `catalog/`, `data/raw` | `catalog.cdse`, `ingestion` | reshape (T22) |
| C1 | **Overpass planning** | overpass, tile set, datatake, discovery cloud gate, observation | One ACOLITE run per overpass × AOI. Tiles are the minimal footprint cover of the grid (T22b); a set that does not cover the grid, or mixes datatakes, is never processed. | reads scene catalog; writes run ledger | `pipeline` | new |
| C2 | **Processing profile** | ACOLITE install, settings (minimal), product set, quality policy, ancillary tier, delivery grid | Every input to a run that can change the output is inside the profile hash. No path, time or host is. | `configs/` (versioned YAML) | `domain` + `config` | new |
| C3 | **Environment preflight** | release tag, commit SHA, LUTs, credentials, disk budget | No run starts against an ACOLITE whose version or commit differs from the pin. | none | `acolite` | new |
| C4 | **ACOLITE execution** | invocation, workspace, runid, log | Subprocess only (Q1). Exit code is recorded and **never** treated as success (F10). | `data/work/` scratch | `acolite` | new |
| C5 | **Run verification** | expected outputs, skip messages, ancillary evidence, variable presence | Success = expected files ∧ required variables ∧ no skip message ∧ no ancillary fallback ∧ version attribute matches. | reads workspace | `acolite` | new |
| C6 | **Run archive** | L2R, L2W, settings (user + resolved), log, run manifest | Immutable once committed. Committed atomically. Every file checksummed. | `data/archive/` | `pipeline` (via `storage`) | new |
| C7 | **Delivery-grid conformance** | delivery grid, grid id, phase alignment, layer | Every published raster for an AOI version is on **one** grid (PRD "same footprint every date"). Values are never interpolated: aligned → window copy, misaligned → fail. | `data/work/` staging | `processing.normalize` | **reshape** (Q3) |
| C8 | **Quality assessment** | flag spec, valid pixel, valid fraction, range check, usability verdict | Statistics read **full resolution** only. Bit meanings come from the run's resolved settings, not constants. | `quality.json` in release | `processing.quality` | new |
| C9 | **Coastal analysis mask** | CUDEM elevation (DA-1 amendment), coastal buffer, analysis mask | Built once per grid. It excludes pixels from *statistics* only. The published layers keep the coastline (Q8). | `data/products/<aoi>/grid/` | `processing.masks` | new |
| C10 | **Packaging** | COG profile, true-colour view, product asset, provenance record | Float products and the bitfield never share a file (Q16). `l2_flags` overviews use MODE. | `data/work/` staging | `publishing` | new |
| C11 | **Publication** | release, current pointer, derived STAC item, supersession | Releases are immutable. Switching the current release is atomic. The previous release stays readable until its successor is committed (Brief acceptance "WHILE reprocessing"). | `data/products/` | `publishing` | new |
| C12 | **Time-series extraction** | analysis zone, series point, observation status | Gaps are rows with a status, never missing rows. Only pixels valid under C8 and C9 contribute. | `data/state/index.sqlite` | `timeseries` | new (replaces the empty `composites/`) |
| C13 | **Run ledger & index** | attempt, run key, state, failure record | On-disk manifests are the truth. The SQLite index is derived from them and can be rebuilt. | `data/state/` | `index` | new |
| C14 | **Orchestration** | backfill, update, reprocess, writer lock | Single writer, enforced (resolves `CURRENT_STATE.md` §4). A process that crashes can always be resumed. | `data/state/writer.lock` | `pipeline` | new |
| C15 | **Retention** | SAFE discard, workspace cleanup, superseded-release GC | A SAFE is deleted only after the archive commit **and** only when its source id + SHA-256 are recorded (Brief acceptance). | all tiers | `pipeline` | new |
| C16 | **Read API** | observation, series, provenance, operator status | Read-only. It never imports `acolite`, `pipeline` or the writer side of `index`. It never triggers processing (PRD OQ4 default). | reads products + index | `api` | new (package exists, empty) |
| C17 | **Viewer** | map layer, legend, absence, comparison, provenance panel | Contains no science. It never computes a statistic. It renders NaN and flagged pixels differently from clear pixels. | static assets | `web/` | new |
| C18 | **Failure reporting** | failure code, evidence, retryability, operator view | A processing failure and an unusable observation are different outcomes and are never conflated. | ledger + index | `domain` + `index` | new |

## 2. Shared-library vs app-specific

Nothing here is worth extracting into a separate library. The consumer is one deployment, and no
convention home for library organization is bound in this repository. Two capabilities are
**deliberately written to have no I/O**, following the gap `CURRENT_STATE.md` §6 names ("no pure
computational core"):

- **C8 quality math**: flag decoding, valid-fraction and range checks over arrays.
- **C12 zonal aggregation**: statistics over a pixel index.

## 3. What survives from the baseline, and why

| Component | Disposition | Evidence |
|---|---|---|
| `config`, `aoi` | keep; `config` extended | Leaves in the dependency graph, unaffected by ACOLITE (`CURRENT_STATE.md` §9) |
| `SceneProvider`, `SceneMetadata`, `LocalSceneCatalog` | keep; + `CdseODataProvider`, `SceneMetadata` optional L1C fields (T22a, T22e) | Research §11: "KEEP entirely" / "KEEP the provider abstraction" |
| `ingestion.fetch` integrity machinery | keep, regranularized to whole SAFE with MD5 + member checks (T22d) | Research §11: "KEEP the integrity machinery … REMOVE the band-level granularity" |
| `GridSpec`, `metric_crs`, `buffered_aoi`, `assert_aligned` | **keep** | Q3: "survives … `assert_aligned` retained" |
| `normalize_band` | **extend**: NetCDF subdataset source, `int32` categorical input | Its categorical path exists without a caller (`CURRENT_STATE.md` §5); `l2_flags` is `int32`, which is outside its accepted dtypes today |
| `normalize_scene` | **retire / replace** by the conformance stage | Hard-bound to `MVP_BANDS` and to raw band manifests, both invalidated by F3 |
| `build_grid(reference_path, …)` | **retire** once an AOI-anchored grid builder exists (T13, T21) | It anchors each scene to that scene's reference band. The delivery grid must be fixed per AOI version, independent of any scene |
| Staging → verify → backup → `os.replace` → rollback | **keep, extract** into `storage` | Now needed by six stages. `CURRENT_STATE.md` §3.2: "copy this shape verbatim" |
| `composites/` placeholder | **retire** (replaced by `timeseries/`) | PRD non-goals exclude aggregation into composites; the actual need is series extraction (R-D3) |
| `api/`, `publishing/` placeholders | fill | — |
