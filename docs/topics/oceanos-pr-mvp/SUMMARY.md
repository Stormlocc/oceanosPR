# OCEANOS PR — Where the project stands

**Date:** 2026-09-11 · **Baseline:** commit `acc6072` ("Fase5 complete") · **Status:** discovery and research complete; architecture not yet designed.

One-page entry point to the four documents produced in this phase. Each section links to where the detail lives.

---

## 1. What happened in this phase

Three things, in order: we assessed what exists, we defined what to build, and we established the external facts that constrain how.

| Document | What it answers | Size |
|---|---|---|
| [`CURRENT_STATE.md`](CURRENT_STATE.md) | What the codebase actually is today | 482 lines |
| [`PRD.md`](PRD.md) | What we are building, for whom, measured how | 258 lines |
| [`research/ACOLITE_TECHNICAL_BASELINE.md`](research/ACOLITE_TECHNICAL_BASELINE.md) | What ACOLITE requires and already does | 16 sections |
| `.work/oceanos-pr-mvp/RESEARCH.md` (+ 11 sidecars) | The raw evidence, fetch log, gaps — not committed | memory tier |

---

## 2. Decisions locked

| # | Decision |
|---|---|
| **D1** | Work from **Fase 5** (`acc6072`). It is a detached HEAD; branch `master` is two commits ahead. |
| **D2** | **Fase 6 and Fase 7 are rejected** as unverified (SCL-based QA; in-house NDVI/FAI/RGB). Not to be revived as a shortcut. |
| **D3** | **ACOLITE performs all processing.** |
| **D4** | Primary users are **marine researchers**; a **separate technical operator** runs the pipeline. |
| **D5** | Use cases: **water quality/turbidity + sargassum**. |
| **D6** | Delivery: **internal web application, named authenticated users**. |
| **D7** | Cadence: **historical backfill, then periodic updates** — not real-time alerting. |

---

## 3. What the system is today

The pipeline runs **discovery → local STAC catalogue → verified download → spatial normalization**, and stops. Five bands warped onto a common metric grid as Float32 rasters holding **raw sample values, not reflectance**.

There is no atmospheric correction, no quality masking, no spectral product, no composite, no API, and no way to look at anything. ~1,400 lines of source, 137 passing tests, and genuinely disciplined engineering — atomic publish with rollback, SHA-256 verified downloads, versioned artefacts, and a consistent refusal to invent missing values.

**Four cheap defects to fix early:** a broken `oceanospr` console script, a stale `nasa_oceanos_pr.egg-info/`, an unused `pandas` dependency, and `EARTHDATA_*` variables in `.env.example` that are dead as spelled — but see §5.

Detail: [`CURRENT_STATE.md`](CURRENT_STATE.md).

---

## 4. What we are building

A marine researcher must be able to answer a water-quality or sargassum question about the study area across a date range, **without operating the pipeline and without assistance** — and defend the answer afterwards.

**Seven success metrics with thresholds and windows**, of which two matter most: **M4** (100% of products link to scene, processing version and parameters) and **M5** (zero products marked usable that a researcher judges unusable). M5 is what tests the quality gate; if it exceeds zero, nothing else matters.

**Explicit non-goals:** real-time sargassum alerting, public access, coral/benthic habitat, in-situ validation, re-implementing ACOLITE's science.

Detail: [`PRD.md`](PRD.md).

---

## 5. What the research established

Eighteen facts are now closed. The five that change the plan:

**F1 — The current acquisition path is incompatible with ACOLITE on three independent counts.** Wrong level (L2A is hard-rejected), wrong packaging (loose COG bands, not a `.SAFE`), and destroyed inputs (pre-warping discards the geometry and calibration the correction consumes). **It must be replaced with complete L1C `.SAFE` acquisition**, not adapted. ACOLITE also needs eight bands the current set omits.

**F2 — ACOLITE already does most of what Fase 5 built.** Clipping, resampling, reprojection, masking, flagging and every water-quality algorithm are ACOLITE's. Doing them upstream is duplicated at best and destructive at worst.

**F3 — ACOLITE exits 0 on failure.** Unsupported level, missing footprints, ROI outside the scene, missing settings file — all print, skip, and return success. Confirmed by running it. **Failure detection is a first-class component, not error handling.**

**F4 — Scene-level cloud and pixel-level usability are genuinely separate.** ACOLITE has no scene-cloud concept at all. That gate stays in discovery, permanently; pixel usability is ACOLITE's `l2_flags`. They belong in different components.

**F5 — For sargassum, ACOLITE gives indices, not detection.** `fai`, `afai` and `fait` are native but **unmasked** — computed over land, cloud and water alike. No biomass, no unmixing, no aggregation, no tracking. Wang & Hu's own published method needs all of those on top of the index.

**A correction to an earlier finding:** `CURRENT_STATE.md` called the `EARTHDATA_*` entries dead configuration to delete. They are dead *as spelled* — ACOLITE wants `EARTHDATA_u`/`EARTHDATA_p` — but the requirement they anticipated is real and mandatory. The recommendation changes from **remove** to **rename and wire up**.

Detail, with confidence ratings and the responsibility matrix: [`research/ACOLITE_TECHNICAL_BASELINE.md`](research/ACOLITE_TECHNICAL_BASELINE.md).

---

## 6. What survives, what goes

| Keep | Replace or reconsider |
|---|---|
| Config, AOI handling, the provider abstraction | Discovery **target** — must serve whole L1C products |
| Local STAC catalogue (ACOLITE has none) | Band-level download granularity → whole SAFE |
| SHA-256 manifests, atomic publish, re-verification | Pre-ACOLITE clipping, reprojection, resampling |
| Scene-level cloud gate at discovery | Normalization as a *pre*-ACOLITE step |
| Doing nothing about radiometry (now provably correct) | — |

**Build new:** orchestration and job state, failure detection by log parsing, sargassum logic above the index, and the viewer.

---

## 7. Environment ready

| Component | Location |
|---|---|
| ACOLITE clone (official, `20260421.0` is the pin candidate) | `~/acolite` |
| Runnable environment (gdal 3.13.3, netCDF4, zarr) | `~/micromamba/envs/acolite` |
| Credentials template, permissions set | `~/.netrc` |

`pyproject.toml` and `uv.lock` untouched — installing ACOLITE into the project is an architecture decision, deliberately not taken.

**Outstanding:** EarthData account with **OB.DAAC** and **LP DAAC** approvals (administrative lead time), and CDSE registration. Without EarthData credentials ACOLITE silently substitutes default atmospheric values and produces lower-quality output with no error.

---

## 8. Next

1. **Engineering interview** — the sixteen open questions in the technical baseline §13. The highest-impact single tuning value is `l2w_mask_threshold`: its default masks turbid coastal water as land, which is precisely the water this project measures.
2. **Architecture** — after the interview, not before.
3. **Then** the rollout sequence in PRD §11: single scene end to end → bounded backfill (which measures real cloud sparsity before the viewer is built on top of it) → viewer → periodic updates.

**Still unknown, and each rated for impact:** eleven items in technical baseline §14. None blocks the interview; each should close before its corresponding design decision.
