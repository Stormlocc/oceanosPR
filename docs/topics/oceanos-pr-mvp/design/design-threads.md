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
| **V1** | Is ACOLITE's output grid phase-aligned to 10 m UTM multiples under `merge_tiles=True` + `limit` (+ forced `extend_region`)? | Decides whether conformance is a copy or a failure | Run two same-datatake tiles over the AOI at the pin; compare output `x`/`y` origin mod 10 | T13 |
| **V2** | Is the ancillary fallback detectable as L2R global attributes equal to `uoz_default`/`uwv_default`/`pressure_default`? | Silent-degradation detection (gotcha 3) | **Partly verified by reading code:** `acolite_l2r.py:175-194` sets the defaults, then overwrites them only if the ancillary fetch returns values. Read on the *unpinned* clone. Confirm at the pin with the 2026-08-04 date | contracts §6 |
| **V3** | GSHHG `land_water_mask` reachability from the S2 flow, its setting names, and whether land shows as NaN or as a flag bit (research U5) | Q7 implementation; the `OwnedSettings` land-mask keys | Read `masking/land_water_mask.py` at the pin; one run | Q7, §4.1 |
| **V4** | Does `l2_flags` carry CF `flag_masks`/`flag_meanings` (research U2)? | Only a convenience: `FlagSpec` comes from resolved settings anyway | Inspect an output | none |
| **V5** | Can the project environment read ACOLITE NetCDF without new dependencies? | Conformance implementation | **Verified 2026-09-14:** project rasterio 1.4.4 / GDAL 3.10.3 lists the `netCDF` driver. Still to confirm on a real file: CRS read from the CF grid mapping | none |
| **V6** | Allowed characters and length of ACOLITE `runid` | `RunAttemptId` as `runid` | Read `acolite_run.py` at the pin | none |
| **V7** | Real storage per overpass (SAFE × tiles, workspace peak, L2R + L2W compressed, release) | P1 disk budget, retention sizing | Measure during the bounded backfill (PRD rollout step 3) | P1 thresholds |

**Environment prerequisites found (not design threads, but blocking any run):**

- **E1.** `~/acolite` is a shallow clone of `main` at `d61c8de`, not tag `20260421.0` / `f73cbe7`.
  **Re-clone at the tag.** Verified 2026-09-14.
- **E2.** `~/acolite/data/LUT` is still empty (SUMMARY §8).
- **E3.** GSHHG is not downloaded (SUMMARY §8).
- **E4.** The `version=20260421.0` line (Q15) is not yet added to the deployment `config/config.txt`.

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
