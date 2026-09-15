# Design threads — OCEANOS PR

**Status:** rounds 1–3 closed · 2026-09-14 · scope `system` · baseline `master` @ `07ecca4`
**Handoff gate:** first run FAILED on R1 (acquisition undesigned). R1 was closed by round 2 (§H), and
the gate is re-run after that. The user accepted **every recommendation** in round 1 (T1–T26) and in
round 2 (T22a–f), so all of them are `resolved`. Where a thread's text below says
"Recommendation", that is now the decision. Residual items are listed in §G.

**Amendment to the locked Brief (round 2, T22b).** The constraint "The AOI spans at least two tile
columns; `merge_tiles=True` is required" and Q11 are superseded. Tile selection is the minimal
footprint cover, and `merge_tiles` is written only when more than one tile is selected. Evidence:
§H.0 §3. The amendment is recorded in `../PLAN.md` § Resolved after lock.

**Status legend**

- **locked**: already decided in `../PLAN.md` (cited); this document only applies it.
- **proposed**: carries a recommendation and waits for the user.
- **directional**: direction agreed, details deferred.
- **resolved**: confirmed by the user in a round.
- **deferred**: waits for a verification spike (`V#`) or research.

Ordered by how likely the user is to redirect them: public contracts, data shapes and user-facing
surfaces first; mechanical threads last.

---

## A. User-facing surfaces and data shapes

### T6 — What a researcher sees for an unusable observation · **resolved (round 1)**

PRD acceptance requires that "no usable observation" never look like "observed and clear". W4 needs
the researcher to judge whether an anomaly is a cloud edge.

| Option | Effect |
|---|---|
| a. Status only, no rasters | Simplest. The researcher cannot see *why* a date is unusable |
| **b. Restricted release: status + true colour + `l2_flags`, no science layers** | Shows the cloud or coverage problem without offering numbers that failed the gate |
| c. Full release marked `usable=false` | Most information; puts rejected numbers one click away, which is what M5 guards against |

**Recommendation: (b).** M5 (0 false-usable) is protected, because no science value from a failed
gate is displayable. W4 still works.

### T3 — Which products become COGs vs archive-only · **resolved (round 1)**

Q4 lists `rhow_*`, `Rrs_*`, `rhorc_*`, `tur_nechad2016`, `spm_nechad2016`, `chl_re_gons740`, `fai`,
`fait`, `ndvi`. The spectral families are ~11 bands each.

**Recommendation.** COG-publish `tur_nechad2016`, `spm_nechad2016`, `chl_re_gons740`, `fai`, `fait`,
`ndvi`, `l2_flags` and `true_colour`. Keep `rhow_*`, `Rrs_*` and `rhorc_*` **archive-only** in the
MVP. PRD §7 says surface reflectance is "not consumed directly by researchers", and publishing
~33 spectral layers per date multiplies storage and viewer clutter. The archive keeps them, and
releases can add them later without reprocessing (publication profile change → re-enter at P5).

### T4 — Source of the true-colour view · **resolved (round 1)** · *gap between PRD §7 and Q4*

PRD §7 requires a true-colour view; no Q4 product is one.

| Option | Note |
|---|---|
| **a. 3-band byte COG from L2R `rhos` (B04, B03, B02), fixed stretch** | Uses an archived L2R (Q10); land and cloud stay visible, which is the purpose |
| b. ACOLITE's own RGB PNG outputs | Not georeferenced COG; per-scene stretch breaks comparison |
| c. From `rhot` (TOA) | No correction; hazier; still valid as context |

**Recommendation: (a)**, labelled *display-only, not a measurement*, with **one stretch for all
dates** so side-by-side comparison is honest.

### T5 — Unmasked indices (`fai`, `fait`, `ndvi`) · **resolved (round 1)**

ACOLITE computes these over land, cloud and water alike (research C6).

**Recommendation.** Publish ACOLITE's values **unmodified** in the COG. Mask in **statistics**
always (valid-pixel predicate) and in the **viewer** by default (flag overlay on). Rewriting
ACOLITE's numbers before publication would make the COG disagree with the archived NetCDF, and the
lineage (L1) would then need a second transformation to explain.

### T2 — Platform-neutral product keys · **resolved (round 1)**

ACOLITE names spectral variables by wavelength, which differs per platform (`rhow_560` S2A,
`rhow_559` S2B, `rhow_561` S2C). A time series across S2A/B/C keyed on those names splits into three
series.

**Recommendation.** `ProductKey` uses the S2 band name (`rhow_b04`). The actual wavelength goes into
the STAC `eo:center_wavelength` and `ProvenanceRecord`. The `acolite` adapter maps
platform × band → variable name, and no other module sees wavelength-suffixed names (A4).

### T9 — Series statistics · **resolved (round 1)**

**Recommendation.** `valid_pixels`, `valid_fraction`, `mean`, `median`, `p10`, `p90`, `std`.
A valid pixel is: finite ∧ `l2_flags == 0` ∧ inside the AOI ∧ outside the coastal analysis buffer.
Statistics are always computed at full resolution. **Question for the user:** is a zone with a
valid fraction below the observation threshold (20%) shown as a gap, or shown with its low
fraction? Recommendation: show it, with `valid_fraction` visible; the observation-level gate
already hides wholly bad dates.

### T8 — Time-series serving strategy · **resolved (round 1)**

Measured (R-D3): per-request raster reads cost 2606 ms for 500 scenes; an indexed table costs 1.09 ms.

| Option | Cost |
|---|---|
| Per-pixel table | 1.8 M pixels × products × dates → billions of rows. Rejected |
| Only predefined zones | Fast; breaks PRD "a point or region the researcher defines" |
| **Pre-extracted zones + ad-hoc full-resolution reads for drawn geometry** | Zones in ~1 ms; ad-hoc ~2.6 s per 500 dates, well inside M1's 5-minute budget |

**Recommendation: the hybrid.** The response says which path served it. **Question for the user:**
which zones should be predefined for La Parguera (e.g. bay interior, reef crest, shelf edge)? They
are a scientific choice, and they depend on Q12.

### T7 — Provisional vs final products (ancillary tier) · **resolved (round 1)**

The Brief's constraint makes M3 (≤7 days) possible only with `GMAO_IT_MET`.

**Recommendation.** Publish with `tier=provisional` inside the 50-day window. When an observation
ages past cutover + margin (proposed 7 d), the next `update` reprocesses it with `GMAO_MERRA2_MET`.
The profile changes, so a new `RunKey` and a new release are created and the provisional one is
superseded. The tier is visible in the viewer and in provenance. **Question:** reprocess
automatically, or only on operator command? Recommendation: automatically, because M7 budgets
operator time and this is mechanical.

---

## B. Boundaries and identity

### T10 — API shape · **resolved (round 1)**

**Recommendation.** A read-only HTTP service inside `oceanos.api` (contracts §7). No processing
triggers (PRD OQ4 default), so the pipeline stays CLI-only and cannot be started from a browser.
Framework: **FastAPI** (pydantic is already the model layer, which gives schema generation for the
contracts). Alternative: Starlette alone. This is a **new runtime dependency**. Confirm.

### T11 — Authentication and roles · **resolved (round 1)** · *outward-facing*

PRD: named authenticated users, researcher ≠ operator, no institutional IdP unless one exists.

| Option | Note |
|---|---|
| **a. Reverse proxy (Caddy/nginx) terminates auth; passes a verified user + role header** | App holds no passwords; TLS and auth in one tested component |
| b. App-managed sessions with a local user file | More code in the app; password handling becomes ours |
| c. Existing institutional SSO | Only if one exists: **does UNSAAC or the project have one?** |

**Recommendation: (a)**, unless (c) exists. Also needed: **where does this run** (the same machine as
ACOLITE, reachable over VPN/LAN)?

### T12 — Viewer stack · **resolved (round 1)**

**Recommendation.** Leaflet + `georaster-layer-for-leaflet` 4.1.2 + `geotiff` 3.0.5 (versions from
the research), served as static ES modules with **pinned vendored copies and no build step**.
Caveat from the research: **MapLibre and deck.gl were not investigated.** If the viewer is expected
to use either, this thread needs a research pass first.

### T1 — Unit of processing is the overpass · **resolved (round 1)** (derived from Q11 + acceptance)

> **Amended by T22b (round 2):** "every tile intersecting the grid, merged" below is superseded. The run covers the **minimal footprint cover** of the grid, and merge happens only when that cover has more than one tile.

**Recommendation.** One ACOLITE run per AOI × datatake, over every tile intersecting the grid, merged
by ACOLITE. It cannot be per tile: Q11 forbids external mosaicking, and the acceptance criterion "no
partial AOI product" makes the tile set atomic.

### T14 — Run identity and idempotence · **resolved (round 1)**

**Recommendation.** Content-derived `RunKey` + per-execution `RunAttemptId` (type-inventory §1).
Consequence worth confirming: **changing any owned ACOLITE setting marks every observation for
reprocessing** on the next `update`, unless the operator scopes it to a date range.

### T16 — Release model and retention of superseded releases · **resolved (round 1)**

**Recommendation.** Immutable release directories; atomic switch of the STAC item + index row; keep
the **current + 1 previous** release per observation, and collect older ones at P9. Supersession is
always recorded in the index, even after the files are collected.

### T22 — Scope of the upstream acquisition rework · **resolved (round 1)** · *scope question*

This design starts at the normalization boundary, as asked, but its input (L1C SAFE via CDSE OData,
Q2) does not exist yet. Contracts §1 fixes what that layer must deliver.

**Question:** design the acquisition rework (CDSE OData provider, SAFE-level fetch, L1C collection,
extended `SceneMetadata`) in this same design effort, or in a separate pass? Recommendation: **same
effort, as a short thread**. It is small against the existing abstractions, and `/planning:plan`
cannot sequence P0 without it.

### T23 — GeoAI constraints · **resolved (round 1)** · *interpretation needs confirmation*

The request asked the design to respect "las restricciones de GeoIA". **No document in this
repository defines them.** The interpretation below comes from the `geoai-skills` plugin installed
today (v0.1.0) and the `geoai-py` library it wraps.

| geoai-skills capability | Fit for OCEANOS | Reason |
|---|---|---|
| `search-stac` (Planetary Computer) | **no, for production input** | PC's Sentinel-2 collection is L2A, rejected by ACOLITE (F2). *From prior knowledge, not re-verified this session* |
| `download-data` (NAIP) | no | Aerial imagery, not ocean colour |
| `process-raster` clip / mosaic / stack | **no, before ACOLITE**; unnecessary after | Research §5.4: upstream clip, resample and mosaic invalidate or degrade the correction; Q11 forbids external mosaicking |
| `detect-objects` (buildings, cars, ships, solar panels, parking, fields, GroundedSAM) | no | No floating-algae model; GPU-oriented against a no-GPU constraint; model-based sargassum detection is explicitly out of scope (Brief) and a PRD non-goal |
| `inspect-geo` | **yes, as operator/dev tooling** | Inspecting COGs and NetCDF during development and incident review |
| `overture-data` | not needed | GSHHG is the locked coastline source (Q7) |

`geoai-py` is **not installed** in the project environment (verified). **Recommendation:** GeoAI stays
development tooling only. It adds **no runtime dependency** to `pyproject.toml`, and nothing under
`src/oceanos` imports it. **Question:** is this what you meant, or do "GeoAI constraints" refer to a
specific rule set (a course, a lab guideline, a document)? If so, share it and this thread reopens.

---

## C. Mechanics

### T13 — Delivery grid anchoring and misalignment policy · **resolved (round 1)**

Q3 locks that the grid survives after ACOLITE with `assert_aligned`.

**Recommendation.** The grid is fixed per AOI version: EPSG:32619, 10 m, **anchored at the UTM
origin**, so its lines fall on multiples of 10 m. Sentinel-2 MGRS tile grids use multiples of 10 m
too, so an ACOLITE output on the native grid is phase-aligned and conformance is a **window copy with
no interpolation**. If ACOLITE's output is *not* phase-aligned, the stage **fails with
`grid.misaligned` (batch)** rather than resampling scientific values silently. Whether it is aligned
under `merge_tiles` + `limit` + `extend_region` is **V1**.

### T21 — What Fase 5 code survives · **resolved (round 1)** (Q3 + evidence)

Keep `GridSpec`, `metric_crs`, `buffered_aoi` and `assert_aligned`. **Extend** `normalize_band`: a NetCDF
subdataset source, and `int32` in the accepted categorical dtypes for `l2_flags`. **Replace**
`normalize_scene`, which is bound to `MVP_BANDS`. **Retire** `build_grid(reference_path, …)` once an
AOI-anchored builder exists; its tests move to the new builder. **Extract** the staging/rollback
shape into `storage`. Detail in capability-matrix §3.

### T15 — Source of truth · **resolved (round 1)**

**Recommendation.** Manifests on disk (`run-manifest.json`, `release.json`) are authoritative, and
SQLite is derived and rebuildable (topology §2.2). This matches the existing "lost catalog update is
repairable from the manifest" property.

### T17 — Failure taxonomy and retry · **resolved (round 1)**

Contracts §6. Decisions to confirm:

- Batch-scope codes stop the whole run.
- `acolite.ancillary_fallback` is a failure (not published), retried on a later `update`.
- Failed workspaces are kept 14 days.

### T18 — Single writer · **resolved (round 1)**

**Recommendation.** An exclusive `flock` on `data/state/writer.lock`, held by any mutating CLI command.
The API opens SQLite read-only in WAL mode and never takes the lock. This resolves the unenforced
single-writer constraint noted in `CURRENT_STATE.md` §4.

### T19 — Scheduling W1/W2 · **resolved (round 1)**

**Recommendation.** No daemon. CLI verbs are `pipeline backfill --start --end`, `pipeline update`
(new scenes + deferred retries + tier upgrades) and `pipeline reprocess --observation|--range`.
W2 runs from a **systemd timer** (or cron on WSL). Every verb is resumable from the ledger.

### T20 — Module topology · **resolved (round 1)**

Topology §1. New packages: `domain`, `storage`, `acolite`, `index`, `pipeline`, `timeseries`.
`composites/` is retired, and `web/` is added at the repo root. Architecture rules A1–A4 are
enforced by a test.

### T24 — Test-seam posture · **resolved (round 1)** · *confirm before design output is final*

**Recommendation: one primary seam, `AcoliteRunner`.** A `FakeAcoliteRunner` writes fixture outputs
into the workspace: a valid pair of NetCDFs, a skip log, an ancillary-fallback L2R, and a
missing-variable L2W. The full pipeline P0–P9 then runs in the normal suite without ACOLITE. This
mirrors how `httpx.MockTransport` stands in for the network today.

Secondary seams:

- Pure cores (`quality`, `timeseries` aggregation) tested on arrays.
- The API tested against a fixture product tree + SQLite.
- One opt-in `--run-acolite` golden test on a tiny `limit`, excluded by default like
  `--run-integration`.

Fixture NetCDFs must be **produced by a real ACOLITE run at the pin** and then trimmed, not
hand-written, so the fake cannot drift from the real output shape.

### T25 — Configurability · **resolved (round 1)**

**Recommendation.**

- New config sections: `acolite` (paths, pin, timeout), `quality` (policy version + thresholds),
  `publication` (profile), `storage` (tier roots, retention days), `api`.
- `ProductSet` in a versioned `configs/products.yaml`.
- `extra="forbid"` everywhere.
- `netcdf_compression=True` in the owned settings, to cut archive size. ACOLITE's default is `False`
  (research §8.1). Output values are unchanged; confirm on a run.

### T26 — Observability · **resolved (round 1)**

**Recommendation.**

- Each attempt writes a JSON-lines event log (stage start/end, durations, peak RSS, disk use) next
  to its manifest.
- The operator status view reads the index.
- No metrics stack. M7 (operator minutes per month) is measured from those events.

---

## D. Verification spikes (deferred)

| # | What | Why it matters | How | Blocks |
|---|---|---|---|---|
| **V1** | Is ACOLITE's output grid phase-aligned to 10 m UTM multiples under `limit`? **Scope amended by T22b:** single tile (`19QGV`, no `merge_tiles`) is the verified contract for the current AOI; merge + `extend_region` is deferred to a dedicated spike if an AOI needs several tiles (R4, PLAN R-4) | Decides whether conformance is a copy or a failure | ~~Run two same-datatake tiles~~ Run A single tile at the pin; `(x[0] − 5) mod 10 == 0`, `(y[0] − 5) mod 10 == 0`, `abs(pixel size) == 10`. **Outcome (pin 20260421.0): verified** — Run A produced 10 m pixels with centres `x[0]=701155`, `y[0]=1991385`; both centres are 5 mod 10. This is the single-tile contract; no merge was exercised. | T13 |
| **V2** | Is the ancillary fallback detectable as L2R global attributes equal to `uoz_default`/`uwv_default`/`pressure_default`? | Silent-degradation detection (gotcha 3) | **Outcome (pin 20260421.0): verified** — Run B/MERRA2 has exactly `uoz=0.3`, `uwv=1.5`, `pressure=1013.25`, `wind=2.0`; Run A has `0.2862418702`, `4.3052080220`, `1003.4058158184`, `5.9678248541`; Run C/GMAO IT has `0.2945093261`, `4.4086515091`, `1004.8734723421`, `3.3989131011`. | contracts §6 |
| **V3** | GSHHG `land_water_mask` reachability from the S2 flow, its setting names, and whether land shows as NaN or as a flag bit (research U5) | Q7 implementation; the `OwnedSettings` land-mask keys | **Outcome (pin 20260421.0): refuted** — at the pinned tree, `land_water_mask` is defined and re-exported but never called by the Sentinel-2/ACOLITE flow. DA-1 therefore remains authoritative: OCEANOS applies GSHHG itself. | Q7, §4.1 |
| **V4** | Does `l2_flags` carry CF `flag_masks`/`flag_meanings` (research U2)? | Only a convenience: `FlagSpec` comes from resolved settings anyway | **Outcome (pin 20260421.0): refuted** — Run A's real `l2_flags` has only the `grid_mapping` attribute, with no `flag_masks` or `flag_meanings`; `FlagSpec` must come from the resolved settings. | none |
| **V5** | Can the project environment read ACOLITE NetCDF without new dependencies? | Conformance implementation | **Outcome (pin 20260421.0): verified** — project rasterio 1.4.4 / GDAL 3.10.3 opened Run A's real `l2_flags`, resolved `EPSG:32619`, and read the affine transform `(10, 0, 701150, 0, -10, 1991390)`. | none |
| **V6** | Allowed characters and length of ACOLITE `runid` | `RunAttemptId` as `runid` | **Outcome (pin 20260421.0): verified** — `runid=att-20260914T221929Z-spike0001` was accepted and appears in Run A's resolved settings and output filenames. | none |
| **V7** | Real storage per overpass (SAFE × tiles, workspace peak, L2R + L2W compressed, release) | P1 disk budget, retention sizing | **Outcome (pin 20260421.0): verified** — the 801,045,804-byte SAFE produced compressed L2R/L2W of 100,413,193/48,167,667 bytes in 4:55.68 at 1,700,624 KiB peak RSS; A′ produced 289,393,899/303,867,816 bytes in 5:00.17 at 1,556,780 KiB. The derived `acolite.timeout` is 1,200 s (3× Run A rounded up to the next 10 min). | P1 thresholds |
| **V8** | **NEW, blocking (found 2026-09-14 while resolving the usable-fixture contradiction).** Does the pinned settings set (`l2w_mask_threshold=0.05`, glint correction off per Q13) leave usable water pixels over La Parguera? | Product premise (M2, R-7), Q7 threshold, Q13, DA-2 glint gate, OD5 season | **Outcome (pin 20260421.0): refuted for the observed scenes.** The non-water mask compares **TOA** `rhot_1614` > threshold (`acolite_flags.py:63-75`), so glint correction cannot change it. Bit 0 covers 98.9 % (A, 2026-07-02), 99.8 % (D1, 07-05) and 100 % (B/C, 09-13) of the grid. Scene A open-water `rhot_1614` p10/p50 = 0.054/0.058. `flags == 0` = 1.06 % (A). Where bit 0 is set without high-TOA (80 % of A), `TUR`, `SPM`, `rhow`, `Rrs` and `chl_re_gons740` hold the NetCDF fill value `9.969e36`, i.e. **ACOLITE already masked them**; `fai`/`fait`/`ndvi` are populated. Scene geometry: sza ≈ 20–23°, vza ≈ 3°, specular angle ≈ 18–24°, so strong sun glint near nadir in summer is the likely cause (inferred, not yet isolated). **Decision required before Phase 1 closes** (see PLAN Phase 1 halt note). **2026-09-14: user authorized testing option A** (residual glint correction + `l2w_mask_water_parameters=False`, OCEANOS land/cloud masking) via Runs F/G; both runs are complete. **Resolved 2026-09-14 (user "sí"): option A adopted.** Q13 amended (residual glint correction on); `l2w_mask_water_parameters=False`; bit 0 informational only; DA-2 predicate amended; OD5 unchanged; fixtures from Run F + re-runs D2/B2 (PLAN Phase 1). | Q7, Q13, DA-2, OD5 |
| **V5-addendum** | Fill values | Conformance | Rasterio reads the NetCDF `_FillValue` `9.969e36` as a **finite** number unless masked explicitly. Conform must honour `_FillValue` → NaN. | Phase 2.3 |

Additional Phase 1 evidence at pin `20260421.0`:

- Two independent reacquisitions of scene A both produced SHA-256
  `056e58383e9fc1b09b7de2567d046f90f082cc3a6dbee36d353a0d6be631340e`.
- The observed L2R diagnostic attribute names are `ac_aot_550`, `ac_model`, `ac_fit` and
  `ac_nbands_fit`. Run A also carries mean geometry in `sza`, `vza` and `raa`.
- Among 1,046,286 GSHHG water pixels in Run A, `l2_flags` bits 0–6 cover respectively
  `0.989718872`, `0`, `0.002169579`, `0.000003823`, `0`, `0` and `0` of the water pixels.
- Run A includes `acolite_run_att-20260914T221929Z-spike0001_l2r_settings.txt`; its resolved
  exponents are SWIR=0, cirrus=1, TOA=2, negative=3, out-of-scene=4, mixed=5 and DEM shadow=6.

V8 remedy evidence (Runs F/G, 2026-09-14, pin `20260421.0`):

- Run F used scene A with `l2w_mask_threshold=0.05`, residual glint correction enabled with
  method `default` and wave range 1500–2400 nm, and `l2w_mask_water_parameters=False`. The resolved
  tag defaults are `glint_mask_rhos_wave=1600` and `glint_mask_rhos_threshold=0.05`; the run log
  records `Starting glint correction`. It exited 0 in 5:39.97 with peak RSS 1,761,528 KiB.
- The denominator is 962,568 GSHHG-water pixels outside the 150 m land buffer. Before the
  product-finite test, 766,621 pixels pass bits 1/2/3. Candidate-valid fractions are
  `0.796433083` for every `Rrs_*`, `rhow_*` and `rhorc_*` band and for `fai`, `fait` and `ndvi`;
  `0.787873688` for `TUR_Nechad2016_665` and `SPM_Nechad2016_665`; and `0.522220768` for
  `chl_re_gons740`.
- Over the 8,351 water pixels where A and F are both defined, `rhow_1614` median/p90 changes from
  `0.031107130`/`0.042165361` (A) to `0`/`0.003206320` (F), and `rhow_2202` changes from
  `0.028668467`/`0.039515093` to `0.000247538`/`0.002765880`.
- Over A's `flags == 0` water, the `TUR_Nechad2016_665` median changes from `16.679050446` to
  `3.553226709` (8,333 comparison pixels), and the `rhow_665` median changes from `0.036990281`
  to `0.009255467` (8,351 pixels). Thus option A materially changes the values even in A's
  previously unflagged subset; this is evidence for the pending decision, not an adopted remedy.
- Run F per-bit water coverage for bits 0–6 is respectively `0.991324249`, `0`, `0.000521522`,
  `0.203045395`, `0`, `0`, `0`. Bit 3 therefore increases by `0.203045395` from Run A, while bit 0
  is unchanged as expected from its TOA definition.
- Run G selected the lowest-cloud `19QGV` candidate among 12 scenes in 2026-01-01–2026-02-28:
  `S2B_MSIL1C_20260106T150719_N0511_R082_T19QGV_20260106T200359.SAFE`, cloud cover
  `1.526083191496`, catalogue MD5 `bb43672fb494c070ee2dda96e6c9160f`, downloaded SHA-256
  `766f2c2daff22195bb48ebf9089f68b5db92e4e9c4df47ed138bc176bcb082b3`. It exited 0 in 4:46.47
  with peak RSS 1,696,812 KiB.
- Run G has bit 0 water coverage `0.007441552`, `flags == 0` fraction `0.984676407`, and
  `rhot_1610` p10/p50 `0.001000000`/`0.001500000` over 962,568 water pixels. (`rhot_1610` is the
  S2B counterpart to S2A's wavelength-suffixed `rhot_1614`.) Its mean geometry is
  sza/vza/raa `45.014185641`/`3.010486097`/`51.587319350` degrees, with specular angle
  `43.194411629` degrees; A/F's corresponding values are `19.996142849`/`3.000503680`/
  `132.543596959`, with specular angle `22.131066354` degrees. This isolates a strong seasonal/
  geometry association, while the causal interpretation remains an inference.
- Run D2 reprocessed scene D1 with the adopted V8 settings: residual glint correction `True`
  (`default`, 1500–2400 nm), `l2w_mask_water_parameters=False`, `l2w_mask_threshold=0.05` and
  `GMAO_MERRA2_MET`. The log records `Starting glint correction`; L2R and L2W are present and the
  process exited 0 in 5:16.88 with peak RSS 1,760,756 KiB. In the final fixture window its amended
  `TUR_Nechad2016_665` valid fraction, including the finite-product condition, is `0.050418605`,
  inside the required open interval `(0, 0.20)`.
- Run B2 reprocessed scene B with the same adopted settings and `GMAO_MERRA2_MET`. The log records
  `Starting glint correction`; L2R and L2W are present and the process exited 0 in 5:26.08 with peak
  RSS 1,789,052 KiB. Its L2R attributes remain exactly the fallback defaults: `uoz=0.3`, `uwv=1.5`,
  `pressure=1013.25` and `wind=2.0`.
- Uncommitted A/F quicklooks and the full machine-readable measurements remain under
  `.work/oceanos-pr-mvp/spikes/`; shared TUR display percentiles are p02/p98
  `0.255167649`/`37.498705444`.

**Environment prerequisites found and resolved during Phase 1 (historical record):**

- **E1.** `~/acolite` is a shallow clone of `main` at `d61c8de`, not tag `20260421.0` / `f73cbe7`.
  **Resolved:** re-cloned at the tag and verified 2026-09-14.
- **E2.** `~/acolite/data/LUT` was empty (SUMMARY §8). **Resolved:** LUT retrieval and environment
  check pass.
- **E3.** GSHHG was not downloaded (SUMMARY §8). **Resolved:** the pinned OCEANOS-owned archive is
  present and `scripts/fetch_gshhg.sh --check` passes.
- **E4.** The `version=20260421.0` line (Q15) was absent from deployment `config/config.txt`.
  **Resolved:** exactly one version line is present.

---

## E. Dependency order

```text
T22 upstream scope ─┐
T1 overpass unit ───┼─► T14 run identity ─► T15 source of truth ─► T16 releases ─► T6 unusable view
                    │
V1 ─► T13 grid ─────┼─► T21 Fase 5 fate
                    │
T2 keys ─► T3 publish subset ─► T4 true colour ─► T5 masking ─► contracts §4.4 STAC
                    │
T9 statistics ─► T8 series strategy ─► index schema ─► T10 API ─► T11 auth ─► T12 viewer
                    │
T7 tier ◄── V2      T17/T18/T19/T25/T26 mechanical, independent
T23 GeoAI ─ independent        T24 test seams ─ confirm before handoff
```

## F. Round log

| Round | Date | Threads opened | Resolved |
|---|---|---|---|
| 1 | 2026-09-14 | T1–T26, V1–V7 | **T1–T26, all as recommended** ("acepto todas las recomendaciones") |
| 2 | 2026-09-14 | T22a–T22f (from failed handoff gate on R1) | **T22a–T22f, all as recommended** ("acepto"); T22b amends the Brief/Q11 |
| 3 | 2026-09-14 | DA-1…DA-6 (from `/planning:devils-advocate` iteration 1 on PLAN rev 2) | **all as recommended** ("acepto todo"); DA-1 amends Q7 and adds a T5 exception |
| 4 | 2026-09-14 | V8 remedy (Runs F/G evidence) | **option A adopted** ("sí"): Q13 amended, bit 0 informational, DA-2 predicate amended, OD5 kept, fixture sources F/D2/B2/E |

## G. Residuals after round 1

Accepting a recommendation settles the choice. It does not supply facts the recommendation asked for,
and it does not do work the recommendation scheduled.

| # | Residual | From | Kind | Blocks |
|---|---|---|---|---|
| R1 | **The acquisition rework must now be designed in this effort** (CDSE OData provider, SAFE-level fetch, L1C collection, extended `SceneMetadata`) | T22 = "same effort" | **closed by round 2 (§H, T22a–f)** | — |
| R2 | List of predefined analysis zones for La Parguera | T8 | scientific input; depends on the reviewed boundary (T22f / PRD OQ8) | pre-extracted series content only, not the design |
| R3 | Whether an institutional SSO exists; where the service is hosted (same machine, LAN/VPN) | T11 | facts; option (a) reverse proxy applies unless SSO exists | deployment plan, not the design |
| R4 | Whether ACOLITE output is phase-aligned under `limit` (single tile, the default after T22b), and under merge when an AOI needs it | T13 / V1 | verification spike; the policy (copy or fail) is decided | first real run |
| R5 | The meaning of "GeoAI constraints" was confirmed as interpreted in T23 | T23 | closed | — |

Decisions recorded with their accepted defaults:

- T9: a zone below 20% valid fraction is **shown, with its fraction**.
- T7: the tier upgrade is **automatic**.
- T10: **FastAPI**.
- T12: **Leaflet**.
- T24: `FakeAcoliteRunner` as primary seam, **fixtures from a real run at the pin**.

---

## H. Round 2 — T22 deep-dive: L1C acquisition · 2026-09-14

This round was triggered by the handoff gate, which FAILED on R1.

### H.0 Evidence gathered this session (tier 0, executed; not read from documentation)

1. **CDSE OData catalogue query works without authentication.** It was queried for `productType eq
   'S2MSI1C'` intersecting the configured AOI (`-67.10,17.90,-66.95,18.00`), 2026-06-01 → 2026-09-01.
   Result: **92 products, 23 overpasses, all `Online: true`**, every one on relative orbit **R082**
   (S2A, S2B, S2C: a ~5-day revisit when combined; ~9 overpasses per month).
2. **Each overpass returns 4 intersecting tiles**: `19QGV`, `19QFV`, `19QGA`, `19QFA`. MGRS tiles
   overlap, so footprints overlap.
3. **`19QGV` alone fully contains the AOI on 23 of 23 overpasses.** AOI fraction covered by each
   footprint: `19QGV` 1.00, `19QFV` 0.54, `19QGA` 0.10, `19QFA` 0.05. The union always covers, but
   one tile is always enough.
   **This contradicts the Brief's constraint "The AOI spans at least two tile columns;
   `merge_tiles=True` is required"** and the premise of Q11/Q12. Those were derived from the Earth
   Search L2A bands for `19QFA`/`19QFV`, not from L1C footprints.
4. **Product entity fields:**
   - `Id` (UUID), `Name` (`….SAFE`), `ContentLength`, `Online`, `EvictionDate` (`9999-12-31`),
     `S3Path`, `ContentDate`, `GeoFootprint`.
   - **`Checksum: [{MD5}, {BLAKE3}]`. There is no SHA-256.**
   - Attributes: `tileId`, `cloudCover` (whole tile), `relativeOrbitNumber`, `orbitNumber`,
     `platformSerialIdentifier` (`A`/`B`/`C`), `processorVersion` (`05.12`), `productGroupId`
     (datatake, e.g. `GS2B_20260804T150719_049157_N05.12`), `datastripId`, `granuleIdentifier`,
     `processingLevel`/`productType` (`S2MSI1C`).
5. **Authentication for download:**
   - Keycloak password grant, `client_id=cdse-public`, against
     `identity.dataspace.copernicus.eu/auth/realms/CDSE`, using the existing `~/.netrc` machine
     `cdse`. Succeeded.
   - **Access token lives 1800 s; refresh token 3600 s.**
6. **Download:**
   - Both `zipper.dataspace.copernicus.eu` and `download.dataspace.copernicus.eu`
     `…/Products(<Id>)/$value` return `200`, `application/zip`, `Content-Length == ContentLength`
     (789 574 421 B for `19QGV` 2026-08-04). The body starts with `PK\x03\x04`.
   - **The server sends `accept-ranges: bytes` but answered a `Range: bytes=0-1023` request with a
     full `200`.** Resuming a partial download cannot be relied on. The existing `fetch` rule
     ("require 200, reject 206") is already compatible.

### T22a — Discovery client · **resolved (round 2)**

**Recommendation.** Add a new `CdseODataProvider` implementing the existing `SceneProvider.search`
contract.

- It reuses the house hardening: bounded retries, `Retry-After`, no partial results, and a
  pagination cycle guard over `@odata.nextLink`.
- The filter is **`productType eq 'S2MSI1C'` fixed in the adapter**, so an L2A product cannot be
  returned. That satisfies the Brief acceptance criterion by construction.
- OData vocabulary stays inside the adapter, like STAC vocabulary in `sentinel2.py`.
- The Element84 `Sentinel2Provider` is **unwired** from config and CLI but kept until the first L1C
  run succeeds. It is deleted in the plan's cleanup phase (F2: L2A has no use).

### T22b — Tile selection and coverage completeness · **resolved (round 2)** · *amends a locked constraint*

**Recommendation.**

- **Selection:** per overpass, pick the **smallest set of tile footprints whose union contains the
  delivery-grid polygon**. Ties are broken by lower whole-tile `cloudCover`, then by tile id, so
  the choice is deterministic.
- **`merge_tiles=True` is written only when the selection has more than one tile.**
- For the current AOI this selects `19QGV` alone on every observed overpass. That cuts download
  volume ~4× (one ~790 MB SAFE instead of four), and it removes the merge code path from the first
  run.
- Completeness changes from "every intersecting tile present" to **"the union of the selected
  footprints contains the grid polygon"**. The acceptance criterion "no partial AOI product" is
  preserved, and redundant tiles are no longer mandatory.

**This amends** the Brief constraint "The AOI spans at least two tile columns; `merge_tiles=True` is
required" and Q11. Merge stays **supported** for AOIs that need it (Q12 may enlarge the AOI), but it
is no longer **mandatory**. **Needs explicit user confirmation.**

### T22c — Scene-level cloud gate · **resolved (round 2)**

CDSE `cloudCover` is a whole-tile figure.

**Recommendation.**

- Record `max(cloudCover)` over the selected tiles as the observation's discovery cloud value.
- Leave the gate threshold **unset during the bounded backfill**: record the value, exclude nothing.
  This matches the Brief assumption that the threshold is set empirically from the backfill.
- `excluded_scene_cloud` becomes active only once a threshold is configured.

### T22d — Download and integrity · **resolved (round 2)**

**Recommendation.**

- **Transfer.** Streamed download from `download.dataspace.copernicus.eu/odata/v1/Products(<Id>)/$value`
  into a `.part` file.
  - Require `200` and `Content-Length == ContentLength`.
  - **Verify MD5 against the catalogue checksum** (stdlib `hashlib`).
  - **Compute SHA-256** as OCEANOS's own content identity (`InputSetId` is built from it).
  - **Record BLAKE3** from the catalogue without verifying it (verifying would add a dependency;
    MD5 already detects transfer corruption).
- **Resume.** None, because ranges are not honoured (H.0 §6). A failed transfer restarts from zero,
  within the existing bounded retry.
- **Token.** Obtained per product; refreshed when fewer than 300 s remain. Never logged, never written
  to disk.
- **Archive check.** The zip's member list is checked **without extracting**: `MTD_MSIL1C.xml`,
  `GRANULE/*/MTD_TL.xml`, 13 `IMG_DATA/*.jp2`, `QI_DATA/MSK_DETFOO*`. Exactly one granule.
- **Reuse.** The existing `ingestion.fetch` machinery (`.part` → fsync → `os.replace`, manifest,
  re-verification, catalog sync) is kept, with **one asset per scene** (`product`) instead of one
  per band. `MVP_BANDS`/`BAND_ASSETS` are retired.
- **New failure codes:** `input.product_offline` (deferred retry; no LTA ordering in the MVP, since
  all 92 observed products are online), `input.md5_mismatch`, `input.safe_members_missing`.

### T22e — Scene catalog and model changes · **resolved (round 2)**

**Recommendation.**

- **Collection.** `LocalSceneCatalog` gets a `sentinel-2-l1c` collection through its existing
  `collection_id` parameter. The old `sentinel-2-l2a` collection is left untouched
  (`CURRENT_STATE.md` §4).
- **`SceneMetadata`** gains optional fields `processing_level`, `processing_baseline`,
  `relative_orbit`, `datatake_id`, `mgrs_tile`, `source_id`, `checksums`.
- **Wire format.** `SceneSearchResult` moves to `schema_version: "1.1"`; readers accept `"1.0"`.
- **`OverpassId`** is derived from `productGroupId` minus the baseline suffix
  (`S2B_20260804T150719_R082`, with the orbit from `relativeOrbitNumber`).
- **Scene Items** record retention after deletion (Q10): `oceanos:retained: false`, `deleted_at`,
  plus the `source_id` + SHA-256 needed to re-fetch.

### T22f — AOI boundary (Q12) given H.0 §3 · **resolved (round 2)**

Q12 asked to "fit inside 19QFV if scientifically defensible". The evidence shows the configured AOI
already lies **entirely inside `19QGV`**; `19QFV` covers only 54% of it. The engineering motive for
Q12 (avoid multi-tile) is therefore already met.

**Recommendation.** Record Q12's engineering half as satisfied. Keep only its **scientific** half
(the reviewed boundary, PRD OQ8) open as a pre-backfill input. Any future boundary is checked
against the T22b single-tile preference, and multi-tile stays supported.

---

## I. Round 3 — decisions from the adversarial plan review · 2026-09-14

**Evidence** (planner re-verified against a tarball of tag `20260421.0`):

- `land_water_mask` is defined, but its only reference is the re-export in `masking/__init__.py:3`.
- The sensor-merged settings file is `acolite_run_<id>_l2r_settings.txt` (`acolite_l2r.py:530`).
- `delete_extracted_input=False` and `rgb_rhot`/`rgb_rhos=True` (`defaults.txt:591`, `:480-481`).
- `flag_exponent_outofscene=4` (`:265`).
- `netcdf_compression=False` at the tag (`:61`).
- `rhorc` is requested through `l2w_parameters` (`acolite_run.py:40-43`).

### DA-1 — Land mask owned by OCEANOS · **resolved (round 3)** · *amends Q7, adds a T5 exception*

ACOLITE never applies its GSHHG mask at the tag, so Q7 ("land/sea split by
`ac.masking.land_water_mask`") cannot be satisfied inside ACOLITE.

**Decision.**

- OCEANOS rasterizes GSHHG once per delivery grid into a `LandMask`.
- At P5 it sets **water products** to NaN on land. `true_colour` and `l2_flags` are not masked.
- The mask version and hash are recorded in provenance, per product, as an OCEANOS transformation.
- `l2w_mask_threshold=0.05` keeps its cloud and bright-target duty.

**T5 exception.** Published water-product values equal ACOLITE's values **except** on `LandMask`
land pixels, which are NaN. "Water products" = `ProductSpec.land_masked == true`: `tur_nechad2016`,
`spm_nechad2016`, `chl_re_gons740`, `rhow_*`, `Rrs_*`. `fai`, `fait` and `ndvi` stay unmodified per
T5 and are masked at display/statistics time (B9). This keeps the Brief criterion "land excluded from every published water
product".

### DA-2 — Hardened quality gate · **resolved (round 3)**

**Decision.** `QualityPolicy` gains:

- a cloud/toa/swir flag dilation of `cloud_dilation_px`;
- AOT550 and aerosol-model bounds, from `AerosolEvidence` in L2R attributes;
- a glint-angle gate (`glint_angle_min_deg`);
- concrete `RangeRule`s with a maximum offending fraction;
- `min_grid_coverage` (→ `incomplete_coverage`);
- `valid_fraction` computed over `AnalysisMask.water_pixels`.

The numbers are set in Phase 3 from spike data and reviewed at the DA-6 gate.

### DA-3 — Optically shallow water excluded from statistics · **resolved (round 3)**

**Decision.** `AnalysisMask` excludes shallow pixels from statistics, using public NOAA bathymetry
for Puerto Rico. The map keeps them.

**Refined in rev 4 (B7):** the exclusion depth is **per product** (`ProductSpec.shallow_exclusion_m`).
It applies to turbidity, SPM and chlorophyll, and not to `fai`/`fait`/`ndvi`. There is a guard
against too few analysis pixels. This is flagged for user confirmation at Step 5.

Dataset selection and the depth threshold are a Phase 3 research item. If no suitable dataset is
found, the fallback is a per-product caveat plus a user decision.

### DA-4 — Split ACOLITE vs downstream profile · **resolved (round 3)**

**Decision.** `RunKey` = observation + input set + `AcoliteProfileId` (pin, owned settings, grid,
ancillary tier). `ReleaseId` = attempt + `DownstreamProfileId` (product set, quality policy, masks,
publication).

Downstream changes re-enter at P5 from the archive, with no ACOLITE run and no SAFE download.

### DA-5 — Superseded releases not served · **resolved (round 3)** · *amends T16*

**Decision.**

- At P8 the previous release moves to `data/superseded/`, which is not served, inside the same
  commit sequence.
- `data/products/` holds current releases only. P9 keeps one superseded release per observation.
- Tracer-bullet releases are wiped before the backfill.

### DA-6 — Single-scene review gate · **resolved (round 3)**

**Decision.** After Phase 3's real-scene probe, the user (or a researcher) reviews scene A's COGs,
flags and quality verdict before Phase 4. This is PRD rollout step 2.

### DA-3 / DA-2 — Phase 3 values · **resolved with the user (2026-09-15)**

Research artifact: `.work/oceanos-pr-mvp/bathymetry-research/RESEARCH.md` (memory tier, not committed).
Measurements: `.work/oceanos-pr-mvp/spikes/phase3_measurements.json` (`measure_phase3.py`).

- **Bathymetry dataset.** NOAA NCEI CUDEM 1/9 arc-second Puerto Rico, version 2022v2, tiles
  `ncei19_n18x00_w067x00`, `n18x00_w067x25`, `n18x25_w067x00`, `n18x25_w067x25`. Public domain,
  NAD83 + PRVD02 height (≈ local MSL, San Juan 1983–2001; decimetric offset, irrelevant to the cut),
  no nodata over the AOI, AOI water depth p50 12.9 m, max ≈ 25 m. NCEI publishes no checksum:
  `scripts/fetch_bathymetry.sh` pins SHA-256 values measured from the S3 PDS and the Digital Coast
  mirror. Rejected: CRM Vol.9 (3″ ≈ 90 m, mixed datums), NCCOS 2006 LADS lidar (older, 4 m), no USGS
  CoNED TBDEM for Puerto Rico.
- **Shallow exclusion 7 m** for `tur_nechad2016`, `spm_nechad2016`, `chl_re_gons740`; none for
  `fai`, `fait`, `ndvi`. Basis: scene A median turbidity inflates above ~5 m (29 FNU at 0–1 m, 5.2 at
  3–5 m, plateau ≈ 4.3 from 5 m) and two-way pure-water attenuation at 665 nm leaves ≈ 0.24 % at 7 m.
  Analysis pixels: ≈ 902 k for the AOI.
- **Residual-glint gates: strict** — `max_negative_rhos_fraction = 0.10`,
  `max_residual_swir_rhow = 0.02` (clean scene G: 0.008 / 0.001; scene A: 0.20 / 0.052). Scene A is
  therefore an unusable observation (restricted release); scene G is the usable review case.
- **AOT550 ≤ 0.5**, aerosol models MOD1/MOD2 (A 0.28, G 0.055, D 0.63).
- **`chl_re_gons740` is published** as a COG with a strong caveat: red-edge algorithm for productive
  water, not reliable in clear oligotrophic reef water (medians ≈ 10–11 mg m⁻³ in A and G).

### DA-1 amendment — land mask from CUDEM · **resolved with the user (2026-09-15, DA-6 review)**

**Evidence.** GSHHG 2.3.7 level 1 is displaced ≈ 380 m south and ≈ 150 m west over La Parguera and
simplifies the cays. Shifting the GSHHG mask raises agreement with CUDEM land (elevation ≤ 0 m
boundary) from 93.5 % to 96.0 % and with scene-G NDVI land from 91.3 % to 94.3 %; unshifted it marks
≈ 102 k water pixels (≈ 10 km²) as land and leaves ≈ 14 k land pixels unmasked. Review page and
overlay: `.work/oceanos-pr-mvp/da6-review/`.

**Decision.** `LandMask` v2 and the `AnalysisMask` v2 coastal buffer derive from the pinned CUDEM
tiles: land = grid-averaged elevation > 0 m (PRVD02); the 150 m buffer is applied to that land.
GSHHG is no longer read by the pipeline (the Phase 1 fetch script and probe check remain, pending
Phase 7 clean-up). Water products are still NaN on land (T5 exception unchanged). The Phase 1 fixture
window now has 539 land pixels (GSHHG: 3434) and 58 481 water pixels outside the buffer (GSHHG: 53 750).
