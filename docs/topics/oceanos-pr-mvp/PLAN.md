# OCEANOS PR — ACOLITE MVP

## Brief

**Status:** LOCKED (user-confirmed) · 2026-09-12 · *revised 2026-09-12: ancillary-latency constraint added after empirical verification* · baseline `acc6072`
`acceptance_criteria_format`: **free-text** (default — no convention home bound in this repository)

### TLDR

Replace the L2A/COG-band acquisition with complete Sentinel-2 **L1C SAFE** acquisition, run
**ACOLITE 20260421.0** as a subprocess to produce water-quality and floating-algae products over an
ocean-only AOI, and publish them with per-pixel quality and full provenance. Fase 5's grid discipline
survives as a post-ACOLITE delivery-grid step; Fases 2–4's integrity machinery survives with its
granularity changed from bands to whole products.

### Goal

A marine researcher can answer a water-quality or sargassum question about the La Parguera study
area across a date range, without operating the pipeline, and can trace any displayed value back to
its scene, processing version and parameters.

### Constraints

- **Hardware:** one mid-to-high-range CPU machine. No GPU, no cluster. Scaling is far-future.
- **ACOLITE pinned to `20260421.0`** (commit `f73cbe73887c2b114d9d3c70865effee73871525`), invoked as
  a **subprocess** with a minimal settings file, one process per scene. Never imported as a library
  in production (GPLv3 coupling; §10.3 of the technical baseline).
- **Input is a complete L1C `.SAFE`** — one granule, all 13 bands, `MTD_MSIL1C.xml`,
  `GRANULE/<g>/MTD_TL.xml` and `QI_DATA/MSK_DETFOO*` intact. No band subsetting, no re-packing, no
  upstream reprojection, resampling, clipping, or DN→reflectance scaling.
- **ACOLITE owns** clipping (`limit`/`polygon`), resampling (`average`), reprojection, masking,
  flagging and all product algorithms. OCEANOS must not duplicate them upstream.
- **ACOLITE exits 0 on failure.** Success is asserted from expected output files **plus** a scan of
  the run log for known skip messages — never from an exit code.
- **`l2w_parameters` must be set explicitly**; its default `None` silently produces no L2W file.
- **Settings files stay minimal** — writing every key defeats ACOLITE's sensor-default layer.
- **The AOI spans at least two tile columns**; `merge_tiles=True` is required, same orbit and
  datatake, tiles ≤600 s apart.
- **EarthData credentials** (OB.DAAC + LP DAAC approved) via `~/.netrc`. Without them ACOLITE
  silently substitutes default atmospheric values.
- Python 3.11; `extra="forbid"` on all config models; single writer per catalogue and per scene.
- **Ancillary atmospheric data has a ~40-60 day latency.** Measured empirically 2026-09-12:
  `GMAO_MERRA2_MET` returns data for 2026-07-10 (64 d) and 2026-06-15 (89 d) but **fails for
  2026-08-04 (39 d)**, returning an empty result **without raising**. `GMAO_IT_MET` (near-real-time)
  **does** return data for 2026-08-04. ACOLITE's own `ancillary_aerosol_nrt_days=50` marks the same
  boundary for aerosols. **Therefore `ancillary_type` must be selected by scene age**, not left at
  its default, or recent scenes silently fall back to `uoz_default`/`uwv_default`/`pressure_default`.
  Without this, **PRD metric M3 (<=7 days acquisition-to-viewer) is unachievable at full quality.**

### Locked decisions

| # | Decision |
|---|---|
| Q1 | ACOLITE invoked as a **subprocess** with a settings file, one process per scene |
| Q2 | **OCEANOS acquires** the SAFE; discovery retargeted to CDSE OData for full L1C products |
| Q3 | Fase 5 grid/normalization **survives**, reduced to a post-ACOLITE delivery-grid step; `assert_aligned` retained |
| Q4 | Products: `rhow_*`, `Rrs_*`, `rhorc_*`, `tur_nechad2016`, `spm_nechad2016`, `chl_re_gons740`, `fai`, `fait`, `ndvi` |
| Q5 | Two usability gates: scene-level cloud at discovery + `l2_flags == 0` per pixel; publish only above an AOI valid-fraction threshold |
| Q6 | Work lives on branch `master`, cut fresh at `acc6072` and renamed over the old one. **Revised 2026-09-12:** the rejected Fase 6/7 commits were deliberately left unreachable rather than preserved — the user chose to let them be garbage-collected. **Superseded 2026-09-14 by OD2 for branch strategy only:** `master` stays the baseline (the Fase 5 lineage, Fase 6/7 still abandoned). `feat/oceanos-pr-mvp` is created from `master`, all implementation happens on it, and it merges into `master` only in Phase 7 behind the user gate. |
| Q7 | Land/sea split by **geometric GSHHG mask** (`ac.masking.land_water_mask`), decoupled from the SWIR threshold, which rises to `0.05` for cloud/bright-target duty only |
| Q8 | Coastal buffer is **layered**: exclude ~100–200 m from analysis (adjacency), retain the coastline in visualisation |
| Q9 | `dsf_aot_estimate=fixed` — the AOI is too small to give the tiled DSF enough valid tiles |
| Q10 | Discard the SAFE after successful processing; `l1r_delete_netcdf=True`; keep L2R + L2W + manifests indefinitely |
| Q11 | `merge_tiles=True` with `limit`; no upstream mosaicking |
| Q12 | Revise the AOI boundary before backfill; fit inside 19QFV if scientifically defensible |
| Q13 | ~~Sun-glint correction **off**~~ **Amended 2026-09-14 (V8): residual glint correction ON**; record the glint angle as metadata |
| Q14 | Request `rhorc_*` so literature-native FAI stays computable without reprocessing |
| Q15 | Add `version=20260421.0` to the **deployment** `config/config.txt`, and record the git commit SHA in our own run manifest |

### Acceptance criteria

- Discovery returns only Sentinel-2 **L1C** products; an L2A product never reaches ACOLITE.
- An acquired product is a complete, unmodified `.SAFE` whose required metadata files are present and verified before processing begins.
- Every acquired product is recorded with its source id and a checksum sufficient to re-fetch it deterministically after the SAFE is discarded.
- A scene whose AOI spans several tiles is processed by a single ACOLITE run over the merged tiles, not by mosaicking separate outputs.
- Every published product carries: source scene id, ACOLITE version, ACOLITE commit SHA, the resolved settings, and the processing timestamp.
- Land pixels are excluded from every published water product by the geometric coastline mask, and turbid water is never classified as land by a reflectance threshold.
- Every published product is accompanied by its per-pixel `l2_flags`, and the per-AOI valid-pixel fraction is computed from those flags rather than from any scene-level number.
- The viewer distinguishes *no usable observation* from *observed and clear*; the two are never visually equivalent.
- A researcher can select an area and a date range and obtain a time series without operator involvement.
- The same location resolves to the same spatial footprint on every date.
- **IF** atmospheric correction fails, or its output falls outside the accepted range, **THEN** the product is not published as usable and the reason is recorded and visible to the operator.
- **IF** a tile required by a merge is missing or belongs to a different orbit or datatake, **THEN** no partial AOI product is published.
- **WHILE** a scene is being reprocessed, the previously published version remains available and complete.
- A processing run that ACOLITE skips is detected and reported as a failure despite its zero exit code.

### Captured assumptions

- The coastal exclusion buffer starts at ~100–200 m and is fixed empirically after the bounded backfill. **Revisit trigger:** the first backfill that yields a measurable adjacency signal, or a researcher reporting lost nearshore coverage.
- The AOI valid-pixel-fraction publication threshold starts at 20% and is tuned after the bounded backfill.
- The scene-level cloud threshold at discovery is set empirically from the bounded backfill rather than chosen now.
- `limit_buffer` is left unset initially; `dsf_aot_estimate=fixed` removes the tile-count pressure that would otherwise motivate it.
- The SAFE is handed to ACOLITE as a `.zip` with `extract_inputfile=True`; disk is budgeted for zip plus expansion during the run.
- ~~GSHHG must be downloaded once into ACOLITE's `external_dir` before first use.~~ *Superseded by the Q7 amendment (DA-1):* GSHHG is downloaded into OCEANOS `data/external/gshhg/` and applied by OCEANOS.
- LUTs are pre-fetched at environment-build time (`--retrieve_luts --sensor S2A_MSI,S2B_MSI,S2C_MSI`).
- `ancillary_type` switches to `GMAO_IT_MET` for scenes younger than ~50 days and `GMAO_MERRA2_MET` beyond that; the exact cutover day is assumed to be 50, matching ACOLITE's own aerosol NRT boundary. **Revisit trigger:** any scene whose ancillary fetch returns empty.
- - S2C is assumed supported for the core chain (verified in code) though the release manual's per-algorithm sensor lists omit it.

### Out of scope

- Real-time or near-real-time sargassum alerting.
- Public access; the deployment is internal with named authenticated users.
- Coral reef / benthic habitat products.
- Validation against in-situ measurements.
- Re-implementing any ACOLITE algorithm, or reviving the rejected Fase 6/7 code.
- Landsat or any sensor other than Sentinel-2 MSI.
- Sargassum biomass estimation, sub-pixel unmixing, drift tracking, and multi-date event aggregation — ACOLITE stops at the index, and the MVP stops there too.
- Importing ACOLITE as a library in production.

### Resolved after lock (publication-architecture research, 2026-09-12, gates clean)

- **Q16 — Delivery format, and how `l2_flags` travels.** **NetCDF stays the archive** (it alone
  carries the CF metadata); **COG is the publication format**. The flag band **must be a separate
  single-band COG** built with `MODE` or `NEAREST` overviews. Reason, measured not assumed: GDAL's
  COG driver defaults `OVERVIEW_RESAMPLING` to **CUBIC**, which fabricates flag combinations that
  never occurred; and a COG carries **one** predictor and **one** overview-resampling choice per
  file, so Float32 products (`PREDICTOR=3`, cubic/average) and an int32 bitfield (`PREDICTOR=2`,
  mode/nearest) **cannot correctly share a file**. Verified empirically by range-reading Element84's
  live Sentinel-2 `SCL.tif` for **19QFV — our own AOI tile** — and decoding a full-resolution tile
  against its overview: in 52/52 blocks where mode and average disagree, the overview took a parent
  value, never the average. Digital Earth Australia states the same, with the caveat that binds:
  **mode loses rare classes, which is exactly what a flag band is for.**
  **Invariant: overviews are display-only; every statistic reads full resolution.**
- **Q17 — STAC shape and visualisation stack.** **STAC 1.1.0** core; `classification:bitfields`
  models `l2_flags` exactly (its canonical example is Landsat's QA raster); `processing:` v1.2.0
  carries the ACOLITE version, commit SHA and timestamp. A **static catalog is viable** here, at the
  cost of the `/search` endpoint. **No tile server in the MVP** — geotiff.js reads our COGs directly
  over HTTP range requests, Float32 and floating-point predictor included.
- **Time series must be pre-extracted, not read per request.** Measured on this machine class:
  500 per-scene 512x512 Float32 DEFLATE tiles cost **2606 ms** and decompressed **500 MiB** to
  return **2000 bytes**; the same series from an indexed SQLite table took **1.09 ms** — ~2400x.
  The cost is structural (a whole tile decompresses to read one pixel), so a faster tile server does
  not fix it.
- **Landsat forecloses nothing.** Collection 2 already ships as COG with a bit-packed QA band,
  already publishes through a STAC API, and is the canonical example in the extension recommended
  for `l2_flags`.
- **Rejected as wrong for this deployment, with reasons:** **Zarr** (Unidata measured 2000+ files vs
  2 netCDF for the same data; the benefit is object storage we do not have), **GeoZarr** (no released
  spec exists — its own repository says one "will be produced" later), and **a tile server in the MVP**.

### Deferred questions

*None. Every question raised by the interview and by the publication-architecture research is
resolved. The Brief is complete.*

### Resolved after lock (continued)

- **Q18 — Attaching the resolved ACOLITE settings to a STAC Item.** **Accepted:** a
  `processing-software` link plus a **metadata-role asset** carrying the resolved settings file.
  This is an explicit workaround: the `processing` extension v1.2.0 has **no typed field** for a
  settings file, so the Brief's "every published product carries the resolved settings" criterion is
  satisfied by an asset reference rather than a spec field. Recorded as a workaround, not as spec
  conformance, so a future `processing` version that adds the field can replace it cleanly.
- **Amendment 2026-09-14 — Q11 and the constraint "The AOI spans at least two tile columns;
  `merge_tiles=True` is required" are superseded** (design round 2, T22b, user-confirmed).
  - **Evidence.** The live CDSE OData catalogue for L1C over the configured AOI, 2026-06-01 →
    2026-09-01, shows 92 products and 23 overpasses, all on R082. Tile `19QGV` alone contains the
    AOI on 23/23 overpasses (`19QFV` covers 54%). The original constraint was derived from Earth
    Search L2A bands for `19QFA`/`19QFV`.
  - **New rule.** Per overpass, select the minimal set of tile footprints whose union contains the
    delivery grid. `merge_tiles=True` is written only when more than one tile is selected.
  - **What still holds.** The acceptance criterion "no partial AOI product" still holds, now read
    as "the selected footprints must cover the grid". Multi-tile merge remains supported for AOIs
    that need it.
  - **Q12.** The engineering motive (avoid multi-tile) is met by the current AOI. The scientific
    boundary review (PRD OQ8) stays open before backfill.
  - Detail: `design/design-threads.md` §H, `design/contracts.md` §1.
- **Amendment 2026-09-14 — Q7 is amended** (design round 3, DA-1, user-confirmed).
  - **Evidence.** At tag `20260421.0`, `ac.masking.land_water_mask` is never called by any
    processing path; its only reference is `masking/__init__.py:3`.
  - **New rule.** The geometric GSHHG land mask is built and applied by **OCEANOS** at the conform
    stage: water products are set to NaN on land. `l2w_mask_threshold` stays `0.05` for cloud and
    bright-target duty.
  - **Unchanged.** The acceptance criteria "land excluded from every published water product" and
    "turbid water never classified as land by a reflectance threshold" are unchanged.
  - **Published values.** Published water-product values equal ACOLITE's except on masked land.
  - Detail: `design/design-threads.md` §I.
- **Amendment 2026-09-14 — Q13 and the role of Q7's SWIR threshold are amended** (V8, user-confirmed).
  - **Evidence** (`design/design-threads.md` V8 rows; `.work/oceanos-pr-mvp/spikes/v8_measurements.json`).
    - With the pinned settings, ACOLITE's TOA SWIR non-water flag (bit 0) covered ~99 % of the water
      on the observed summer scenes, and blanked the water products.
    - Run F (residual glint correction + `l2w_mask_water_parameters=False`) brought `rhow_1614` over
      water from median 0.031 to 0.000, and left 79.6 % of the water valid under the new predicate.
    - Run G (2026-01-06, sun zenith 45°) had bit 0 on 0.7 % with the old settings, confirming
      summer glint as the cause.
  - **New rules.**
    - `dsf_residual_glint_correction=True` (method `default`, 1500–2400 nm).
    - `l2w_mask_water_parameters=False`.
    - `l2w_mask_threshold` stays `0.05`, but **bit 0 is informational only**. It never excludes a
      pixel and never blanks a product.
    - Land stays OCEANOS's `LandMask` (DA-1). Cloud comes from cirrus + high-TOA flags (dilated).
  - **Valid pixel (DA-2, amended):** GSHHG water outside the coastal buffer (and the per-product
    shallow exclusion from Phase 3) ∧ cirrus, high-TOA and negative-rhos flags == 0 (bit names from
    `FlagSpec`) ∧ cloud flags dilated by `cloud_dilation_px` ∧ product finite (`_FillValue` → NaN).
  - **Recorded risks, reviewed at the DA-6 gate:**
    - Run F raised negative-rhos (bit 3) coverage by 20 percentage points of the water.
    - It shows speckled high turbidity offshore in the south-east, likely residual glint or wave
      facets.
  - **OD5 unchanged.** The backfill stays 2026-06-01 → 2026-08-31.

## Plan

**Status:** APPROVED FOR IMPLEMENTATION 2026-09-14 (rev 4, final; user: "aprobado") · produced by `/planning:plan`. Every planning gate is closed. Implementation starts at Phase 0 on branch `feat/oceanos-pr-mvp`.
**Scope:** "completar oceanos-pr-mvp desde el límite de normalización actual hasta la visualización"
**Rev 2:** incorporates the fresh-context plan review (28 findings, all verified against files).
**Rev 3:** incorporates `/planning:devils-advocate` iteration 1 (23 findings) and design round 3 (DA-1…DA-6).
**Rev 4:** incorporates `/planning:devils-advocate` iteration 2 (B1–B16, verified against the tag source).

### Goal

**What.** Take OCEANOS PR from its current end point (Fase 5 normalization of L2A bands) to an
internal viewer, passing through:

- L1C SAFE acquisition from CDSE;
- ACOLITE `20260421.0` run as a subprocess;
- a verified archive and delivery-grid conformance;
- quality gating;
- immutable releases with full provenance;
- a derived static STAC catalog;
- a SQLite index with time series;
- a read-only API and a Leaflet viewer.

**Why.** PRD Goal 1: a marine researcher answers a water-quality or sargassum question without
operating the pipeline. PRD Goal 2 and M4: every displayed value traces back to its scene,
processing version and parameters.

### Inputs this plan consumes (not re-derived)

| Input | Role |
|---|---|
| § Brief above (LOCKED + amendments under "Resolved after lock") | constraints, acceptance criteria |
| `design/design-threads.md`: T1–T26, T22a–f and DA-1…DA-6 resolved; handoff gate PASS 2026-09-14 | every design decision with its rationale |
| `design/contracts.md` | stages A0–A2 and P0–P9, ports, data contracts, lineage, failure codes, API, CLI status shape, viewer boundary |
| `design/type-inventory.md` · `design/topology.md` | identities, types, packages, import rules A1–A4, storage layout |
| `PRD.md` §5 (metrics), §8 (viewer), §11 (rollout) | phase ordering, measurement |
| **Decisions made** (below): OD1–OD6 were user-accepted 2026-09-14; D-1…D-9 were passed by the planner and are open to override | execution choices |

### Standards grounding

**No standards index exists.** None of `.claude/standards.yaml`, `docs/standards/`,
`~/.claude/standards/`, `AGENTS.md` or `CLAUDE.md` is present. Following ladder rung 4, the grounding
below is **inferred from repository context**:

| Surface | Source loaded | Layer |
|---|---|---|
| Python house patterns: adapter boundary, atomic publish, verify-then-use, never invent values, versioned artifacts, `extra="forbid"` | `CURRENT_STATE.md` §3, §4 | team (inferred) |
| Test conventions: `httpx.MockTransport`, `no_network` fixtures, opt-in collection hook | `tests/conftest.py`, `CURRENT_STATE.md` §2.12 | team (inferred) |
| Phase commit style: one self-contained commit per phase plus a README "Fase N" section | `git log`, `README.md` | team (inferred) |
| Toolchain: Python 3.11, `uv`, `uv_build`, pytest | `pyproject.toml` | team (inferred) |

This inference has **not** been persisted as `docs/standards/README.md`. That can be done with
`/planning:setup` if wanted.

### Decisions made

#### User-accepted Open Decisions (2026-09-14)

| # | Decision | Effect on this plan |
|---|---|---|
| OD1 | Feasibility spikes (V1, V2, V3, V6, V7) run **inside** the plan, as Phase 1, with halt gates | Phase 1 exists; Phase 2+ build on its recorded outcomes |
| OD2 | Work on branch `feat/oceanos-pr-mvp` cut from `master`, with one commit per (sub-)phase | Phase 0 creates the branch; Phase 7 merges it back to `master`, behind a user gate |
| OD3 | `ruff` + architecture test + `mypy` on new packages only; no CI (no remote) | Phase 0 tooling; every phase's Sanity Check runs ruff + the full suite |
| OD4 | Viewer is verified by pure-module design + a manual acceptance checklist; no browser automation (no Node) | Phase 6 checklist and static checks |
| OD5 | Bounded backfill covers **2026-06-01 → 2026-08-31** | Phase 4 operational run |
| OD6 | Phase order: env/spikes → tracer bullet → quality → orchestration + backfill (**gate**) → API → viewer → update/cleanup | Phases 1–7 |

#### Planner-passed decisions (D-#; see the gate-passed table under "Handoff to implementation")

These carry the tags `[EXEC-SHAPE]` or `[FALLBACK]` in the phase bodies.

### Brief acceptance → phase map

| Brief acceptance criterion | Phase |
|---|---|
| Discovery returns only L1C; L2A never reaches ACOLITE | 2.1 |
| Acquired product is a complete, unmodified, verified SAFE | 2.1 |
| Source id + checksum recorded so the product can be re-fetched after SAFE deletion | 2.1, 4 (retention + re-acquisition) |
| ~~Multi-tile AOI processed by one merged run~~ **Amended (T22b):** the selected footprints cover the grid, and merge happens only when >1 tile is selected | 2.1 (selection), 2.2 (settings) |
| Published product carries scene id, ACOLITE version, commit SHA, resolved settings and timestamp | 2.3 (minimal), 3 (complete `ProvenanceRecord`) |
| Land excluded by the geometric coastline mask; turbid water never classified as land | 1 (GSHHG fetch), 2.3 (`LandMask` applied at conform, DA-1), 2.2 (SWIR threshold 0.05 for cloud only) |
| Per-pixel `l2_flags` travel with every product; valid fraction computed from the flags | 2.3 (flags COG), 3 (fraction) |
| Viewer distinguishes "no usable observation" from "observed and clear" | 6 |
| Researcher obtains a time series without operator involvement | 4 (extraction), 5 (API), 6 (UI) |
| Same location → same footprint on every date | 2.1 (delivery grid) + 2.3 (`assert_aligned`) |
| AC failure or out-of-range output → not published as usable, with the reason visible | 3 (verdict), 4 (operator status), 6 |
| Missing tile or different datatake → no partial product | 2.1 |
| Previous version stays available while reprocessing | 4 (supersession + rollback test) |
| Skipped ACOLITE run detected despite exit 0 | 2.2 |

| PRD §8 MVP viewer capability | Phase 6 item |
|---|---|
| Map view with usability mask distinguishable | map + `states.js` |
| Date navigation including dates without a usable observation | `dates.js` |
| Area selection: **point** or region | point click, zone picker, drawn polygon |
| Time series with gaps shown as gaps | series chart |
| Side-by-side date comparison | comparison view |
| Provenance panel | provenance panel |
| Value inspection with unit | `/value` |
| Operator status view | operator view |

**Every phase ends with the same baseline checks, in addition to its own:**

- `uv run pytest -q` exits 0 (**full suite**, not only new files);
- `uv run ruff check src tests` exits 0;
- the README gains that phase's "Fase N" section (house style).

---

### Phase 0: Branch, hygiene, tooling [DONE]

A small horizontal prerequisite, about 150 LOC.

- [x] **Branch.** Create `feat/oceanos-pr-mvp` from `master`. Its first commit holds
  `docs/topics/oceanos-pr-mvp/design/`, `PLAN.md` and `.claude/settings.json`; the only diff in
  that file is `enabledPlugins`, verified. **`.agents/` is not committed** (untracked by rule
  for this plan; see Open questions).
- [x] **Console script.** Set `pyproject.toml` `oceanospr = "oceanos.__main__:main"`
  (`CURRENT_STATE.md` §2.14).
- [x] **Stale build output.** Delete the untracked `src/nasa_oceanos_pr.egg-info/` directory from
  disk. `.gitignore` already ignores it.
- [x] **Dependencies.** Remove `pandas`. Nothing imports it, and the series use SQLite (T8).
- [x] **`.env.example`.** Replace the `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` lines with a
  comment: credentials live in `~/.netrc` (machines `earthdata`, `cdse`).
- [x] **Dev tools (OD3).** Add `ruff` and `mypy` to the dev group, configured in `pyproject.toml`.
  Fix whatever ruff reports on the existing ~1 400 LOC; a `ruff format` pass goes in its own
  structural commit. `mypy` strict applies to the new packages only as they appear.
- [x] **`tests/test_architecture.py` (D-7).** Enforces A1–A3 as an **AST import scan** and A4 as a
  **string-literal scan**.
  - A4 matches only **`key=` patterns** for ACOLITE-owned setting keys (e.g. `l2w_parameters=`,
    `dsf_aot_estimate=`), skip-message fragments, and the wavelength-suffixed variable regex
    `\b(rhow|Rrs|rhos|rhot|rhorc)_\d{3,4}\b`. Bare words such as `limit` or `output` are not
    scanned, to avoid false positives.
  - Allow-listed: `oceanos/acolite/**`, `configs/products.yaml`, `tests/**`, and the shared key
    `l2_flags`.
  - It enforces A1–A4 only, **not** the full "may import" table. `processing/normalize.py`
    importing `catalog`/`ingestion` is tolerated until 2.3 removes it.

**Sanity Check:**

- `uv run oceanospr --help` exits 0.
- `test ! -d src/nasa_oceanos_pr.egg-info` exits 0.
- `grep -c '"pandas' pyproject.toml` prints `0`.
- `uv run ruff check src tests` exits 0.
- `uv run pytest -q` exits 0 with ≥138 passed (137 existing + the architecture test).
- `git branch --show-current` prints `feat/oceanos-pr-mvp`.
- `git ls-files .agents | wc -l` prints `0`.

### Phase 1: ACOLITE environment and feasibility spikes [DONE]

Resolves V1, V2, V3, V6 and V7 **before** any code depends on them (OD1). Produces the real fixtures
that T24 requires.

- [x] **`scripts/acolite_env.sh`** supports `--check`, `--dry-run` and idempotent re-runs. It:
  - moves the current `~/acolite` to `~/acolite.main-d61c8de` (kept, not deleted);
  - clones tag `20260421.0` with full history of that tag;
  - asserts `HEAD == f73cbe73887c2b114d9d3c70865effee73871525`;
  - appends `version=20260421.0` to `config/config.txt` if absent (Q15);
  - runs `launch_acolite.py --retrieve_luts --sensor S2A_MSI,S2B_MSI,S2C_MSI`.
- [x] **Runtime dependency `pyogrio`** (vector reader for the GSHHG shapefile; B12), added in this phase with `uv add`.
- [x] **`scripts/fetch_gshhg.sh`**, idempotent, with the **expected archive sha256 pinned in the script** (not written by it; B12), downloads GSHHG (full
  resolution, level 1 land polygons) into OCEANOS-owned `data/external/gshhg/`. OCEANOS, not ACOLITE,
  applies the land mask (DA-1).

  `--check` verifies:
  - the commit and the version line;
  - that the LUT directories are non-empty;
  - **`git -C ~/acolite status --porcelain` lists only `config/config.txt`** (the Q15 edit), so a
    dirty tree cannot masquerade as the pin (DA #17);
  - that `~/.netrc` has machines `earthdata` and `cdse` with mode `600`;
  - **that the micromamba env satisfies the tag's `environment.yml`**: every listed package is
    importable, with version drift reported (finding 25).
  - **Pinned source (resolved 2026-09-14, Phase 1 blocker raised by the implementer).**
    - URL: `https://www.soest.hawaii.edu/pwessel/gshhg/gshhg-shp-2.3.7.zip`, the official GSHHG
      page. The NOAA NGDC mirror path returns 404.
    - Expected size: `149157845` bytes.
    - **Accepted SHA-256:** `8dbbe7e071e77e9e75f2d639239099ebca8d5c16d6a07df8169729d49f15cf41`.
    - Members used: `GSHHS_shp/f/GSHHS_f_L1.{shp,shx,dbf,prj}`, i.e. full resolution, level 1 land.
  - **Provenance of the checksum.** Upstream publishes no checksum. The value was measured by
    downloading the file independently over **HTTP** and over **FTP**
    (`ftp://ftp.soest.hawaii.edu/gshhg/gshhg-shp-2.3.7.zip`).
    - Both SHA-256 values are identical.
    - The size equals the server `Content-Length`.
    - `zipfile.testzip()` reports no CRC error.
    - The server `Last-Modified` is 2017-06-15, a stable release.

    Both copies are served by the same institution. This is an *accepted* checksum, recorded as
    such, not an upstream-published one. The script pins it; it must not compute and trust it at
    run time (B12).
  - **Extraction** uses Python's standard `zipfile`; `unzip` is not installed on the host.
- [x] **Spike, part 1: select scenes from recorded discovery.** Run the live OData query of
  `contracts.md` §1.2 for **[run date − 75 d, run date − 60 d]** and **[run date − 30 d, run date]**, windows computed relative to the execution date (B11). Save the JSON to
  `.work/oceanos-pr-mvp/spikes/discovery.json`. From it, pick:
  - **scene A**: the `19QGV` product of the first overpass dated ≥ 50 days before today
    (MERRA2 applies);
  - **scene B**: a `19QGV` product < 30 days old (V2 forced fallback, and Run C with `GMAO_IT_MET`);
  - **scene D candidates**: the three `19QGV` products with the highest `cloudCover` among overpasses
    ≥ 60 days old. After Run D, the one whose **measured** AOI valid fraction lies in (0, 0.20) is the
    `cloudy/` fixture; the next candidate is tried if none qualifies (B11).

  Their names and `Id`s are written to `.work/oceanos-pr-mvp/spikes/scenes.json`. Scene ids are
  **never hard-coded in this plan** (finding 10).

  **Tooling for parts 1–2 (clarified 2026-09-14).** The OData query is run by a **throwaway spike
  script**, `.work/oceanos-pr-mvp/spikes/discover_l1c.py`. It uses stdlib only, is uncommitted, and is
  not production code. It implements exactly the `contracts.md` §1.2 filter (`productType eq
  'S2MSI1C'`).
  - It must **not** import or reuse `oceanos.catalog` (the current provider is L2A/Earth Search).
  - It does not bring forward the Phase 2.1 migration; that migration stays in Phase 2.1.
  - Nothing under `src/` or `tests/` changes for the spikes.
- [x] **Spike, part 2: download.** `.work/oceanos-pr-mvp/spikes/fetch_safe.py` is throwaway and
  uncommitted, and uses stdlib only. It:
  - obtains a Keycloak password-grant token (`client_id=cdse-public`, `~/.netrc` machine `cdse`);
  - streams `https://download.dataspace.copernicus.eu/odata/v1/Products(<Id>)/$value` to `.part`;
  - checks `Content-Length == ContentLength` and MD5 against the catalogue;
  - renames the file into place.

  It is run for scenes A, B and D (~2.4 GB). **Scene A is downloaded twice**, and both SHA-256
  values are recorded, to test the re-acquisition determinism that D-3 depends on (DA #14).
- [x] **Spike, part 3: ACOLITE runs.** Both run under `/usr/bin/time -v` with explicit
  `runid=att-<UTCstamp>-spike0001`.
  - **Run A.** Minimal settings from `contracts.md` §4.1: single tile, no `merge_tiles`,
    `limit` = AOI bounds + 1 px.
    - `ancillary_type=GMAO_MERRA2_MET`, `netcdf_compression=True`, `delete_extracted_input=True`,
      `rgb_rhot=False`, `rgb_rhos=False`.
    - **`l2w_parameters` pinned to the full Q4 list:**
      `rhow_*,Rrs_*,rhorc_*,tur_nechad2016,spm_nechad2016,chl_re_gons740,fai,fait,ndvi`.
      `rhorc_*` there sets `output_rhorc`, and the output lands in **L2R** (`acolite_run.py:40-43`).
    - Before the run, every default this plan relies on is re-derived from the tag's
      `config/defaults.txt` and `config/defaults/S2*_MSI.txt`, and listed in the spike notes
      (DA #17: defaults drift between `main` and the tag).
  - **Run A′.** Same as A with `netcdf_compression=False`, for the V7 size comparison.
  - **Run B.** Same as A but on scene B with `GMAO_MERRA2_MET`, to force the fallback.
  - **Run C.** Scene B with `GMAO_IT_MET`. `uoz`, `uwv` and `pressure` in L2R must **differ** from the
    defaults (DA #4).
  - **Run D.** Same as A on the scene D candidates (cloudy).
  - **Run E.** Scene A with `limit` placed outside the tile footprint. This captures a **real skip
    message** and ACOLITE's exit 0 (`sentinel2/l1_convert.py:231`) for the `skipped/` fixture (B11).
- [x] **Record outcomes (D-8).** In `design/design-threads.md` §D, append to each V1–V7 row the
  exact token `**Outcome (pin 20260421.0): verified**` or
  `**Outcome (pin 20260421.0): refuted**`, followed by the evidence:
  - **V1 scope (clarified 2026-09-14):** the authorized criterion is the **single-tile** run (Run A,
    no `merge_tiles`), because T22b made single-tile the default and 19QGV covers the AOI. A merge
    run is **not** required in Phase 1; the merge path stays covered only by fixture-level tests
    (R-4) and gets its own spike if an AOI ever needs several tiles.
  - **V1:** ACOLITE writes `x`/`y` as pixel **centres**. Verified iff `(x[0] − 5) mod 10 == 0`,
    `(y[0] − 5) mod 10 == 0` and `abs(pixel size) == 10` (y spacing is negative). The centre/edge convention is written down with
    it (DA #16).
  - **V2:** L2R global attributes `uoz`/`uwv`/`pressure`/`wind` for A, B and C. Verified iff B equals
    the defaults **and** A and C differ from them.
  - **V3:** **refuted by code reading** at the tag (`land_water_mask` is never called), and resolved by
    DA-1. Recorded with its evidence; not a halt.
  - **V6:** whether the `runid` was accepted.
  - **V7:** peak RSS, wall time, SAFE size, and L2R/L2W size for A vs A′. It also sets
    `acolite.timeout = 3 × wall time of A`, rounded up to 10 min.
  - **Also recorded:**
    - the two SHA-256 values of scene A (equal or not);
    - the L2R attribute names for AOT550, aerosol model and fit diagnostics (DA-2);
    - that L2R carries per-scene `sza`, `vza`, `raa` (mean geometry) so OCEANOS can compute the glint angle. The tag computes it only when `dsf_residual_glint_correction_glint_angle=True`, which also enables correction, forbidden by Q13 (`acolite_l2r.py:1500-1512`; B3);
    - for scene A, the fraction of water pixels each `l2_flags` bit covers (DA #22);
    - that `acolite_run_<id>_l2r_settings.txt` exists and carries the `flag_exponent_*` values (DA #10).
- [x] **`scripts/make_acolite_fixtures.py`** (committed dev tool). It runs in the ACOLITE env with
  `netCDF4` only; there is no `import acolite`.
  - Crops Run A's L2R/L2W to a **256×256** window (2.56 km) containing land, the 150 m coastal buffer and **≥ 20 000 GSHHG water pixels outside that buffer**. The criterion is geometric only (clarified 2026-09-14): the shallow cut and the bathymetry dataset are Phase 3 decisions and are **not** applied here. `.work/oceanos-pr-mvp/spikes/run_a/` is kept until Phase 3 so the fixture can be re-cropped. It also writes a committed GSHHG clip `tests/fixtures/acolite/gshhg_clip.geojson` for that window (B12, B13), **rewriting `x`/`y` coordinates and the extent/limit
    attributes**, and keeping every other global and variable attribute.
  - Writes the cropped window's bounds to `tests/fixtures/acolite/window.json`, so the tests can
    build a matching test AOI and grid (finding 7).
  - Copies the log and both settings files into `tests/fixtures/acolite/success/`.
  - Derives three variants:
    - `skipped/`: Run E's real log and settings files (no NetCDFs are produced);
    - `ancillary_fallback/`: Run B's real L2R attributes;
    - `missing_variable/`: `tur_nechad2016` is dropped;
    - **`cloudy/`**: Run D, cropped at the same window (real low valid fraction; DA #13).
- [ ] **Stop conditions (user-approval gates):**
  - V1 refuted (misaligned) → halt; reopen T13 through `/planning:design`.
  - Peak RSS > 5.5 GiB → halt; the user raises the `.wslconfig` memory limit.
  - V2 refuted (fallback undetectable, **or Run C also shows the defaults**) → halt. Reopen T7/T17;
    the documented alternative is `ancillary_data=False` + `s2_auxiliary_default=True` (ECMWF data
    inside the SAFE).
  - Scene A's two downloads have different SHA-256 → halt; reopen D-3 (re-acquisition identity).
  - ~~ACTIVE HALT (2026-09-14): V8~~ **Resolved 2026-09-14 by user decision.** See the Q13/Q7
    amendment under "Resolved after lock". The V8 remedy spike below is done.
- [x] **Fixtures after V8 (binding, supersedes the fixture sources above).** Every ACOLITE-derived
  fixture comes from the **amended settings**: glint correction on, `l2w_mask_water_parameters=False`,
  `l2w_mask_threshold=0.05`, everything else as Run A. No new downloads; the SAFEs are in
  `.work/oceanos-pr-mvp/spikes/safe/`.
  - `success/` (usable): **Run F** (scene A).
  - `cloudy/`: **Run D2**, scene D1 (`S2B … 20260705 …`) re-run with the amended settings. Its valid
    fraction under the amended predicate must lie in (0, 0.20).
  - `ancillary_fallback/`: **Run B2**, scene B re-run with the amended settings and
    `GMAO_MERRA2_MET`. Its L2R attributes must still equal the defaults.
  - `skipped/`: **Run E**, unchanged (a skip does not depend on these settings).
  - `missing_variable/`: derived from Run F.
  - The usable window must satisfy the geometric criterion **and** a per-product valid fraction
    ≥ 0.20 under the amended predicate. Bathymetry is still excluded here (Phase 3 re-check).
  - Runs A/A′/D1/B keep their evidence value but are **not** fixture sources.
  - Record Runs D2/B2 (settings, exit, time, RSS) in `design-threads.md` V8 evidence.
- [x] **V8 remedy spike, authorized by the user 2026-09-14 ("opción A autorizada").** No new
  downloads for Run F. Outputs go under `.work/oceanos-pr-mvp/spikes/`. Nothing under `src/`,
  `tests/` or the committed fixtures changes until the decision below is recorded.
  - **Run F (option A).** Scene A, same settings as the valid Run A, plus:
    - `dsf_residual_glint_correction=True` (`dsf_residual_glint_correction_method=default`,
      `dsf_residual_glint_wave_range=1500,2400`, tag defaults);
    - `l2w_mask_water_parameters=False`, so ACOLITE no longer blanks water products on flagged
      pixels;
    - `l2w_mask_threshold=0.05` unchanged; bit 0 is kept only as information;
    - record the tag values of `glint_mask_rhos_wave` / `glint_mask_rhos_threshold` (1600 / 0.05),
      and the log line proving glint correction ran.
  - **Run G (cause isolation, same authorization).** One `19QGV` L1C scene from **January–February
    2026** (lowest `cloudCover`, chosen with `discover_l1c.py`), run with **Run A settings**, i.e.
    current pinned settings, no glint correction. Downloaded with `fetch_safe.py`.
  - **Measure and record as V8 evidence in `design-threads.md`:**
    1. **Candidate valid predicate for option A:** GSHHG water outside the 150 m buffer ∧ no cirrus
       (bit 1) ∧ no high-TOA (bit 2) ∧ no negative-rhos (bit 3) ∧ finite product (fill `9.969e36`
       treated as NaN). Report the fraction per product over that water, for Run F.
    2. **Glint removal:** median and p90 of `rhow_1614` and `rhow_2202` over that water, Run F
       vs Run A where both are defined. Target is a residual near 0.
    3. **Bias check:** median `TUR_Nechad2016_665` and `rhow_665` in Run F vs Run A, over the pixels
       where Run A had `flags == 0`.
    4. **Side effects:** change in bit 3 (negative rhos) coverage between Run A and Run F;
       per-bit coverage for Run F.
    5. **Run G:** bit 0 fraction, `flags == 0` fraction, `rhot_1614` p10/p50 over water, and scene
       `sza`/`vza`/`raa` with the specular angle (same method as V8).
    6. One quicklook PNG each (not committed) of `TUR_Nechad2016_665` for Runs A and F, for the
       user's visual check.
  - **Stop and return to the user with the numbers.** The planner then proposes amendments to Q13,
    to Q7's threshold role and to the DA-2 valid predicate (and, if Run G shows a seasonal cause,
    to OD5). **No fixture is regenerated and Phase 1 is not closed before that decision.**

**Sanity Check:**

- `scripts/acolite_env.sh --check` exits 0.
- `git -C ~/acolite rev-parse HEAD` prints `f73cbe73887c2b114d9d3c70865effee73871525`.
- `grep -c '^version=20260421.0' ~/acolite/config/config.txt` prints `1`.
- `grep -cE '\*\*Outcome \(pin 20260421\.0\): (verified|refuted)\*\*' docs/topics/oceanos-pr-mvp/design/design-threads.md` prints `7`.
- `grep -E '^\| \*\*V(1|2)\*\*' docs/topics/oceanos-pr-mvp/design/design-threads.md | grep -c 'Outcome (pin 20260421.0): refuted'`
  prints `0`. A refuted V1/V2 must stop the phase, not pass it.
- `scripts/fetch_gshhg.sh --check` exits 0 (it compares the archive against the sha256 pinned in the script).
- `test -f tests/fixtures/acolite/window.json && ls tests/fixtures/acolite/success/*_L2W.nc tests/fixtures/acolite/success/*_L2R.nc` exits 0.
- `ls -d tests/fixtures/acolite/{skipped,ancillary_fallback,missing_variable,cloudy}` exits 0.
- `test "$(du -sb tests/fixtures/acolite | cut -f1)" -lt 10000000` exits 0.

### Phase 2: Tracer bullet — one observation end to end [TODO]

Review: architecture

This is the integration slice (OD6): discovery → selection → acquisition → ACOLITE → verification →
archive → conformance → minimal release, for **one** observation.

It is deliberately thin:

- no quality policy (the verdict is hard-coded `usable`);
- no index, no series, no batch;
- the product set holds one continuous product plus `l2_flags`.

Estimated size: 2 300–2 800 LOC over three sub-phases, one commit each.

**Sanity Check (container):** `grep -cE "^#### Phase 2\.[123]: .*\[DONE\]" docs/topics/oceanos-pr-mvp/PLAN.md` prints `3`.

#### Phase 2.1: Domain core, delivery grid, acquisition A0–A2 [DONE]

- [ ] **Pre-flight consumer check (first item; finding 8).** Grep the consumers of every surface this
  sub-phase migrates, and record migrate/retire per consumer in the commit message:
  - `SceneSearchResult` / `schema_version`;
  - `fetch_scene`, `MVP_BANDS`, `BAND_ASSETS`, `load_materialized_bands`, `SceneManifest`;
  - `SceneSearchSettings.catalog_url` / `collection`;
  - the `scenes search|fetch` and `process normalize` CLI.

  Known consumers today:
  - `processing/normalize.py:21`, `__main__.py:15`;
  - `tests/test_fetch.py`, `tests/test_normalize.py`, `tests/test_cli.py`, `tests/test_config.py`,
    `tests/fixtures/stac_item.json`;
  - `configs/mvp.yaml`, `config/models.py:54-55`, `README.md` Fases 2–5;
  - `data/raw/sentinel2/*/manifest.json` (orphaned local data).
- [ ] **Retire the L2A band path now (D-1; finding 1).** Remove:
  - `normalize_scene` and the `process normalize` CLI;
  - `scenes fetch` band mode, `MVP_BANDS`/`BAND_ASSETS`/`load_materialized_bands`;
  - their tests.

  Kept tests are the ones asserting `GridSpec` behaviour, `assert_aligned` and `normalize_band`. The
  orphaned `data/raw/sentinel2/` is left on disk, untouched and unreferenced.
- [ ] **`oceanos.domain`.** Adds `SceneId`, `OverpassId`, `AoiId`, `GridId`, `InputSetId`,
  `ArtifactRef`, `FailureCode`/`FailureRecord`/`FailureScope` (the full code table from
  `contracts.md` §6.2), `TileCandidate`, `TileCoverage` and `InputSet`.
- [ ] **`oceanos.aoi`.** Gains `AoiId` derivation from canonical GeoJSON. **`processing/grid.py`**
  gains the AOI-anchored `DeliveryGrid` builder (EPSG:32619, 10 m, origin on multiples of 10 m),
  writes `grid.json` with `GridId`, and adds CLI `grid build` (finding 4).
- [ ] **`oceanos.storage`.**
  - Tier layout computed from ids.
  - Atomic commit/rollback extracted verbatim from the removed `normalize_scene`.
  - `WriterLock` (`fcntl.flock`) with a holder record `{pid, proc_start_time, boot_id, host, child_pid, child_pgid, child_start_time, child_cmdline,
    attempt_id, started_at}`. The `child_*` fields are filled by an **atomic rewrite right after the
    ACOLITE subprocess spawns** (B10). `boot_id` comes from `/proc/sys/kernel/random/boot_id`;
    `proc_start_time` is field 22 of `/proc/<pid>/stat`.
  - Semantics: the flock dies with its process, so "stale" means **lock free but the holder record is
    non-terminal** (DA #7).
- [ ] **`catalog/models.py`.** Optional L1C fields + `ProviderChecksums`. `SceneSearchResult` moves to
  `schema_version "1.1"`, and the reader keeps accepting `"1.0"`. A compatibility test uses
  `tests/fixtures/stac_item.json`.
- [ ] **`catalog/cdse.py` `CdseODataProvider`** per `contracts.md` §1.2. `sentinel2.py` stays in the
  tree, unwired from config and CLI.
- [ ] **`pipeline/plan.py` (D-9: the name matches `contracts.md` §1.1).** Pure minimal-cover selection
  per §1.3.
- [ ] **`ingestion/fetch.py` → whole-SAFE acquisition** per `contracts.md` §1.4:
  - token client (`ingestion/cdse_auth.py`);
  - MD5 check + SHA-256;
  - zip member check;
  - a single `product` asset, keeping the manifest/sync shape;
  - **re-acquisition by `source_id` with an expected SHA-256** (`input.refetch_mismatch`), used
    later by T7.
- [ ] **Config.** `SceneSearchSettings` becomes `provider: Literal["cdse"]` + `catalogue_url` +
  `download_url` + `identity_url`, with defaults for CDSE. The Earth Search defaults are removed.
  `configs/mvp.yaml` is migrated. New `storage` section (tier roots, retention days).
- [ ] **CLI.** `scenes search` now targets CDSE. New commands: `scenes acquire --overpass ID`,
  `scenes overpasses --start --end [--count]` (from the local catalog) and `aoi info --json`
  (DA #21).
- [ ] **Integration test.** `tests/integration/test_cdse_live.py` (opt-in `--run-integration`)
  runs discovery over the Phase 1 date window and asserts that every overpass selects exactly
  `("19QGV",)`.

**Sanity Check:**

- `uv run pytest -q tests/test_cdse.py tests/test_plan_select.py tests/test_acquire.py tests/test_grid.py` exits 0. These tests cover:
  - pagination and the cycle guard;
  - the L2A guard;
  - ties in minimal cover;
  - MD5 mismatch, missing members, two-granule zip, offline product, refetch mismatch;
  - `GridId` stability.
- `uv run pytest --run-integration -q tests/integration/test_cdse_live.py` exits 0.
- `grep -rn "MVP_BANDS\|normalize_scene\|load_materialized_bands" src tests | wc -l` prints `0`.
- Full suite + ruff (baseline).

#### Phase 2.2: ACOLITE adapter, verification, archive [TODO]

- [ ] **`configs/acolite_parameters.yaml` `AcoliteParameterSet` v1 (B4).** The pinned Q4 list
  (`rhow_*,Rrs_*,rhorc_*,tur_nechad2016,spm_nechad2016,chl_re_gons740,fai,fait,ndvi`) is owned by
  `AcoliteProfile` and is the **only** source of `l2w_parameters`. `ProductSet` may only *select* from
  it; config load rejects a `ProductSpec.acolite_parameter` outside the set. Adding a parameter is
  therefore an `AcoliteProfile` change (new `RunKey`), by design.
- [ ] **`configs/products.yaml` `ProductSet` v0 (finding 5).**
  - `tur_nechad2016` (continuous, COG) + `l2_flags` (bitfield, COG).
  - `l2w_parameters` is still rendered from the **full Q4 list**, so ACOLITE outputs match the
    Phase 1 fixtures. v0 only limits what gets *published*.
- [ ] **Config section `acolite`**: interpreter, launcher, root, pin tag + SHA, LUT dir,
  `external_dir`, and the timeout from V7 (finding 23).
- [ ] **`oceanos.acolite`**:
  - `InstallationProbe`;
  - `SettingsRenderer` (owned keys only; `merge_tiles` only when more than one tile is selected);
  - `SubprocessAcoliteRunner`: own process group, pgid written to the lock holder record, timeout,
    tee to log;
  - `RunVerifier`: expected files, the skip-message scan (research §9.4), variable presence, the
    `acolite_version` attribute, and ancillary evidence as observed in V2;
  - `FlagSpec` built from the resolved settings;
  - platform × S2 band → variable mapping (T2), tested against all three platform wavelength tables
    in research §4.
- [ ] **`tests/support/fake_acolite.py` `FakeAcoliteRunner`**, which copies the Phase 1 fixture
  variants.
- [ ] **`conftest.py` `--run-acolite` hook + `tests/acolite_golden/test_golden_run.py` (finding 15).**
  It is collected only with the flag. It re-runs scene A through `SubprocessAcoliteRunner` +
  `RunVerifier` and compares variable names, units and `FlagSpec` to the fixtures.
- [ ] **`oceanos.domain`**:
  - `AcoliteProfile`/`AcoliteProfileId` and `DownstreamProfile`/`DownstreamProfileId` (DA-4);
  - `OwnedSettings`, which includes `delete_extracted_input=True`, `rgb_rhot/rgb_rhos=False`, **`dsf_residual_glint_correction=True`** and **`l2w_mask_water_parameters=False`** (V8);
  - `ProductSpec`/`ProductSet`;
  - `RunKey`/`RunAttemptId`, `RunAttempt`, `RunState`;
  - `AncillaryEvidence`, `AerosolEvidence`.
- [ ] **`RunVerifier` details (DA #10, #18):**
  - `rhorc_*` is looked for in **L2R**;
  - `settings_resolved` = `acolite_run_<id>_l2r_settings.txt`, which is also the `FlagSpec` source
    and the Q18 asset;
  - `AerosolEvidence` is read from the L2R attribute names recorded in Phase 1.
- [ ] **`pipeline/archive.py`**:
  - the P4 commit into `data/archive/…` plus `run-manifest.json`;
  - it archives an **explicit allow-list**: `*_L2R.nc`, `*_L2W.nc`, the log,
    `l1r_settings_user.txt`, `l2r_settings.txt`. Anything else stays in the workspace (DA #9).
- [ ] **Append-only attempts ledger** `data/state/ledger/attempts.jsonl`. Every attempt state
  transition, including failures before P4, is appended with `fsync`. It is the rebuild source for
  failures (DA #8).
- [ ] **Stale-lock recovery (DA #7).** When the lock is free but the holder record is non-terminal,
  kill the recorded `child_pgid` **only if** `boot_id` matches, `child_start_time` matches and `child_cmdline`
  contains `launch_acolite.py`. Then mark the attempt `abandoned` and clean staging.

**Sanity Check:**

- `uv run pytest -q tests/test_acolite_settings.py tests/test_acolite_verify.py tests/test_acolite_mapping.py tests/test_archive.py tests/test_writer_lock.py` exits 0. These tests include:
  - the `skipped/` fixture yields `acolite.skipped` with exit code 0 recorded;
  - a second lock acquirer gets `internal.writer_locked`;
  - a stale lock whose recorded pgid has a live dummy process with a matching start time and a
    `launch_acolite.py` cmdline leads to that process being killed;
  - a **boot_id mismatch** or a start-time mismatch kills nothing;
  - the archive contains exactly the allow-listed files;
  - `rhorc_*` is detected in L2R.
- `uv run pytest --run-acolite -q tests/acolite_golden` exits 0.
- `uv run pytest -q tests/test_architecture.py` exits 0, now covering `acolite`.
- Full suite + ruff (baseline).

#### Phase 2.3: Conformance, minimal release, runtime probe [TODO]

- [ ] **Pre-flight consumer check (first item).** Consumers of `normalize_band` (only
  `tests/test_normalize.py` after 2.1) and of `build_grid` (tests; `normalize_scene` is gone).
  Record the result.
- [ ] **`processing/normalize.py` conform:**
  - `normalize_band` accepts a `NETCDF:"…":var` source and `int32` categorical input;
  - window copy when the output is phase-aligned, `grid.misaligned` otherwise;
  - partial extent handled per `contracts.md` P5 (NaN / the out-of-scene flag value taken from
    `FlagSpec`, `grid_coverage_fraction`);
  - **`LandMask` (DA-1)**: `processing/masks.py` rasterizes `data/external/gshhg` once per grid into
    `data/products/<aoi>/grid/land_mask.tif`. Conform sets water products to NaN on land, and
    provenance records `land_mask` version + sha256 per product;
  - `assert_aligned` on every layer;
  - the `catalog`/`ingestion` imports are removed.
- [ ] **`oceanos.publishing`:**
  - continuous COG profile (`DEFLATE`, `PREDICTOR=3`);
  - bitfield profile (`DEFLATE`, `PREDICTOR=2`, `OVERVIEW_RESAMPLING=MODE` explicit);
  - `PublicationProfile` v0, `PublicationProfileId`, `ReleaseId` (finding 5);
  - release dir, `release.json`, minimal `provenance.json`;
  - derived STAC Item per `contracts.md` §4.4;
  - STAC validation uses **schemas vendored under `tests/fixtures/stac-schemas/`** (finding 27).
- [ ] **Release commit (DA-5, DA #8, B1).** The sequence is:
  1. rename the new release dir into `data/products/`;
  2. atomically replace the STAC Item;
  3. commit the index transaction (from Phase 4; a no-op before that);
  4. **only then** move the previous release to `data/superseded/`, and append a `release_superseded`
     event to `data/state/ledger/releases.jsonl`.

  Until step 4, the previous release stays served, so I3 and the Brief criterion "previous version
  available while reprocessing" hold. An orphan left by a crash is harmless.

  A reconciliation step runs at the start of every mutating command **and at API start-up
  (read-only report + refusal to start on a broken state)**. `tests/test_publish_rollback.py`
  injects a crash after each of steps 1–3.
- [ ] **`pipeline/run_one.py` + CLI `pipeline run-one --overpass ID [--force-reprocess]`.** The AOI comes from config.
  It chains A1 selection → A2 → P1–P8 under `WriterLock`. It requires a prior `grid build` and
  `scenes search` covering the overpass, and errors otherwise (house pattern §3.3).
- [ ] **`scripts/verify_release.py RELEASE_DIR`.** It checks:
  - every `.tif` is tiled and has ≥ 1 overview;
  - `l2_flags` overview values are a subset of the full-resolution value set;
  - every asset's sha256 matches `release.json`;
  - the STAC Item validates against the vendored schemas.
- [ ] **CLI `pipeline latest-release --overpass ID`** prints the current release dir, read from the
  derived STAC Item. It is needed for non-ambiguous probes (finding 11).

**Sanity Check:**

- `uv run pytest -q tests/test_conform.py tests/test_land_mask.py tests/test_publish.py tests/test_publish_rollback.py tests/test_pipeline_run_one.py` exits 0. They also assert:
  - water products are NaN on every land-mask pixel of the fixture window, and `l2_flags`/`true_colour`
    are not masked;
  - after a second `run-one --force-reprocess`, `data/products/` holds exactly one release for the
    overpass and `data/superseded/` holds the previous one.
  - The `run_one` grid is built from `tests/fixtures/acolite/window.json`, as before. The `run_one` test builds its grid from `tests/fixtures/acolite/window.json`.
- **Runtime probe (real)**, a script listing every prerequisite (finding 10):
  - `scripts/probe_run_one.sh` runs `uv run oceanospr grid build`;
  - then `uv run oceanospr scenes search --start <A date> --end <A date+1>`, with the date read
    from `.work/oceanos-pr-mvp/spikes/scenes.json`;
  - then `uv run oceanospr pipeline run-one --overpass <A overpass id>`;
  - then `uv run python scripts/verify_release.py "$(uv run oceanospr pipeline latest-release --overpass <id>)"`;
  - the script exits 0.
- Full suite + ruff (baseline).

### Phase 3: Quality, masks, full product set, provenance [TODO]

Review: code-design

Estimated size: 1 200–1 500 LOC.

- [ ] **Config sections `quality` (file `configs/quality.yaml`) and `publication`** (finding 23).
- [ ] **Bathymetry research item (DA-3).** Run `/discovery:research`: public bathymetry for La
  Parguera/SW Puerto Rico (NOAA NCEI CUDEM / Coastal Relief Model candidates) — resolution, vertical
  datum, licence, coverage of the AOI. Record the chosen dataset and the reason in
  `design/design-threads.md` §I. **User gate** if none is suitable (fallback: per-product caveat).
- [ ] **`scripts/fetch_bathymetry.sh`** (idempotent, sha256 recorded) into `data/external/bathymetry/`.
- [ ] **`processing/masks.py` `AnalysisMask`**, built once per grid:
  - GSHHG coastal buffer `150 m` (D-2: the midpoint of the Brief's 100–200 m);
  - a **depth raster** from the bathymetry dataset. The shallow exclusion is **per product** (B7):
    `ProductSpec.shallow_exclusion_m` (e.g. set for `tur_nechad2016`, `spm_nechad2016`,
    `chl_re_gons740`; `null` for `fai`, `fait`, `ndvi`, where the NIR/SWIR bottom signal is small and
    sargassum over the shelf is the target). Initial values come from the research item, with their
    basis;
  - `water_pixels` per product is the `valid_fraction` denominator;
  - **Fixture re-check (deferred from Phase 1, clarified 2026-09-14).** Once the dataset and the
    per-product shallow cuts are chosen, verify that the Phase 1 fixture window still has ≥ 20 000
    analysis pixels for every product with `shallow_exclusion_m` set. If it does not, re-crop from
    `.work/oceanos-pr-mvp/spikes/run_a/` with `scripts/make_acolite_fixtures.py` before the quality
    tests are written.
  - **guard:** if any product's analysis pixels < 10 000 for the AOI, stop with a user gate
    (the shelf may be too shallow for that product) rather than dividing by ~0.
- [ ] **`processing/quality.py`, a pure core (DA-2):**
  - the valid-pixel predicate **as amended by V8**: cirrus, high-TOA and negative-rhos flags == 0, with the cloud flags (cirrus, high-TOA) dilated by `cloud_dilation_px`; **bit 0 (SWIR threshold) is recorded but never excludes**; product finite with `_FillValue` → NaN;
  - `FlagStatistics`, `RangeViolation`, `QualityReport`;
  - gates, applied in order:
    1. ancillary fallback;
    2. `grid_coverage_fraction < min_grid_coverage` → `incomplete_coverage`;
    3. AOT550 / aerosol model outside bounds;
    4. **residual-glint gates (V8):** the negative-rhos (bit 3) fraction above `max_negative_rhos_fraction`, and the water `rhow_1614` p90 above `max_residual_swir_rhow`, both reported in `quality.json`. The glint angle is **recorded only** (not a rejection gate) because glint is now corrected. **OCEANOS computes it** from the L2R scene-mean `sza`/`vza`/`raa` with the standard specular geometry, recorded in provenance as an OCEANOS derivation (geometry, not an ACOLITE algorithm; B3);
    5. range rules;
    6. `valid_fraction` < 0.20, computed **per product** over that product's analysis pixels (B7).
  - Initial numeric values are set from Phase 1 spike data (scenes A and D), each with its basis
    written into `configs/quality.yaml`, which is the file behind config section `quality` (B14). Numbers are fixed **after** the bathymetry item above (B7).
- [ ] **`configs/products.yaml` `ProductSet` v1:**
  - all Q4 parameters;
  - publish flags per T3;
  - units, accepted and display ranges, and caveats taken from research §6.
- [ ] **`publishing`:**
  - `true_colour` COG from L2R `rhos` B04/B03/B02, with one fixed stretch;
  - the restricted release (T6);
  - full `ProvenanceRecord`;
  - `PublicationProfile` v1.
- [ ] **Failure codes for stages P3–P8** are wired with their evidence. Ancillary fallback fails the
  attempt.
- [ ] **`series.json` in every release (DA #8)**. For now it holds the whole-AOI zone rows, so the
  index can be rebuilt from releases.
- [ ] **Downstream re-entry (DA-4).** CLI `pipeline republish --observation|--range` re-enters at P5
  from the archive when only the `DownstreamProfile` changed.
- [ ] **User-approval gate (DA-6; PRD rollout step 2).** After the runtime probe, present scene A's
  COGs, `l2_flags`, `quality.json` verdict and provenance, plus scene D's verdict. Phase 4 starts
  only on explicit approval.

**Sanity Check:**

- `uv run pytest -q tests/test_quality.py tests/test_masks.py tests/test_release_visibility.py tests/test_provenance.py tests/test_republish.py` exits 0. They assert that:
  - the **`cloudy/`** variant yields an unusable verdict, and its release has exactly the data
    assets `{true_colour, l2_flags}`;
  - `pipeline republish` after a quality-policy version bump creates a new `ReleaseId` while
    `FakeAcoliteRunner` records **zero** invocations and no acquisition occurs;
  - each DA-2 gate has a failing case, including the OCEANOS glint-angle computation against a known geometry;
  - the analysis-pixel guard trips when a synthetic mask leaves < 10 000 pixels;
  - `fai` statistics include shallow pixels, `tur_nechad2016` statistics exclude them;
  - the usable variant's release has all 8 COG products;
  - `provenance.json` contains the keys `scenes`, `acolite`, `oceanos`, `ancillary`, `products` and
    `scientific_label`.
- **Runtime probe:** `scripts/probe_run_one.sh --force-reprocess` exits 0. Then
  `uv run python -c "import json,sys; p=json.load(open(sys.argv[1]+'/provenance.json')); assert {'scenes','acolite','oceanos','ancillary','products','scientific_label'} <= p.keys()" "$(uv run oceanospr pipeline latest-release --overpass <A id>)"`
  exits 0.
- Full suite + ruff (baseline).

### Phase 4: Index, orchestration, retention, bounded backfill [TODO]

Review: concurrency

Estimated size: 1 600–1 900 LOC, plus an operational run.

- [ ] **`oceanos.index`:**
  - the SQLite schema (`contracts.md` §4.5), in WAL mode;
  - `IndexWriter`, `IndexReader`;
  - `oceanospr index rebuild`;
  - `scripts/check_index_rebuild.sh`: dump **full sorted row content** of every table, move
    `index.sqlite` aside, rebuild from `release.json` + `series.json` + `ledger/attempts.jsonl` + `ledger/releases.jsonl` (supersession survives GC; B8),
    dump again, `diff` (finding 12, DA #8). The fixture state for the check includes **one reprocessed observation** with a superseded release, so the diff is not vacuous.
- [ ] **`oceanos.pipeline`:**
  - P0 planner over a date range;
  - batch vs observation scope;
  - "yes (once)" retries and deferred retries;
  - verbs `pipeline backfill --start --end`, `pipeline update`, `pipeline reprocess`, `pipeline republish`, `pipeline purge`,
    `pipeline status --start --end [--json] [--failure-histogram]`, where `--failure-histogram` adds `failure_histogram: {code: {count, scope}}` to the `contracts.md` §7.1 shape (B5);
  - supersession: the previous release moves to `data/superseded/` (keep 1), per DA-5.
- [ ] **T7 tier upgrade via re-acquisition (D-3; finding 2).** `update` selects provisional
  observations older than 57 d, re-acquires them by `source_id` with the expected SHA-256
  (`input.refetch_mismatch` otherwise), and reprocesses them with `GMAO_MERRA2_MET`.
- [ ] **P9 retention.**
  - Follows the `contracts.md` §6.3 conditions.
  - Failed workspaces are kept 14 d.
  - `data/superseded/` keeps 1 release per observation.
- [ ] **Before the backfill, wipe the tracer-bullet and probe releases (DA-5, B2).** Run
  `pipeline purge --created-before <ISO-8601 wall-clock timestamp>`. It removes releases, STAC Items and
  index rows, keeps the archive, and appends a **`purged` event per attempt** to
  `ledger/attempts.jsonl`. Rule I4 and `index rebuild` treat a purged attempt as *not published*,
  so the backfill re-publishes those overpasses **from the archive (P5)** rather than skipping them.
- [ ] **`oceanos.timeseries`:**
  - zone pixel indices and pure aggregation;
  - rows written at P8.
  - Until R2 is answered, `zones.geojson` holds **one zone: the AOI water area**
    (`[FALLBACK — confirm or override]`, D-4).
- [ ] **JSON-lines per-attempt event log** (T26).
- [ ] **`docs/topics/oceanos-pr-mvp/RUNBOOK.md`** (finding 22):
  - run the backfill under `tmux`/`nohup` from inside WSL;
  - keep WSL alive (`wsl --shutdown` kills it);
  - resume with `pipeline backfill`, which is idempotent through the ledger.
- [ ] **Operational run (OD5).**
  - Record discovery for 2026-06-01 → 2026-08-31 with `scenes search`, then
    `pipeline backfill --start 2026-06-01 --end 2026-08-31`.
  - Write `docs/topics/oceanos-pr-mvp/BACKFILL_REPORT.md`:
    - observations by status;
    - valid-fraction distribution;
    - M2 coverage;
    - wall time per observation;
    - operator interventions (a proxy for M7);
    - storage per overpass (V7);
    - provisional vs final counts;
    - the discovered overpass count (`N_DISCOVERED`).
- [ ] **RUNBOOK/BACKFILL_REPORT note (B15):** MERRA-2 availability is month-batched (measured: fails at 39 d, works at 64 d). Scenes aged 50–60 d may hit `acolite.ancillary_fallback` and be retried later; the report counts them separately from real failures.
- [ ] **User-approval gate (PRD §11).** Present the report. Proceed to Phase 5 only on explicit
  approval.

**Sanity Check:**

- `uv run pytest -q tests/test_index.py tests/test_reconcile.py tests/test_pipeline_batch.py tests/test_timeseries.py tests/test_retention.py tests/test_tier_upgrade.py` exits 0.
- `scripts/check_index_rebuild.sh` exits 0.
- The status count matches discovery rather than a literal (finding 19):
  `N=$(uv run oceanospr scenes overpasses --start 2026-06-01 --end 2026-08-31 --count)` followed by
  `uv run oceanospr pipeline status --start 2026-06-01 --end 2026-08-31 --json | python -c "import json,sys; o=json.load(sys.stdin)['observations']; assert len(o)==int(sys.argv[1]) and all(x['status'] in {'usable','no_usable_observation','processing_failed','excluded_scene_cloud','incomplete_coverage'} for x in o) and any(x['status']=='usable' for x in o)" "$N"`
  exits 0 (at least one usable observation; DA #13).
- The scene A overpass from the Phase 2/3 probes is present with a terminal status after purge + backfill: `uv run oceanospr pipeline status --start <scene A date> --end <scene A date> --json | python -c "import json,sys; o=json.load(sys.stdin)['observations']; assert len(o)==1 and o[0]['current_release_id']"` exits 0 (B2).
- `uv run oceanospr pipeline status --start 2026-06-01 --end 2026-08-31 --json --failure-histogram | python -c "import json,sys; h=json.load(sys.stdin)['failure_histogram']; assert not [c for c,v in h.items() if v['scope']=='batch']"`
  exits 0 (no batch-scope failure left unresolved).
- `test -f docs/topics/oceanos-pr-mvp/BACKFILL_REPORT.md && test -f docs/topics/oceanos-pr-mvp/RUNBOOK.md` exits 0.
- Full suite + ruff (baseline).

### Phase 5: Read API [TODO]

Review: security

Estimated size: 900–1 100 LOC.

- [ ] **Runtime dependencies `fastapi` + `uvicorn`** (T10). **Config section `api`**: the Unix socket
  path and header names (finding 23).
- [ ] **`oceanos.api`**, with endpoints exactly as in `contracts.md` §7:
  - series by zone uses the pre-extracted table;
  - series by geometry **or point** uses full-resolution windowed reads (finding 26);
  - `/value` reads full resolution.
- [ ] **Role enforcement (DA #12).**
  - uvicorn listens **only on a Unix domain socket** at `data/state/run/api.sock`. uvicorn forces socket mode 0666, so access is controlled by the **directory** `data/state/run/` (mode 0750; B6), with
    `proxy_headers=False`. No TCP port means WSL localhost forwarding or
    `portproxy` cannot reach it.
  - Identity comes from `X-Oceanos-User`/`X-Oceanos-Role`, set by Caddy.
  - Operator endpoints return `403` to researchers; a missing identity returns `401`.
- [ ] **`/data` static serving of `data/products/` only**, with HTTP Range `206` and same-origin
  hosting (no CORS needed, D-6). **First check that Starlette's static file serving honours Range at
  the resolved version.** If it does not, Caddy serves `/data` directly; that is safe because
  `data/products/` is researcher-visible by construction (`contracts.md` §7, finding 17).
- [ ] **Install Caddy** (not present on the host, verified 2026-09-14): pinned release binary via `scripts/install_caddy.sh` with a checksum, no system package changes without user confirmation.
- [ ] **`docs/deploy/Caddyfile.example`:**
  - `tls internal` (no cleartext basic auth); distributing its root CA to researcher browsers is part of the hosting decision R3 (B6);
  - `reverse_proxy unix//…/api.sock { header_up -X-Oceanos-* ; header_up X-Oceanos-User {http.auth.user.id} ; header_up X-Oceanos-Role {mapped role} }`, so client-supplied identity headers never reach the API, whatever the directive order (B6);
  - basic auth, then a user → role `map` that sets the two headers;
  - `/api/*` → uvicorn;
  - `/data/*` → uvicorn or `file_server`;
  - `/` → `web/`;
  - all on one origin.

**Sanity Check:**

- `uv run pytest -q tests/api/` exits 0. It runs `TestClient` over a fixture tree plus SQLite and
  asserts:
  - researcher → operator endpoint gives `403`;
  - a request without identity headers gives `401`;
  - a point series returns gap rows.
- `uv run pytest -q tests/test_architecture.py` exits 0, now including A2.
- **Runtime probe:** `scripts/probe_api.sh` exits 0. It:
  - starts uvicorn on the Unix socket and Caddy with the example config on `https://localhost:8443`;
  - asserts `curl -sk -o /dev/null -w '%{http_code}' -H 'X-Oceanos-Role: operator' https://localhost:8443/api/v1/operator/status` without credentials prints `401` (spoofed header stripped);
  - asserts the same request with **researcher** credentials plus a spoofed `X-Oceanos-Role: operator` prints `403`;
  - reads `AOI` from `uv run oceanospr aoi info --json`;
  - asserts the observation count equals `N` from the Phase 4 check;
  - asserts `curl -sk -u researcher:<probe password> -o /dev/null -w '%{http_code}' -H 'Range: bytes=0-99' "https://localhost:8443/data/<relative path of a real l2_flags.tif>"` prints `206`;
  - stops Caddy and uvicorn.
- Full suite + ruff (baseline).

### Phase 6: Viewer [TODO]

Review: code-design

Estimated size: 1 300–1 700 LOC of JS/HTML/CSS.

- [ ] **`web/vendor/`** holds **browser/UMD builds** (no bare ESM specifiers; finding 18), pinned,
  with SHA-256 recorded in `web/vendor/VERSIONS.md`:
  - `leaflet`;
  - `georaster` (`georaster.browser.bundle.min.js`);
  - `georaster-layer-for-leaflet@4.1.2`;
  - `geotiff@3.0.5` browser bundle.

  Files are fetched once by `scripts/vendor_web.sh` with checksum verification. The exact dist file
  names are confirmed at vendoring time.
- [ ] **No external basemap (D-5).** PRD §12 lists no external integrations beyond the data provider
  and ACOLITE. Map context is a simplified GSHHG coastline GeoJSON generated per AOI into
  `data/products/<aoi>/grid/coastline.geojson` and served under `/data`. The no-URL grep therefore
  holds.
- [ ] **Pure logic modules:**
  - `colour.js`: the NaN branch before the ramp;
  - `flags.js`: legend and toggles generated from `classification:bitfields`;
  - `states.js`: the four visual states;
  - `dates.js`: gaps listed with their status.
- [ ] **Views:**
  - map + date navigator;
  - side-by-side comparison with synchronized pan/zoom;
  - series chart (gaps as gaps) for a zone, a drawn polygon or a clicked **point**;
  - value inspection via `/value`;
  - provenance panel;
  - persistent scientific label;
  - operator status view.
- [ ] **`docs/topics/oceanos-pr-mvp/VIEWER_ACCEPTANCE.md`**, a manual checklist with **12 items**:
  - the 4 visual states, each on a named real backfill date;
  - date navigation with a gap;
  - point selection; polygon selection;
  - side-by-side on the same pixel;
  - value inspection with unit;
  - provenance from a value;
  - operator view hidden for the researcher role;
  - the **M1 proxy**: a timed turbidity series over the 3-month backfill.

  The checklist states that the PRD's M1 uses 12 months, so this is a proxy (finding 26).
- [ ] **User-approval gate.** The user runs the checklist.

**Sanity Check:**

- `grep -rnE "https?://" web --include=*.js --include=*.html | grep -v "^web/vendor/" | wc -l` prints `0`.
- `grep -nE "(0x[0-9a-fA-F]+|<< ?[0-9]+|\*\* ?[0-9]+|Math\.pow|[&|^] ?[0-9]+)" web/js/flags.js web/js/states.js | wc -l`
  prints `0`. No numeric literal may take part in a bitwise or power expression. Masks are computed
  from `classification:bitfields` offsets held in variables (DA #13).
- `grep -c "classification:bitfields" web/js/flags.js` ≥ 1.
- `test "$(grep -c '^- \[x\]' docs/topics/oceanos-pr-mvp/VIEWER_ACCEPTANCE.md)" -eq 12` exits 0.
- Full suite + ruff (baseline).

### Phase 7: Periodic update, retirement, documentation, merge [TODO]

Estimated size: ~300 LOC net, mostly deletions.

- [ ] **Pre-flight consumer check (first item).** Grep every remaining reference to `sentinel2.py`,
  `Sentinel2Provider`, `build_grid`, `composites`, `earth-search` and `sentinel-2-l2a`. Classify
  each as retire or keep, with the keep list below.
- [ ] **Update scheduling.**
  - `scripts/oceanos-update.sh` (lock-aware, logs to `data/state/`);
  - `docs/deploy/oceanos-update.{service,timer}`, and a cron alternative;
  - **a Windows Task Scheduler entry** (`wsl -d <distro> -e /path/scripts/oceanos-update.sh`,
    daily, "run whether user is logged on"), because WSL timers only fire while WSL runs (DA #19);
  - `pipeline status` reports `last_successful_update_age_hours`.
- [ ] **Retire:**
  - `catalog/sentinel2.py`, `tests/test_scenes.py`, `tests/integration/test_sentinel2_live.py`;
  - `build_grid(reference_path)` + its tests;
  - `src/oceanos/composites/`.
- [ ] **Keep (allow-listed):**
  - the committed `catalog/` L2A collection (`CURRENT_STATE.md` §4);
  - `LocalSceneCatalog`'s collection-id handling;
  - `tests/fixtures/stac_item.json`, the 1.0 compatibility fixture.
- [ ] **Docs.** Update `docs/architecture.md` and `SUMMARY.md`. List the ADR candidates from the
  handoff in `SUMMARY.md` §10.
- [ ] **User-approval gate (OD2).** Merge `feat/oceanos-pr-mvp` into `master` (local, `--no-ff`).

**Sanity Check:**

- `grep -rnE "earth-search|Sentinel2Provider|build_grid\(|oceanos\.composites" src tests configs | wc -l` prints `0`.
- `grep -rn "sentinel-2-l2a" src tests configs | grep -v -e "tests/fixtures/stac_item.json" -e "test_local_catalog.py" | wc -l` prints `0`.
- `test ! -d src/oceanos/composites` exits 0.
- `bash -n scripts/oceanos-update.sh` exits 0.
- `git branch --merged master | grep -c "feat/oceanos-pr-mvp"` prints `1`, after the gate.
- Full suite + ruff (baseline).

---

### Test strategy

**Red-Green-Refactor per work item.** The failing test is written against the named boundary first.

The default run stays offline and free of ACOLITE, as it is today. Two suites are opt-in:

- `--run-integration`: live CDSE;
- `--run-acolite`: the golden run on the Phase 1 scene A (Phase 2.2).

**Test boundaries** (approving this plan settles them):

| Boundary | Status | Test type | Phases |
|---|---|---|---|
| `SceneProvider.search` | existing | unit, `httpx.MockTransport` | 2.1 |
| `pipeline.plan` selection core | new, pure | unit, table-driven | 2.1 |
| SAFE acquisition + re-acquisition entry points | reshaped from `fetch_scene` | unit, streamed fakes + tmp fs | 2.1, 4 |
| `DeliveryGrid` builder | new (replaces `build_grid` role) | unit | 2.1 |
| **`AcoliteRunner` port** + `FakeAcoliteRunner` | new, **primary seam** (T24) | unit/integration | 2.2–4 |
| `RunVerifier.verify` | new | unit over real-derived fixtures | 2.2 |
| `WriterLock` | new | unit, multiprocess | 2.2 |
| Conform function | reshaped from `normalize_band` | unit, synthetic NetCDF + fixture | 2.3 |
| Publisher / release commit | new | unit + crash-injection rollback | 2.3, 3 |
| Quality core | new, pure | unit, arrays | 3 |
| `IndexWriter` / `IndexReader` / rebuild | new | unit | 4 |
| CLI verbs (`grid build`, `scenes acquire`, `pipeline run-one/backfill/update/reprocess/status/latest-release`, `index rebuild`, `scenes overpasses`) | new public boundary | integration via `main(argv)` (existing pattern) | 2.1–4 |
| HTTP API | new | integration, `TestClient` | 5 |
| Import + literal rules A1–A4 | new | architecture | 0 onward |
| Viewer | new | manual checklist + static greps (OD4) | 6 |

**Edge cases that must have tests:**

- exit 0 with a skip message;
- ancillary fallback;
- a dropped variable;
- a misaligned grid;
- partial grid coverage;
- MD5 mismatch, offline product, two-granule zip, refetch mismatch;
- a stale lock with a live orphaned process group;
- a crash between the release rename and the STAC replace;
- S2A/S2B/S2C suffix mapping;
- an all-NaN observation;
- a series with gaps;
- `SceneSearchResult` 1.0 read compatibility.

**Existing tests to update or retire:**

- `test_fetch.py`: rewritten for whole SAFE (2.1).
- `test_normalize.py`: band-scene tests retired (2.1), conform tests added (2.3); grid/alignment
  assertions kept.
- `test_config.py` and `test_cli.py`: updated per phase.
- `test_scenes.py`: retired in Phase 7.

### Alternatives considered

| Alternative | Why rejected | Switch condition |
|---|---|---|
| Horizontal build (all domain → all adapters → all stages) | ACOLITE/CDSE integration risk surfaces last; PRD rollout step 2 requires a single-scene path first | Spikes show ACOLITE output shape varies per scene, so fixtures cannot stand in |
| Run the V-spikes before writing this plan | Only V1 changes plan shape, and it has a halt gate | V1 refuted → reopen T13, re-plan 2.3+ |
| Keep the L2A band path alive until Phase 7 | Nothing consumes it after 2.1, and keeping it means maintaining two `fetch` models (finding 1) | A researcher needs the old L2A outputs during the transition |
| Keep the SAFE until tier = final instead of re-acquiring | Contradicts Q10 (discard after processing); re-fetchability is already a Brief acceptance criterion | CDSE re-fetch proves unreliable (`input.refetch_mismatch` or offline) in the backfill |
| All intersecting tiles + `merge_tiles` (original Q11) | ~4× download, no coverage gain (T22b) | Reviewed AOI no longer fits one footprint |
| TiTiler tile server | Q17; geotiff.js reads COGs directly | Server-side reprojection needed, or >50 concurrent users |
| External basemap tiles (OSM etc.) | PRD §12 allows no extra external integrations | The user approves a basemap provider |
| Playwright browser tests | Node absent (OD4) | Viewer regressions recur, or Node is added |
| Parallel Phases 5 ∥ 6 | Phase 6 acceptance needs a live API over real data; UI work is judgment-heavy | API tests green and a second implementer available |
| Importing ACOLITE as a library | Q1 / GPLv3 coupling | never within this Brief |

### Risks and mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | 7 GiB WSL RAM is insufficient for ACOLITE | Med | High | Phase 1 measures peak RSS; halt gate at 5.5 GiB |
| R-2 | V2 fallback detection differs at the tag (code was read on `main`) | Med | High | Phase 1 run B at the tag; halt if undetectable |
| R-3 | ~~GSHHG land mask unreachable from ACOLITE~~ **Confirmed at the tag; resolved by DA-1** (OCEANOS `LandMask` at conform) | — | — | GSHHG resolution near mangroves/reef flats may misclassify a few pixels; the coastal analysis buffer (150 m) keeps them out of statistics |
| R-4 | Merge path unexercised on real data | Low | Med | Fixture-level tests only; a multi-tile AOI triggers its own spike |
| R-5 | CDSE quota, rate limits or token expiry during 790 MB transfers | Med | Med | Sequential downloads, per-product token, bounded retry, `input.auth_failed` is batch-scoped |
| R-6 | Starlette static serving lacks Range | Low–Med | Low | Checked first in Phase 5; Caddy fallback is safe by construction |
| R-7 | Cloud sparsity makes the backfill series useless | Med | High | Phase 4 report + user gate |
| R-8 | georaster-layer UTM→WebMercator sampling misplaces pixels at high zoom | Med | Med | `/value` reads full resolution server-side; checklist item "same pixel" |
| R-9 | Fixtures from one S2 platform miss other-platform suffixes | Med | Low | Mapping tests use all three wavelength tables; `--run-acolite` golden run |
| R-10 | Scope (~9 000 LOC) exceeds what one plan document carries well | High | Med | Sub-phase commits; per-phase sub-topic promotion not used by default (Q-A default recorded under Open questions) |
| R-11 | CDSE re-acquisition for tier upgrade fails (product changed or evicted) | Low | Med | `input.refetch_mismatch` / `input.product_offline` keep the provisional release current; the operator decides |
| R-12 | The backfill is interrupted by WSL shutdown | Med | Low | RUNBOOK; ledger-based resume; boot_id-guarded stale-lock recovery |
| R-13 | No suitable public bathymetry for DA-3 | Low–Med | Med (shallow bias in statistics) | Phase 3 research item + user gate; fallback: per-product caveat |
| R-14 | CDSE re-download is not byte-identical | Low | High for D-3 | Phase 1 double-download halt gate |
| R-15 | DA-2 thresholds tuned on 2 scenes over-reject or under-reject | Med | Med (M2 vs M5) | DA-6 review gate; downstream re-entry (DA-4) makes retuning cheap after the backfill |

## Blast radius

**HIGH.**

- Around 80 files across new packages, a new runtime dependency (FastAPI) and dev tooling.
- An external integration with credentials (CDSE, EarthData).
- An authentication boundary (proxy headers).
- Deletion of the L2A path (`sentinel2.py`, `normalize_scene`, band fetch).
- A CLI contract change and a wire-format bump (`SceneSearchResult` 1.1).
- A long operational run.

Triggers matched: external dependency changes · security-sensitive (auth, tokens) · breaking CLI/API
changes · multi-step implementation over poorly understood behaviour (ACOLITE silent failures) · new
enforcement mechanism (architecture test).

## Stress-test summary

1. **Step 3, fresh-context plan reviewer (2026-09-14).** 0 CRITICAL, 18 IMPORTANT, 10 SUGGESTION.
   All 28 were verified against the files (e.g. `processing/normalize.py:21` imports `MVP_BANDS`;
   `config/models.py:54-55` defaults to Earth Search; `.gitignore:7` already ignores `*.egg-info`;
   `.agents/` is untracked). All were incorporated in rev 2. Design artifacts were updated too:
   `contracts.md` gains `internal.writer_locked`, `input.refetch_mismatch`, partial-extent conform,
   the T7 re-acquisition path, the `/data` visibility rule and the §7.1 status JSON shape; T1 is
   annotated as amended.
2. **Step 4, `/planning:devils-advocate`** (fresh context, iteration 1, 2026-09-14).
   **1 CRITICAL, 6 HIGH, 9 MEDIUM, 7 LOW.** Verdict: *does not survive as written*.

   The key claims were re-verified by the planner against a tarball of tag `20260421.0`, which was
   **not** checked against commit `f73cbe7`:
   - `land_water_mask` is defined in `acolite/masking/land_water_mask.py`, but its only reference is
     the re-export in `masking/__init__.py:3`. **No processing path calls it.**
   - The sensor-merged settings file is `acolite_run_<id>_l2r_settings.txt` (`acolite_l2r.py:530`).
   - `delete_extracted_input=False` (`defaults.txt:591`).
   - `rgb_rhot`/`rgb_rhos` are `True` (`:480-481`).
   - `netcdf_compression=False` at the tag (`:61`).
   - `flag_exponent_outofscene=4` (`:265`).
   - `l2w_parameters` entries starting with `rhorc` set `output_rhorc` (`acolite_run.py:40-43`).

   **Disposition.**

   | Findings | Disposition |
   |---|---|
   | #1 (Q7 land mask not reachable in ACOLITE), #2 (quality-gate hardening), #3 (optically shallow water), #5 (split processing vs downstream profile), #6 (superseded releases stay downloadable), #15 (single-scene review gate) | **Need user decisions** (Brief- or design-level). Asked as round DA-1…DA-6 before rev 3 |
   | #4, #7–#14, #16–#23 | Accepted as plan corrections, applied in rev 3 |

   Specifically, rev 3 adds:
   - Run C (`GMAO_IT_MET` at the tag) and a double download for SHA-256 determinism;
   - boot_id + start-time guarded lock recovery;
   - `series.json` + append-only attempts ledger + full-content rebuild diff + reconciliation;
   - `delete_extracted_input=True` and an explicit P4 allow-list;
   - `l2r_settings.txt` as the resolved settings;
   - `min_grid_coverage` and the `valid_fraction` denominator;
   - non-vacuous sanity checks and a real cloudy fixture;
   - V1 defined on pixel centres ≡ 5 mod 10;
   - a `git status` clean check;
   - `rhorc_*` in `l2w_parameters`, verified in L2R;
   - a Windows Task Scheduler trigger;
   - flag bits taken from `FlagSpec`;
   - missing CLI items;
   - per-bit flag coverage recorded in the spike;
   - A4 scan narrowed to `key=` / wavelength patterns.
3. **Step 4, `/planning:devils-advocate` iteration 2** (fresh context, on rev 3, 2026-09-14).
   - **Status of iteration 1's 23 findings:** 14 FIXED, 9 PARTIAL, 0 NOT FIXED.
   - **New findings:** 5 HIGH (B1–B4, B7), 8 MEDIUM, 3 LOW. Verdict: *survives in structure; not
     ready until B1–B5 and B7 are fixed*.
   - **Planner re-verification.** B3 was confirmed at the tag: the glint angle is computed only
     inside `if setu['dsf_residual_glint_correction_glint_angle']`, which also switches glint
     correction on (`acolite_l2r.py:1500-1512`).
   - **All 16 findings are incorporated in rev 4:**
     - publish order with superseded move last + `releases.jsonl`;
     - `purge` writing ledger events respected by I4 and rebuild;
     - OCEANOS glint angle from L2R geometry;
     - `AcoliteParameterSet` separated from `ProductSet`;
     - `--failure-histogram` defined;
     - socket directory mode + Caddy `header_up`;
     - per-product shallow exclusion + analysis-pixel guard;
     - rebuild from both ledgers with a non-vacuous diff;
     - `ProductSpec.land_masked` and land-mask lineage;
     - child-process lock fields;
     - relative spike windows, measured cloudy fixture, Run E real skip;
     - GSHHG vector dependency + committed clip + pinned checksum;
     - 256×256 fixture window;
     - stale-text cleanup;
     - MERRA-2 cutover note;
     - `swir_threshold` naming.
   - **Iteration 3: waived (closed, not pending).** The escalation guard allows up to 3 iterations,
     not 3 mandatory ones. Iteration 2 found no CRITICAL item. Every rev 4 change is a local edit
     answering a named finding, and the remaining risk is listed under Risks. On 2026-09-14 the user
     instructed that planning cycles not be re-run before the Codex handoff.
   - **B7 (per-product shallow exclusion)** refines the user's DA-3. It is part of the plan submitted
     for approval, so approving the plan accepts it. The flip, if wanted, is to set every
     `ProductSpec.shallow_exclusion_m` equal.

**Gate status: Step 3 plan review ✔ · Step 4 devil's-advocate (2 iterations) ✔ · Step 4.7 outcome
gate ✔ · Step 5 user approval ✔ (2026-09-14).**

## Execution shape

**Fully sequential: 0 → 1 → 2.1 → 2.2 → 2.3 → 3 → 4 → 5 → 6 → 7** `[EXEC-SHAPE]`.

- Each phase consumes the previous one's artifacts. Phase 1's fixtures and spike outcomes feed 2.2
  and 2.3; 2.1's grid and selection feed 2.2; the release model feeds 3.
- Phase 4 has a user gate before 5. Phase 6 needs 5's live API.
- The only file-disjoint pair (5 ∥ 6) is kept sequential; see the alternative above.
- Cost note: a single implementer, so no parallel token multiplication.

| Phase | Surface | Basis |
|---|---|---|
| 0 | main session | small, touches config the user cares about (branch, `.agents/`) |
| 1 | main session | interactive halt gates; long downloads/runs as background commands |
| 2.1–2.3 | main session | judgment-heavy integration against real services |
| 3 | main session | scientific choices (ranges, stretch) need user visibility |
| 4 | main session; backfill as a long background command | user gate on the report |
| 5 | main session | security review |
| 6 | main session | UI judgment + manual acceptance |
| 7 | main session (a sub-agent worker is acceptable for the Phase 7 grep/retire sweep) | mechanical, but ends in a merge gate |

## Open questions

- **Q-A (default recorded).** Phases 2, 3 and 4 each exceed the sub-topic promotion thresholds
  (>5 items, >300 LOC). **Default:** they are executed from this document with sub-phase commits;
  no sub-topic `PLAN.md` is created unless the user asks for one when a phase starts.
- ~~`.agents/` of unknown origin~~ **Resolved 2026-09-14.** `.agents/skills/oceanos-domain/` is a
  project-local skill created deliberately for Codex. Rule for this plan: **`.agents/` stays
  untracked and uncommitted** (Phase 0 sanity check `git ls-files .agents | wc -l` = `0`). Changing
  that requires a documented reason in this section.
- **R2:** analysis zones for La Parguera. Until answered, one whole-AOI zone (D-4).
- **R3:** SSO existence and hosting location. Caddy basic auth until answered.
- **PRD OQ8:** the reviewed scientific AOI boundary, needed before any research-grade output.

## Handoff to implementation

### User-approval gates

1. **Phase 1:** each halt condition (V1 refuted, RSS > 5.5 GiB, V2 refuted incl. Run C, scene A SHA-256 mismatch).
2. **Phase 3:** DA-6 single-scene review (scene A outputs + scene D verdict), and the DA-3 bathymetry dataset choice if none is suitable.
3. **Phase 4:** `BACKFILL_REPORT.md` review before Phase 5.
4. **Phase 6:** `VIEWER_ACCEPTANCE.md`, all 12 items ticked by the user.
5. **Phase 7:** merge into `master`.
6. **Any `[FALLBACK — confirm or override]`** item becoming active: D-4 zones (active from Phase 4 unless R2 is answered).
7. **Any change to an acceptance criterion or a locked Brief decision** discovered mid-flight: stop
   and route to `/planning:plan review`.

### Execution shape (`[EXEC-SHAPE]` tagged)

Sequential, all phases in the main session, per the table above. Every sub-phase is one commit on
`feat/oceanos-pr-mvp`, and its `[TODO]` → `[DOING]` → `[DONE]` tag is updated in the same commit.

#### Decisions made (gate-passed)

| # | Decision | What it changes in the plan | Basis (evidence) |
|---|---|---|---|
| D-1 `[EXEC-SHAPE]` | Retire the L2A band path (band fetch, `normalize_scene`, `process normalize`) in **2.1**, not Phase 7 | 2.1 gains a retire item and a zero-reference grep; the full suite stays green in every phase | `processing/normalize.py:21` and `__main__.py:15` import `MVP_BANDS`; F2/F3 make L2A unusable; the reviewer showed breakage would otherwise be hidden |
| D-2 `[EXEC-SHAPE]` | Coastal buffer starts at **150 m** | Phase 3 `masks.py` default; tunable in config | Brief captured assumption "~100–200 m, fixed empirically after backfill" |
| D-3 `[EXEC-SHAPE]` | Tier upgrade re-acquires the SAFE by `source_id` + SHA-256 instead of keeping it | 2.1 builds re-acquisition; 4 adds `tests/test_tier_upgrade.py`; `contracts.md` reprocessing table updated | Q10 (discard SAFE); Brief criterion "checksum sufficient to re-fetch deterministically"; CDSE products verified online |
| D-4 `[FALLBACK — confirm or override]` | Until R2 is answered, one analysis zone = the AOI water area | Phase 4 `zones.geojson` content | R2 open; T8 needs ≥ 1 zone for pre-extraction |
| D-5 `[EXEC-SHAPE]` | No external basemap; GSHHG coastline GeoJSON gives map context | Phase 6 adds coastline generation; the no-URL grep holds | PRD §12 "External integrations in MVP: satellite data provider and ACOLITE. Nothing else" |
| D-6 `[EXEC-SHAPE]` | Viewer, API and `/data` served same-origin behind Caddy; no CORS | Phase 5 Caddyfile; no CORS config | Viewer boundary `contracts.md` §8; removes a cross-origin credential surface |
| D-7 `[EXEC-SHAPE]` | A4 is enforced by a literal scan with a vocabulary + allow-list; A1–A3 by an import scan | Phase 0 architecture test design | `topology.md` A4 concerns string literals; `l2_flags` is shared vocabulary |
| D-8 `[EXEC-SHAPE]` | Spike outcomes are recorded as an exact `**Outcome (pin 20260421.0): …**` token on each V-row | Phase 1 Sanity grep is non-vacuous | The V2 row already contains "verified", so a bare-word grep would pass today |
| D-9 `[EXEC-SHAPE]` | The selection core lives in `pipeline/plan.py` | 2.1 file name | `contracts.md` §1.1 names `pipeline.plan` |
| D-10 `[EXEC-SHAPE]` | Phase 1 adds Run C (`GMAO_IT_MET`), scene D (cloudy fixture) and a double download of scene A, each with a halt condition | Phase 1 downloads ~2.4 GB instead of ~1.6 GB; two extra ACOLITE runs | Devil's-advocate #4, #13, #14; `acolite_l2r.py:175-195` at the tag |
| D-11 `[EXEC-SHAPE]` | The API listens on a Unix socket behind Caddy (TLS internal, identity headers stripped), not on a trusted loopback IP | Phase 5 config, Caddyfile and probe | Devil's-advocate #12: WSL2 loopback forwarding makes peer-IP trust unsafe |
| D-12 `[EXEC-SHAPE]` | Stale-lock kill guarded by `boot_id` + process start time + cmdline | 2.1 holder record; 2.2 recovery and tests | Devil's-advocate #7: PIDs are reused after WSL restart |

### Mechanical work

- **Commits.**
  - One commit per sub-phase; message `Fase N.M: <name>` in the style of the existing history.
  - The trailer carries the session attribution lines.
  - A structural `ruff format` commit is separate from behavioural ones (Tidy First).
- **Verification checkpoints.** A phase's Sanity Check passes before its tag moves to `[DONE]`.
- **Long operations** (downloads, ACOLITE runs, backfill) run as background commands. Progress is
  read from the JSON-lines event log, never by polling the ACOLITE log.
- **Sequential fallback:** not applicable (no parallel waves).
