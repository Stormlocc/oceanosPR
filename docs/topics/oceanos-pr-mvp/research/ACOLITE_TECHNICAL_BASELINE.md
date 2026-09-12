# ACOLITE Technical Baseline — OCEANOS PR

**Purpose:** resolve external technical facts about ACOLITE before the engineering-interview and architecture stages, so the team neither rebuilds what ACOLITE provides nor feeds it inputs it cannot use.

**Everything here is pinned to ACOLITE release `20260421.0`** (published 2026-04-21T12:45:10Z, commit `f73cbe73887c2b114d9d3c70865effee73871525`) unless stated otherwise. Research date: 2026-09-11.

**Status:** research complete and independently verified. **This document records facts and their consequences. It does not decide the architecture** — §13 lists what remains a decision.

**Baseline compared against:** the OCEANOS PR system as assessed in `../CURRENT_STATE.md` (Fase 5, commit `acc6072`).

**Confidence is marked per conclusion: HIGH / MEDIUM / LOW.**

---

## 1. Executive conclusions

### C1 — The current acquisition path is incompatible with ACOLITE, on three independent counts. **HIGH**

OCEANOS today discovers Sentinel-2 **L2A** via STAC, downloads **five COG bands** (B02, B03, B04, B08, B11), and warps them to a project grid. Each of those three choices independently disqualifies the result as ACOLITE input:

1. **Wrong level.** `acolite/sentinel2/l1_convert.py:96-98` hard-rejects anything whose `PROCESSING_LEVEL != 'Level-1C'`. L2A is surface reflectance — the *output* of atmospheric correction, not its input.
2. **Wrong packaging.** ACOLITE requires the complete `.SAFE` tree. The XML metadata is not decoration: `QUANTIFICATION_VALUE` and `RADIO_ADD_OFFSET` define the DN→reflectance conversion, and the granule XML supplies the sun/view angle grids the aerosol retrieval interpolates on.
3. **Destroyed inputs.** Pre-warping discards exactly the geometry and calibration the correction consumes.

It cannot be adapted incrementally. **The acquisition stage must be replaced with complete L1C `.SAFE` acquisition.** ACOLITE also needs eight bands the current set omits: B01, B05, B06, B07, B8A, B09, B10, B12.

### C2 — ACOLITE already performs most of what Fase 5 built. **HIGH**

Clipping, resampling to a single grid, reprojection, masking, flagging, and every water-quality algorithm are ACOLITE's. Doing any of them upstream is at best duplicated work and at worst destructive (§5). The pipeline's remaining jobs are **acquisition, orchestration, failure detection, cataloguing, and everything downstream of `l2_flags`**.

### C3 — ACOLITE fails silently, and this is the single most important operational fact. **HIGH — confirmed by execution**

Unsupported processing level, missing detector footprints, ROI outside the scene, missing settings file, nonexistent input path — every one prints a message, skips, and **exits 0**. Verified empirically this session:

```
EXIT_missing_settings=0     → "Settings file /tmp/nope.txt does not exist."
EXIT_no_settings_arg=0      → "No settings file given"
EXIT_bad_inputfile=0        → "Path /tmp/acotest/NOT_A_SCENE.SAFE does not exist."
```

`grep -n "sys.exit"` over `launch_acolite.py`, `acolite_run.py`, `acolite_l1r.py` and `sentinel2/l1_convert.py` returns **zero hits**. **Success must be asserted from output files plus the run log, never from an exit code.** Mitigating detail: `defaults.txt:207` sets `verbosity=5`, so skip messages do print under default settings — log-scraping is a viable detection mechanism.

### C4 — `l2w_parameters` defaults to `None`, and without it there is no L2W file at all. **HIGH**

`acolite_l2w.py:51-53` returns immediately. A pipeline that forgets this setting produces L2R surface reflectance and no water products, silently.

### C5 — ACOLITE has no scene-level cloud concept. Pixel-level and scene-level usability are genuinely separate. **HIGH**

`sentinel2/metadata_scene.py` never reads `CLOUDY_PIXEL_PERCENTAGE`; `config/defaults.txt` has no cloud-percentage setting of any kind. Scene-level cloud filtering is **entirely a discovery-stage responsibility** and stays in OCEANOS; pixel-level usability is **entirely ACOLITE's** `l2_flags`. This directly answers the PRD's usability-mask requirement.

### C6 — Sargassum: ACOLITE gives indices, not detection. **HIGH**

`fai`, `fai_rhot`, `afai`, `afai_rhot` and `fait` are native. `fait` is already a binary floating-vegetation classifier tuned for turbid water. But there is **no sargassum detection, no species discrimination, no biomass conversion, no aggregation, no drift tracking** — and critically, all three index families set `mask = False`, so they are computed over land, cloud and water alike. Wang & Hu's own published AFAI method requires classification, **linear unmixing**, and gridded aggregation on top of the index; ACOLITE supplies none of those.

### C7 — Pin the release tag; a clone cannot report its own version. **HIGH**

`main` is **88 commits** ahead of `20260421.0` (~one every other day), including behaviour-affecting renames. Worse, `config/config.txt` in the source repo carries **no `version=` key**, so `acolite/__init__.py` falls back to a pseudo-version derived from the *filesystem mtime* of `.git/HEAD`. Our own install reports `Generic GitHub Clone c2026-09-11T19:09:09` — the date it was cloned, not the code it contains. **This breaks PRD metric M4 (100% traceability) by construction** unless mitigated (§10).

### C8 — GPLv3, and internal use carries no source obligation. **HIGH**

Obligations attach to *conveying*, not to running. Invoking ACOLITE as a separate process is lower coupling than importing it, and costs nothing because ACOLITE's own documented interfaces are a CLI and a Docker image.

---

## 2. Evidence table

| # | Claim | Sources | Tier | Confidence |
|---|---|---|---|---|
| 1 | L2A hard-rejected at `PROCESSING_LEVEL != 'Level-1C'` | `sentinel2/l1_convert.py:96-98` @ pinned tag; manual §3.3; **re-derived by independent verifier** | 0/1 | **HIGH** |
| 2 | Complete SAFE required; two XML files + JP2s + `MSK_DETFOO` | `sentinel2/safe_test.py`, `l1_convert.py` | 0/1 | **HIGH** |
| 3 | Zipped SAFE accepted directly (`extract_inputfile=True`) | `acolite/identify_bundle.py`; manual §4.1 | 0/1 | **HIGH** |
| 4 | Loose JP2/COG band files are not a valid input | `identify_bundle.py`, `l1_convert.py`, `safe_test.py` | 0/1 | **HIGH** |
| 5 | Clipping/resampling happen at L1R, before correction; `res_method='average'` hardcoded | `l1_convert.py:282-283`; **verifier confirmed** | 0/1 | **HIGH** |
| 6 | `s2_target_res` default 10, values {10,20,60} | `defaults.txt:72`; manual §4.8.2; `projection.py:67` | 0/1 | **HIGH** |
| 7 | Multi-tile via `merge_tiles`, same orbit, ±600 s | `l1_convert.py`, `multi_tile_extent.py`; manual §4.1 | 0/1 | **HIGH** |
| 8 | L1R→L2R→L2W chain; L2W accepts only L2R | `acolite_l2w.py:85-87`; manual §2.5 | 0/1 | **HIGH** |
| 9 | `l2w_parameters=None` → no L2W file | `defaults.txt:229`; `acolite_l2w.py:51-53`; `acolite_run.py:258-260`; **verifier confirmed** | 0/1 | **HIGH** |
| 10 | `l2_flags` int32 bit field; bits 1/2/4/8/16/32/64 | `acolite_flags.py:77,97,123,125,147,170,184`; `defaults.txt:261-267`; **verifier confirmed** | 0/1 | **HIGH** |
| 11 | Runtime `flag_value` is **47**, behaving as 15 for S2 only because bit 32 is VIIRS-gated | `acolite_l2w.py:175-181`; `defaults.txt:242`; `acolite_flags.py:154`; **verifier correction** | 0 | **HIGH** |
| 12 | No scene-level cloud percentage anywhere in ACOLITE | `sentinel2/metadata_scene.py` tag list; `defaults.txt` sweep | 0/1 | **HIGH** |
| 13 | `tur_nechad2016` / `spm_nechad2016` carry per-MSI-band calibrations | `data/Shared/algorithms/Nechad/Nechad_calibration_201609.txt` | 0/1 | **HIGH** (coefficients) / **MEDIUM** (literature attribution) |
| 14 | `tur_dogliotti2015` uses a MODIS calibration for all sensors | manual §5 verbatim warning; `Dogliotti/defaults.txt` | 1 | **HIGH** (vendor self-warning) |
| 15 | `chl_oc2`/`chl_oc3` carry S2-specific coefficients | `data/Shared/algorithms/chl_oc/defaults.txt` | 0/1 | **HIGH** (values) / **MEDIUM** (attribution to Pahlevan 2020) |
| 16 | FAI/AFAI/FAIT are native and **unmasked** (`mask = False`) | `acolite_l2w.py` FAI/AFAI/FAIT handlers | 0/1 | **HIGH** |
| 17 | AFAI implemented but **absent from the 20260421.0 manual** | `acolite_l2w.py:1235-1258`; `parameter_labels.txt:115-120`; **verifier extracted all 67 manual pages: 0 hits for `afai`** | 0/1 | **HIGH** |
| 18 | AFAI is red-edge based, developed for **MODIS**, and its published method requires unmixing | Wang & Hu 2016 (Elsevier/RSE); Frontiers 2023 review; CARICOOS operational product | 2/3 | **HIGH** |
| 19 | ACOLITE's `fai` uses ρs, not the ρrc of Hu (2009) — published thresholds not portable | manual §5 (FAIT note); `acolite_l2w.py`; Hu 2009 (RSE); JAXA GCOM-C FAI ATBD | 1/3 | **HIGH** |
| 20 | NetCDF4 is the authoritative format; every stage reads/writes it | `nc_write.py`; all consumer modules | 0/1 | **HIGH** |
| 21 | **No Zarr writer exists**; Zarr is input-only | exhaustive tree sweep (2675 blobs, `truncated:false`); `acolite/output/` listing; `defaults.txt` sweep | 0 | **HIGH** |
| 22 | GeoTIFF/COG is per-dataset export; loses global attributes | `output/nc_to_geotiff.py`; manual §2.5 | 0/1 | **HIGH** |
| 23 | CLI `--cli --settings=`, Python API, official DockerHub images | `launch_acolite.py`; manual §3.8 | 0/1 | **HIGH** |
| 24 | Run writes log + two settings files (user, resolved) | `acolite_run.py:57,149,178`; **verifier confirmed filename by execution** | 0/1 | **HIGH** |
| 25 | **Exits 0 on failure** | `launch_acolite.py` bare returns; zero `sys.exit` hits; **verifier executed three failure classes** | 0 | **HIGH** |
| 26 | Latest release `20260421.0`, commit `f73cbe73…` | GitHub Releases API; `git rev-list -n1`; **verifier confirmed** | 0 | **HIGH** |
| 27 | `main` is **88** commits ahead | `GET /compare/20260421.0...main` → `ahead_by: 88`; **verifier corrected 89→88** | 0 | **HIGH** |
| 28 | Clone reports mtime-derived pseudo-version | `acolite/__init__.py:108-135`; `config/config.txt` has no `version` key; **observed in our install** | 0 | **HIGH** |
| 29 | GPLv3, `LICENCE.txt`, SPDX `GPL-3.0` | `LICENCE.txt` (674 lines); GitHub licence API | 0/1 | **HIGH** |
| 30 | v3-only vs v3-or-later unresolved | `LICENCE.txt`, `README.md`, 8 modules grepped — **zero per-file headers** | 1 | **LOW — unresolved** |
| 31 | EarthData credentials needed; silent fallback to defaults without them | README; `config/config.txt`; `defaults.txt` | 1 | **HIGH** |

**Verification:** an independent fresh-context verifier graded the research off disk, re-derived six claims against the pinned source, and executed ACOLITE to test the exit-code finding. **Criterion 7 (all-HIGH): PASS.** **Criterion 4 (independent corroboration): PASS for the parameter/behaviour body; FAIL for four algorithm-provenance claims**, of which the load-bearing one (AFAI) was closed this session with three non-RBINS pools. The remaining three are low severity — the coefficient *values* the pipeline consumes are verified config facts; only the literature attribution rests on one pool.

---

## 3. Sentinel-2 input contract

### 3.1 What ACOLITE accepts

| Question | Answer | Confidence |
|---|---|---|
| Processing level | **Level-1C only** | HIGH |
| Is L1C "recommended"? | **Required.** ACOLITE *is* the atmospheric correction; it needs TOA reflectance plus geometry | HIGH |
| Is L2A accepted? | **No** by the standard `--cli --settings=` flow. A non-default `sentinel2/l2_convert.py` exists but is not wired into `acolite_run`/`acolite_l1r`, accepts only S2A/S2B, and its `L2A` output cannot reach L2W | HIGH (scoped) / MEDIUM (universal) |
| Complete SAFE required? | **Yes** — directory tree, not a band collection | HIGH |
| Zipped SAFE? | **Accepted directly** (`extract_inputfile=True`); budget disk for zip + expansion | HIGH |
| Individual JP2 bands? | **Insufficient** — fails bundle identification, has no DN→reflectance constants, has no geometry | HIGH |
| Platforms | S2A, S2B, **S2C** | HIGH |

### 3.2 Metadata files ACOLITE actually reads

| Path | Supplies |
|---|---|
| `<SAFE>/MTD_MSIL1C.xml` | `SPACECRAFT_NAME`, `PROCESSING_LEVEL`, `PROCESSING_BASELINE`, **`QUANTIFICATION_VALUE`**, **`RADIO_ADD_OFFSET`**, `NODATA`, spectral info, `SOLAR_IRRADIANCE` |
| `<SAFE>/GRANULE/<g>/MTD_TL.xml` | `SENSING_TIME`, `TILE_ID`, **sun zenith/azimuth 5×5 km grids**, **per-detector view angle grids**, projection/geoposition |
| `<SAFE>/GRANULE/<g>/IMG_DATA/*.jp2` | the 13 TOA band rasters |
| `<SAFE>/GRANULE/<g>/QI_DATA/MSK_DETFOO*` | detector footprints — **required** by the default `geometry_type=grids_footprint`; missing → scene skipped |
| `<SAFE>/GRANULE/<g>/AUX_DATA/AUX_*` | optional (`s2_auxiliary_include`, default False) |

**Not read:** `MSK_CLOUDS`, `MSK_CLASSI`, `MSK_QUALIT`, `INSPIRE.xml`, `manifest.safe`. ESA's own cloud masks are ignored entirely.

### 3.3 Consequences of supplying L2A

The bundle is identified as Sentinel-2 (identification routes on `SPACECRAFT_NAME`, not level), reaches `l1_convert`, hits the level guard, prints `Processing of <bundle> Sentinel-2 Level-2A data not supported`, and `continue`s. `acolite_run` then sees an empty file list and skips. **No L1R, no L2R, no L2W, exit 0.** This is C3's failure mode in its most likely form.

### 3.4 Multiple tiles over one AOI

- `merge_tiles=True` merges several SAFEs into one L1R **before** correction.
- Same orbit only; `check_time` rejects tiles >600 s apart; `check_sensor` requires matching sensors.
- With a `limit`, `extend_region` is forced `True` and every tile is warped onto the same ROI grid.
- Without a `limit`, also set `merge_full_tiles=True` or it merges to the first tile's extent.
- `s2_dilate_blackfill=True` removes seam lines between receiving stations.
- **A single SAFE with several granules is a different case and is unsupported.**

### 3.5 RECOMMENDED ACQUISITION CONTRACT — **HIGH**

Per scene, the acquisition layer must deliver:

1. **Level:** Sentinel-2 MSI **Level-1C** only. **Reject L2A at discovery time** — do not let it reach ACOLITE, which will skip it without a non-zero exit.
2. **Form:** the **complete `.SAFE`**, as extracted directory or original `.zip`. Never a band subset, never re-packed, never re-projected, never re-compressed.
3. **Granularity:** exactly one granule per SAFE.
4. **Preserved verbatim:** `MTD_MSIL1C.xml`, `GRANULE/<g>/MTD_TL.xml`, all 13 `IMG_DATA/*.jp2`, `QI_DATA/MSK_DETFOO*`.
5. **Platform:** S2A/S2B/S2C. **Record `PROCESSING_BASELINE`** — baseline ≥ 04.00 carries `RADIO_ADD_OFFSET`, which ACOLITE applies; nothing upstream may apply it.
6. **Multi-tile AOI:** acquire all intersecting L1C SAFEs from the **same orbit and datatake**, hand ACOLITE the comma-separated list with `merge_tiles=True`. **Do not mosaic upstream.**
7. **Source:** any distributor serving the unmodified SAFE. Copernicus Data Space Ecosystem is the reference.

### 3.6 ACOLITE ships its own acquisition — relevant, but not a drop-in

`acolite/api/` contains `stac`, `cdse`, `earthdata`, `earthexplorer`, `s3`, plus `get_scene.py`.

- `get_scene(scene)` routes `S2A`/`S2B`/`S3A`/`S3B` → CDSE, Landsat prefixes → EarthExplorer, `PACE_OCI` → EarthData. **Note: no `S2C` prefix at this tag** — an S2C product name falls through to `Could not identify download source`. **MEDIUM** (unverified whether `main` fixed it).
- **The STAC client is not generic.** `acolite/api/stac/query.py` defaults to `base_url='https://stac.core.eopf.eodc.eu/'`, `collection='sentinel-2-l1c'`, and its docstring says *"create stac query for S2 zarr data"*. It is the discovery half of the **Zarr** input path, not a SAFE discovery client. **HIGH**

**Consequence:** whichever route is chosen, **the pipeline's discovery layer must target a catalogue that serves whole L1C products, not per-band assets.** Element84 Earth Search's `sentinel-2-l2a` COG collection — the current target — is the wrong shape twice over.

---

## 4. ACOLITE processing model

| | **L1R** | **L2R** | **L2W** |
|---|---|---|---|
| **INPUT** | L1C `.SAFE` (or `.zip`) + ROI settings | L1R NetCDF | L2R NetCDF **only** |
| **PROCESS** | SAFE discovery → XML parse → grid at `s2_target_res` → clip from `limit` → per-pixel geometry from angle grids via detector footprints → gdal-warp read (`average`) → `rhot = (DN + RADIO_ADD_OFFSET)/QUANTIFICATION_VALUE` → NODATA→NaN → optional `polygon_clip` | ancillary retrieval (ozone/WV/pressure) → optional DEM pressure → gas transmittance → Rayleigh correction → LUT interpolation → **aerosol retrieval by dark spectrum fitting** → optional interface/glint correction | compute `l2_flags` → derive `rhow_*`/`Rrs_*`/`rrs_*` with water mask → compute each requested algorithm → apply per-parameter masking |
| **OUTPUT** | `rhot_<nm>` ×13, `lon`/`lat`, `sza`/`vza`/`raa` | `rhos_<nm>` + copied `rhot_*`; optional `rhorc_*`, `Ed_*` | `l2_flags` (always) + exactly the requested parameters |
| **TRIGGER** | always | always | **`l2w_parameters` non-empty — default `None`** |
| **RESPONSIBILITY** | **ACOLITE** | **ACOLITE** | **ACOLITE** for implemented algorithms; **downstream** for everything else |

**File naming:** `<SENSOR>_<YYYY_MM_DD_HH_MM_SS>_<tile_code>[_<region>]_<TYPE>.nc`; level recorded in global attribute `acolite_file_type`.

**Wavelength suffixes differ per platform** and must not be hard-coded — **HIGH**:

- **S2A:** 443, 492, 560, 665, 704, 740, 783, 833, 865, 945, 1373, 1614, 2202
- **S2B:** 442, 492, 559, 665, 704, 739, 780, 833, 864, 943, 1377, 1610, 2186
- **S2C:** 444, 489, 561, 667, 707, 741, 785, 835, 866, 947, 1372, 1612, 2191

**AC methods:** `dark_spectrum` (default, recommended), `exponential` (legacy), `radcor` (explicit adjacency correction).

**Band dropping:** bands below `min_tgas_rho=0.70` get **no `rhos_` dataset at all** — typically the 945 nm water-vapour band on S2. **A consumer must not assume `rhos_*` mirrors `rhot_*` one-for-one. HIGH**

**Auxiliary levels irrelevant to S2:** `L2T` (thermal, Landsat), `L1R_pan` (no S2 pan band), `L2R_pans` (S2 not listed).

---

## 5. Spatial-processing responsibilities

### 5.1 Where clipping happens

**First, at L1R conversion, strictly before the atmospheric correction.** Resolution order in `acolite_run.py`: `polylakes` → `polygon` → `limit` → station box → `limit_buffer`; then `l1_convert` computes the pixel subset and a single `warp_to` that clips *and* resamples the bands, the geometry grids and the detector footprints **together on one grid**.

### 5.2 The settings

| Setting | Default | Meaning |
|---|---|---|
| `limit` | `None` | Bounding box, decimal degrees, **`S,W,N,E` order** |
| `polygon` | `None` | Polygon file, or WKT/GeoJSON string |
| `polygon_limit` | `True` | Crop to the polygon's envelope |
| `polygon_clip` | `False` | Set everything outside the polygon to NaN — **this is how a non-rectangular AOI is produced** |
| `extend_region` | `False` | Output covers the whole ROI even where the scene does not |
| `limit_buffer` / `_units` | `None`/`degrees` | Grow the ROI (`d`/`m`/`k`) |
| `s2_target_res` | `10` | Output resolution {10, 20, 60} |
| `merge_tiles` / `merge_full_tiles` | `False`/`False` | Multi-tile merge |
| `output_projection*` family | `False` | Explicit CRS/resolution, applied **after** the chain by default |
| `reproject_before_ac` | `False` | Project the L1R before correction |

**Precedence:** polygon wins over a user `limit` when `polygon_limit=True`; the station box applies only if `limit is None`. Exact behaviour when both `polygon` and `limit` are given is **MEDIUM** — the `polygon_check` body was not read.

### 5.3 The decision input: download-complete vs pre-clip

**Evidence points to option (1): hand ACOLITE the complete unmodified SAFE and let it subset. HIGH**

The reasons are factual, not stylistic:

- ACOLITE already performs the clip, the resample, and optionally the reprojection.
- Its clip is applied to bands + geometry grids + detector footprints together on one grid. **An upstream clip cannot reproduce the geometry half at all.**
- The DSF needs dark-target statistics: `dsf_aot_estimate=tiled`, `dsf_tile_dimensions=600,600` (6×6 km at 10 m), `dsf_min_tile_cover=0.10`. **A small pre-clipped AOI reduces usable tiles and changes the aerosol retrieval.** `limit_buffer` exists precisely to widen a ROI when more context is needed.
- Upstream's own caveat cuts the same way: `reproject_before_ac` *"may give slightly different results due to DSF running on projected/unprojected data"*.

**The one caveat in the other direction:** full-scene processing is RAM-heavy and produces ~10 GB L1R / ~12 GB L2R per full S2 tile at 10 m. **Giving ACOLITE a `limit` is the sanctioned way to bound that** — which is still option (1), just parameterised.

**Operative rule: clip with ACOLITE's `limit`/`polygon`, never with an upstream warp.**

### 5.4 Pre-ACOLITE operations that invalidate or degrade the correction — **HIGH**

| Operation | Verdict | Why |
|---|---|---|
| Using L2A instead of L1C | **Invalidates — hard stop** | Scene skipped at the level guard |
| Band subsetting to 5 bands | **Invalidates** | Fails bundle identification; DSF fits over 400–900 nm needing B1–B8A; cirrus needs B10; non-water mask needs B11; glint uses B11/B12; FAI needs 1610 nm |
| Reprojection to a project grid | **Invalidates the reader, degrades the AC** | No longer a SAFE — no ingest path at all |
| External resampling to 10 m | **Degrades and duplicates** | ACOLITE uses `average`; an external bilinear/cubic warp changes the band-to-band radiometric consistency the DSF depends on |
| Applying DN→reflectance yourself | **Invalidates** | Double-applies `RADIO_ADD_OFFSET`/`QUANTIFICATION_VALUE` |
| Discarding `MTD_TL.xml` or `MSK_DETFOO` | **Invalidates** | No geometry for LUT interpolation; `"No footprint files found"` → skip |
| External mosaicking | **Degrades** | Loses per-tile geometry and the orbit/time guards |
| JP2 → COG conversion | **Not supported** | The reader globs `*.jp2`; a `.tif` is skipped |
| GDAL pre-clip to a small AOI | **Degrades** | Removes DSF dark-target context, and still fails the SAFE check |

**Every one of these describes something the current OCEANOS pipeline does.**

---

## 6. Product inventory

Products are requested via `l2w_parameters` (comma-separated, lower-cased before dispatch; **written variable names are not lower-cased** — `Rrs_665`, not `rrs_665`, and `rrs_*` is a *different* subsurface product). Wildcards `*` expand over available wavelengths. **Units and map scaling live in `config/parameter_labels.txt`.**

### 6.1 Water reflectance

| Parameter | Variable | Definition | Units | Masked |
|---|---|---|---|---|
| `rhot_*` | `rhot_<nm>` | TOA reflectance | `1` | no |
| `rhos_*` | `rhos_<nm>` | Surface reflectance from AC | `1` | no |
| `rhorc_*` | `rhorc_<nm>` | Rayleigh-corrected | `1` | no |
| `rhow_*` | `rhow_<nm>` | Water reflectance = `rhos` + water mask | `1` | **yes** |
| `Rrs_*` | `Rrs_<nm>` | Remote-sensing reflectance = `rhos/π` | `sr^-1` | **yes** |
| `rrs_*` | `rrs_<nm>` | Subsurface = `Rrs/(0.52+1.7·Rrs)` (Lee 2002) | `sr^-1` | **yes** |

### 6.2 Turbidity

| Parameter | Algorithm | Bands | Units | S2-calibrated? |
|---|---|---|---|---|
| **`tur_nechad2016`** | Nechad 2009 **recalibrated Sept 2016 for L8 and S2** | red default; `_red`/`_nir`/`_<nm>` | **FNU** | **YES.** Per-MSI-band A/C: B4 665 (366.14, 0.19563), B5 705, B6 740, B7 783, B8 842, B8A 865 |
| `tur_nechad2009` / `…ave` | Nechad 2009 | 600–900 nm | FNU | Generic |
| `tur_dogliotti2015` | Dogliotti 2015 red/NIR switching | red + NIR | FNU | **Generic — manual warns verbatim: "Published calibration for MODIS is used for all sensors."** |
| `tur_novoa2017` | Novoa 2017 switching | multi-band | FNU | Generic; writes `TUR_Novoa2017_switch` |

### 6.3 Suspended particulate matter

| Parameter | Algorithm | Units | S2-calibrated? |
|---|---|---|---|
| **`spm_nechad2016`** | Nechad 2010 **recalibrated 2016 for L8/S2** | **g m^-3** | **YES.** B4 665 (342.10, 0.19563) … B8A 865 (2932.21, 0.21151) |
| `spm_nechad2010` / `…ave` | Nechad 2010 | g m^-3 | Generic |
| `spm_novoa2017` | Novoa 2017 | g m^-3 | Generic |

**The 2016 recalibration covers B4–B8A only — there is no blue/green turbidity or SPM product. HIGH**

### 6.4 Chlorophyll-a

**Blue-green (open/clear water):**

| Parameter | Reference | Units | S2 status |
|---|---|---|---|
| `chl_oc2` / `chl_oc3` | Pahlevan et al. 2020 | mg m^-3 | **S2-specific coefficients** for S2A/S2B/S2C |
| `chl_oc2f` / `chl_oc3f` | Franz et al. 2015 | mg m^-3 | **Landsat-8 coefficients reused** — the file's own comment says so |
| `chl_oc4`/`oc4m`/`oc5` | O'Reilly & Werdell | mg m^-3 | **Not for S2** (OLCI/MERIS/VIIRS only) |

**Manual caveat, verbatim:** *"these products should be used with care in coastal and inland waters, especially in the presence of sediments and CDOM."* — directly relevant here.

**Red-edge (turbid/productive — the S2-oriented family):**

| Parameter | Reference | Bands | Built-in checks |
|---|---|---|---|
| `chl_re_gons` / `…740` | Gons et al. 2002 | 665, 704, 783 / 740 | Only where `rhos_664 > 0.005` and `rhos_704/rhos_664 > 0.63`; negatives masked |
| `chl_re_moses3b` / `…740` | Moses et al. 2012 | 665, 704, 783 / 740 | negatives masked |
| `chl_re_mishra` | Mishra & Mishra 2012 | 665, 704 | negatives masked |
| **`chl_re_bramich`** | Bramich et al. 2021 — **an updated Gons for Sentinel-2** | 665, 704, 783 | — |
| `ndci` | Mishra & Mishra 2012 | 665, 704 | none |

Each has a `_nocheck` variant that disables its validity screen.

### 6.5 Other families

| Family | Parameters | S2 support |
|---|---|---|
| **QAA** | `qaa`, `qaa5`, `qaa6`, `qaa_v*_a_*`, `_bbp_*`, `_Kd_*` (`m^-1`), `KPAR`, `Zeu` | L8/L9, **S2A/S2B** |
| **P3QAA** | `p3qaa`, `p3qaa_zSD` (**m**, Secchi depth), `p3qaa_Kd_*`, `p3qaa_eta` | L5/L7/L8/L9, **S2A/S2B**, PlanetScope, Pléiades, … |
| **Hue angle** | `hue_angle` (**degrees**) | L8, **S2A/S2B** |
| **Indices** | `ndvi`, `ndsi` (+`_rhot`/`_rhos` variants) | all; S2 default `ndvi_wave=665,835` |
| **Thermal / OLH** | `bt*`, `olh`, `rhos_613` | **Landsat only, not S2** |

### 6.6 Verdict — generic vs S2-calibrated — **HIGH**

**Explicitly calibrated or published for Sentinel-2:** `tur_nechad2016`, `spm_nechad2016`, `chl_oc2`/`chl_oc3`, `chl_re_bramich`, and the `740` red-edge variants.

**Generic, merely running on S2 bands:** `tur_nechad2009`/`spm_nechad2010` (+`ave`), `tur_novoa2017`/`spm_novoa2017`, `chl_oc2f`/`chl_oc3f`, `ndvi`, `ndsi`, **`fai`/`afai`**.

**Generic with an explicit upstream warning:** `tur_dogliotti2015` — MODIS calibration for all sensors. **This is the algorithm most likely to be adopted by default in a coastal pipeline, and it is not S2-calibrated.**

**In code but not in the manual — UNVERIFIED, do not adopt without reading the handler:** `tur_dogliotti2022`, `chl_crat*`, `chl_ci`, `chl_ocx`, `chl_oc3s`, `hue_angle_pitarch`, the Jiang TSS path.

### 6.7 Sargassum and floating algae

| Parameter | What it is | Bands on S2 | Masked |
|---|---|---|---|
| `fai` / `fai_rhot` | FAI (Hu 2009): NIR minus a red↔SWIR linear baseline | B4, **B8A**, B11 | **no** |
| `afai` / `afai_rhot` | AFAI (Wang & Hu 2016): red-edge minus a red↔NIR baseline | B4, **B6**, B8A | **no** |
| `fait` | FAI **adapted to turbid water** (Dogliotti 2018) — **already a 0/1 classifier** | B2, B3, B4, B8A, B11 | **no** |

`fait` applies a FAI threshold, then a red-reflectance screen (`fait_red_threshold=0.08`, rejects turbid water), then CIELAB L (cloud screen) and a-coordinate screens (`fait_a_threshold_MSI=0`). **It is the closest thing ACOLITE offers to an out-of-the-box floating-vegetation detector, and it was designed for turbid coastal water.**

**Three caveats that matter for the sargassum use case — all HIGH:**

1. **FAI selects B8A (865 nm), not B08 (833 nm).** A pipeline acquiring only B08 cannot reproduce ACOLITE's band choice.
2. **ACOLITE's `fai` is computed on ρs; Hu (2009) defined FAI on Rayleigh-corrected reflectance.** **Published FAI thresholds are therefore not directly transferable.** To get the literature-native form, request `rhorc_*` and compute it downstream, or use `fai_rhot`.
3. **AFAI is undocumented in the 20260421.0 manual** (verifier extracted all 67 pages: zero hits). It works, but it carries no documentation-stability guarantee. **AFAI was also developed for MODIS**, so its use on S2 is a sensor transfer — it belongs with the generic algorithms.

**FAI and AFAI do not measure biomass — HIGH.** They measure how far one band sits above a linear interpolation between two flanking bands, in dimensionless reflectance units. They are raised by clouds and cloud edges, sun glint, whitecaps and foam, shallow bright bottom, submerged vegetation, **terrestrial vegetation (nothing masks land)**, ships and wakes, and thin cirrus. The value is not linear in biomass: a pixel partly covered by a dense mat and one fully covered by a thin mat can return the same index. **Wang & Hu's own published method requires classification with gradient correction and cloud masking, linear unmixing, and gridded aggregation on top of the index** — independently confirmed against Elsevier/RSE, a Frontiers review, and CARICOOS's operational Caribbean product.

**Recommended starting set** (a proposal for the interview, not a decision):

```
l2w_parameters=rhow_*,Rrs_*,tur_nechad2016,spm_nechad2016,chl_re_gons740,chl_oc3,fai,afai,fait,ndvi
```

---

## 7. Quality and flags inventory

### 7.1 `l2_flags`

**Name `l2_flags`, type `int32`, written into every L2W file unconditionally.** Bit positions are *configurable settings*, so a pipeline should read them from the resolved run settings rather than hard-code them — though shipped defaults have been stable.

| Setting | Bit | Value | Meaning |
|---|---|---|---|
| `flag_exponent_swir` | 0 | 1 | **Non-water.** `rhot` at ~1600 nm > `l2w_mask_threshold=0.0215` |
| `flag_exponent_cirrus` | 1 | 2 | **Cirrus.** `rhot` at ~1373 nm > 0.005 |
| `flag_exponent_toa` | 2 | 4 | **High TOA.** any band 400–2500 nm > 0.3 |
| `flag_exponent_negative` | 3 | 8 | **Negative `rhos`** in 400–900 nm |
| `flag_exponent_outofscene` | 4 | 16 | **Out of scene** (`rhot` is NaN) |
| `flag_exponent_mixed` | 5 | 32 | VIIRS I/M consistency — **never set for Sentinel-2** |
| `flag_exponent_dem_shadow` | 6 | 64 | Terrain shadow (`dem_shadow_mask=True`, default off) |

**The runtime mask constant is 47, not 15 — HIGH, and this is a correction the verifier caught.** `defaults.txt:242` sets `l2w_mask_mixed=True`, so `acolite_l2w.py:175-181` builds `1+2+4+8+32 = 47`. It *behaves* as 15 for Sentinel-2 only because the mixed-pixel block is gated on `'VIIRS' in sensor`. **Anyone writing masking code against `flag_value`, or reusing this for another sensor, must use 47.** Bit 16 is computed but deliberately excluded from the mask — those pixels are already NaN.

**Masks are spatially smoothed:** `l2w_mask_smooth=True`, `l2w_mask_smooth_sigma=3` applies a Gaussian filter to TOA data *before* thresholding. They are not pure per-pixel thresholds.

### 7.2 Cloud, land, glint

- **There is no cloud detection algorithm.** Cloud is caught indirectly by three TOA thresholds (cirrus, high-TOA, non-water). **ESA's `MSK_CLOUDS`/`MSK_CLASSI` are never read.**
- **There is no coastline-based land mask in the default path.** Land is excluded by the same SWIR threshold that defines non-water. **`l2w_mask_threshold=0.0215` is the single most consequential tuning knob**: turbid coastal water can exceed it at 1600 nm and be **masked as land**. The manual's own worked example raises it to `0.05`.
- **Glint: two distinct mechanisms, both off by default.** `dsf_interface_reflectance` (wind-speed-based interface correction) and `dsf_residual_glint_correction` (SWIR-based, Harmel 2018). The DSF's aerosol retrieval is relatively glint-insensitive, but *"the sun glint signal will however still be present in the resulting surface reflectance."*

### 7.3 AC failure signalling

**There is no explicit "AC failed" flag.** Failure surfaces four ways:

1. **Per-pixel implausibility** → negative `rhos` → bit 3. Closest thing to an AC-failure flag.
2. **Band dropped entirely** below `min_tgas_rho=0.70` — no `rhos_` dataset at all.
3. **LUT boundary** — `dsf_allow_lut_boundaries=False`; geometry beyond `sza_limit=79.999`/`vza_limit=71.999` is not silently clamped.
4. **Whole-scene skip** — print, `continue`, **exit 0**.

### 7.4 NoData

NaN everywhere — in NetCDF, and in exported GeoTIFFs (`gdal.Translate(..., noData=np.nan)`). `s2_dilate_blackfill` dilates the blackfill mask when merging tiles.

### 7.5 Scene-level vs pixel-level — explicit verdict

**They are NOT both present. ACOLITE has only the pixel-level concept. HIGH**

`metadata_scene.py` extracts a fixed tag list that **does not include `CLOUDY_PIXEL_PERCENTAGE`**; `defaults.txt` has no cloud-percentage setting; no scene-level cloud statistic is written.

**Consequence for the PRD:** the two gates must be designed separately and live in different components. Scene-level cloud filtering belongs to **discovery** (STAC `eo:cloud_cover`, CDSE `cloudCover`) — which OCEANOS already has. Pixel-level usability belongs to **ACOLITE** (`l2_flags`). **Recommended consumption pattern: persist `l2_flags` with every product, treat `l2_flags == 0` as fully usable, and compute the per-AOI valid-pixel fraction from the flags rather than from any scene-level number.**

---

## 8. Output-format findings

### 8.1 NetCDF4 is authoritative — **HIGH**

Every stage writes NetCDF4 and every stage consumes it. `nc_to_geotiff`, `acolite_map`, `project_acolite_netcdf`, `crop_acolite_netcdf`, `acolite_flags` all take NetCDF input. **Nothing in ACOLITE reads a GeoTIFF back.**

**Global attributes:** `generated_by='ACOLITE'`, `generated_on`, `contact`, **`acolite_version`**, `Conventions='CF-1.7'`, `projection_key`; plus scene attributes `sensor`, `isodate`, `granule`, `mgrs_tile`, `tile_code`, `acolite_file_type`, `limit`/`sub`, `proj4_string`, `pixel_size`, `zone`, and per-band `<b>_wave`/`<b>_name`/`<b>_f0`.

**Dimensions: exactly two — `x` and `y`. No time dimension, no band dimension.** Each band is its own 2-D variable. **This is the single most important structural fact for anyone planning a datacube: ACOLITE NetCDFs are one-scene, 2-D-per-variable files.**

**Geospatial:** a scalar CRS variable carries CF grid-mapping attributes; 1-D `x`/`y` coordinate variables; optional 2-D `lon`/`lat`.

**Per-variable attributes** come from `config/parameter_cf_attributes.json` plus algorithm-supplied `algorithm`, `reference`, `standard_name`, `long_name`, `units`, `dataset`.

**Provenance in the file:** `acolite_version`, `generated_on`, `granule`, `mgrs_tile`, `isodate`, `limit`, per-variable `algorithm`/`reference`. **Not in the file: the settings used** — those go to sidecar text files (§9).

**Compression is OFF by default** (`netcdf_compression=False`) — notable given ~10 GB L1R / ~12 GB L2R per full tile at 10 m.

### 8.2 GeoTIFF / COG

Opt-in per file type (`l2w_export_geotiff` etc., all `False`). **One GeoTIFF per dataset**, named `<netcdf basename>_<dataset>.tif`, NoData NaN. **COG supported** via `format='COG'` with `export_cloud_optimized_geotiff=True`. **What is lost: all NetCDF global attributes** — no `acolite_version`, no per-variable `algorithm`/`reference`, no `l2_flags` semantics.

### 8.3 Zarr — input only

**There is no Zarr writer. HIGH** — established by an exhaustive tree sweep (2675 blobs, `truncated:false`), the `acolite/output/` listing, a `defaults.txt` sweep, and manual §4.2 + §7. `acolite/zarr/` contains three files that only *read* Zarr metadata, used to classify EOPF-format Sentinel-2/Sentinel-3 inputs (new in 20260421.0), which are then written out as an ordinary **L1R NetCDF**.

**Zarr is a way to feed ACOLITE the new EOPF products, not a way to get Zarr out of it.** Any Zarr/datacube store is a downstream conversion the pipeline owns.

### 8.4 Verdict (reported, not decided)

**NetCDF4 is the processing format of record. GeoTIFF/COG and PNG are terminal publication artefacts.** Note `l2r_delete_netcdf`/`l2w_delete_netcdf` allow keeping only GeoTIFFs — at the cost of losing the global attributes, which is a provenance loss, not merely a format choice.

---

## 9. Automation and reproducibility findings

### 9.1 Execution methods — **HIGH**

```bash
python launch_acolite.py --cli --settings=/path/settings.txt
python launch_acolite.py --cli --settings=... --inputfile="a.SAFE,b.SAFE" --output=/out
python launch_acolite.py --retrieve_luts --sensor S2A_MSI,S2B_MSI,S2C_MSI
```

- **`--cli` is mandatory** — without it the GUI launches.
- **`--settings` is required** in CLI mode; a missing or nonexistent path prints and returns **exit 0**.
- **Python API:** `ac.acolite.acolite_run(settings, inputfile=None, output=None)`, settings being a path *or a dict*. Individual stages callable directly.
- **Docker: officially supported**, documented in manual §3.8, images `acolite/acolite:all_latest` / `tact_latest` on DockerHub. **Nothing Docker-related exists in this repository** — README, `environment.yml`, `acolite.spec` and the full tree show no Dockerfile; the images and their Dockerfiles live in `acolite_tools` and on DockerHub. *(This was a genuine README-vs-manual conflict; the manual is the release's documentation of record.)*

### 9.2 Settings precedence — and a real trap

Lowest to highest: `config/defaults.txt` → `config/defaults/<SENSOR>.txt` → user settings → CLI overrides. Sensor defaults apply **only for keys the user did not set**.

**Upstream's explicit warning:** *"Do not copy the full defaults.txt file to create a settings file, as this will override some of the sensor specific defaults."* **This is a trap for a pipeline that wants fully explicit configuration** — writing every key silently defeats layer 2, changing `dsf_aot_estimate`, `dsf_wave_range`, `dsf_tile_dimensions`, `s2_target_res`, `resolved_geometry`, `ndvi_wave` and `sensor_noise` for S2. **Keep settings files minimal.**

### 9.3 Reproducibility artefacts

Each run writes into the output directory:

| Artefact | Content |
|---|---|
| `acolite_run_<runid>_log_file.txt` | full stdout/stderr tee; first lines carry ACOLITE version, Python version, platform, run id |
| `acolite_run_<runid>_l1r_settings_user.txt` | **only user-supplied settings** — the intent |
| `acolite_run_<runid>_l1r_settings.txt` | **fully resolved settings** after sensor defaults merged — **the reproducible one** |

`runid` defaults to a timestamp and **can and should be set explicitly**, keyed to the pipeline's own job id. Do **not** enable `delete_acolite_run_text_files`.

| Capture target | How |
|---|---|
| **Run configuration** | archive both settings files; the resolved one is authoritative |
| **ACOLITE version** | `acolite_version` NetCDF attribute + first log line — **but see §10.2** |
| **Input products** | `inputfile` in settings; NetCDF `granule`/`mgrs_tile`/`isodate`. **ACOLITE does not checksum inputs — record product id and checksum yourself** |
| **Output products** | the Python API's returned `processed` dict is **the only structured success signal ACOLITE offers**, and it is unavailable from the CLI. From the CLI, enumerate the output directory — there is no manifest |
| **Logs** | the run log — **and it must be parsed, not merely archived**, because it is the only place a skipped scene is reported |

### 9.4 Failure detection — **HIGH**

Assert success from the expected `*_L2W.nc` **plus** a log scan for the known skip messages: `Processing of ... not supported`, `File not recognised`, `Multi granule files are no longer supported`, `No footprint files found`, `Longitude/Latitude limits outside`, `Time difference too large`, `Sensors do not match`.

### 9.5 Operational prerequisites

- **Pre-fetch LUTs** at image-build time (`--retrieve_luts --sensor S2A_MSI,S2B_MSI,S2C_MSI`); the manual recommends exactly this for Docker. LUT size and whether a fully offline run works once cached is **UNVERIFIED** (§14).
- **EarthData credentials** (`EARTHDATA_u`/`EARTHDATA_p`, or `.netrc` machine `earthdata`) with **OB.DAAC Data Access** and **LP DAAC Data Pool** approvals. **Without them, and with `ancillary_data=True` (the default), ACOLITE silently falls back to `uoz_default=0.3`, `uwv_default=1.5`, `pressure_default=1013.25`** — a quality difference with no error. **Assert on this.**

---

## 10. Version and licensing findings

### 10.1 Version — **HIGH**

| | |
|---|---|
| **Latest stable** | `20260421.0`, published 2026-04-21T12:45:10Z, commit `f73cbe73887c2b114d9d3c70865effee73871525` |
| **Scheme** | `YYYYMMDD.N` — **not semantic versioning**, so no compatibility signal in the number |
| **Cadence** | Irregular: ~1–3 releases/year, ten in five years, with a **15-month gap** between 20231023.0 and 20250114.0 |
| **Drift** | `main` is **88 commits** ahead (verified `ahead_by: 88`) |
| **Changelog** | **No `CHANGELOG.md` exists.** The change record is manual §7 plus GitHub release notes |
| **Currently used by this repo** | **None.** ACOLITE is not a dependency, not installed in the project venv, not on `PATH`, not vendored. This is a fresh pin decision, not an upgrade |

**Recommendation (a recommendation, not a decision): pin the tag `20260421.0`.** Grounded in observed behaviour: `main` moves ~one commit every other day; recent commits rename product identifiers (`S2R_L1R` → `L1R_S2R`, 2026-09-09) which would break a pipeline keyed on variable names silently; there is no semver contract and therefore no patch-only track; and the manual is versioned with the release, so tracking `main` means running code the shipped manual does not describe — already demonstrable, since `afai` exists in code but not in the 20260421.0 manual.

**Upgrade policy to consider:** treat each new tag as requiring re-validation — diff `config/defaults.txt` and the manual's version history, re-run a reference scene, compare `rhos_*` and the L2W parameters before promoting.

### 10.2 The version-provenance defect — **HIGH, and it bites the PRD directly**

`acolite/__init__.py:108-135` takes `version` from `config/config.txt` if present; **the source repository's `config.txt` has no `version` key**, so it falls back to a pseudo-version derived from the *filesystem mtime* of `.git/HEAD` or `.git/FETCH_HEAD`.

Our own install reports `Generic GitHub Clone c2026-09-11T19:09:09`.

**Consequences:**

- **The `acolite_version` attribute on every NetCDF records when the clone was made, not which code produced the file.**
- Two machines on the same commit report different versions; the same machine re-fetching reports a new version with no code change.
- **PRD metric M4 (100% of products link to their processing version) cannot be met by a clone install as-is.**

**Mitigation (mandatory, and cheap):** record the git commit SHA independently into your own run manifest, **and/or** add an explicit `version=20260421.0` line to `config/config.txt` in the deployment image. The latter is a one-line change to a config file, not to code, and makes the NetCDF attribute self-describing.

### 10.3 Licensing — **HIGH except where noted**

- **GNU GPL version 3**, verbatim, at `LICENCE.txt` (British spelling — scanners looking for `LICENSE` will miss it). GitHub SPDX `GPL-3.0`. Copyright RBINS 2014–2026.
- **"or later"? UNRESOLVED (LOW).** No per-file or README notice choosing v3-only or v3-or-later was found; 8 core modules grepped returned **zero licence headers**. ~519 modules unchecked.

| Action | Obligation under the text |
|---|---|
| Run unmodified ACOLITE internally | **None** beyond keeping the licence in force |
| Modify ACOLITE, keep changes internal | **None** (no conveying) |
| Expose ACOLITE-derived results over an internal or public API without shipping ACOLITE | **Not conveying** — §0: *"Mere interaction with a user through a computer network, with no transfer of a copy, is not conveying"* |
| Publish maps/products derived from ACOLITE | **No obligation in the text** — the GPL covers the program, not its data output |
| Ship ACOLITE to a third party | Full §4/§5/§6: notices, licence copy, complete corresponding source, modification notices with dates |
| Ship a Docker image containing ACOLITE | §6 applies — conveying a non-source form |

**External process vs library import.** The licence text contains no occurrence of "process", "subprocess", "linking" or "library". Invoking ACOLITE as a **separate process** means your orchestration code is not a modified version of ACOLITE and nothing is conveyed — the lowest-coupling option, and the one ACOLITE's own documentation describes. **Importing it as a library** puts both in one address space; whether that makes your program a work "based on the Program" under §5 is **not settled by the licence text** and is **UNRESOLVED**. Either way, §2's no-conveying rule governs the practical outcome while nothing leaves the organisation — **the distinction becomes decisive only if the application is ever distributed.**

**Not legal advice; this reports only what the licence text supports.**

---

## 11. OCEANOS vs ACOLITE responsibility matrix

Built from the verified ACOLITE findings above plus a full reading of the OCEANOS PR baseline (`acc6072`). **This is the parent's project-fit assessment (outcome-gate criterion 8).**

| Capability | OCEANOS currently does | ACOLITE does | Keep in OCEANOS | Remove / reconsider | Evidence |
|---|---|---|---|---|---|
| **Scene discovery** | STAC Item Search against Earth Search, collection `sentinel-2-l2a`; pagination, cycle detection, bounded retries, no-partial-results | `api/stac/query.py` (hardwired to EOPF EODC, `sentinel-2-l1c`, for **Zarr**); `api/cdse/query.py` | **KEEP the provider abstraction and the hardening** — it is better than ACOLITE's narrow client | **RECONSIDER the target**: must serve whole **L1C** products, not per-band L2A COG assets | §3.1, §3.6; baseline `SceneProvider`/`Sentinel2Provider` |
| **Scene download** | Five COG bands; SHA-256 manifest, preflight, atomic publish, resume, re-verification of every recorded band | `cdse.download`, `get_scene` | **KEEP the integrity machinery** — SHA-256 manifests, atomic publish and re-verification exceed anything ACOLITE offers | **REMOVE the band-level granularity.** `MVP_BANDS`/`BAND_ASSETS`/asset-resolution must become whole-SAFE acquisition | §3.5; baseline `ingestion/fetch.py` |
| **Local STAC catalogue** | PySTAC catalogue, provenance namespace, dedup, atomic writes, portable relative links | **Nothing** | **KEEP entirely.** ACOLITE has no catalogue concept | — | §4; baseline `catalog/local.py` |
| **Normalization to a common grid** | `normalize_scene`/`GridSpec`: warp 5 bands to one metric grid, Float32, NaN nodata, exact-alignment assertion | Clips + resamples to `s2_target_res` at L1R; optional `output_projection*` post-AC | **RECONSIDER — as a *post*-ACOLITE step only**, if an exact delivery grid is required | **REMOVE as a pre-ACOLITE step.** There it is actively destructive | §5.4; baseline `processing/normalize.py` |
| **Clipping to AOI** | `geometry_mask` on buffered AOI after warp | `limit` / `polygon` / `polygon_clip` at L1R, **before** correction, applied to bands + geometry + footprints together | — | **REMOVE.** Pre-clipping removes DSF dark-target context and cannot clip the geometry half at all | §5.1, §5.3, §5.4 |
| **Reprojection** | `build_grid` via `calculate_default_transform`; AOI reprojection via pyproj | Keeps native UTM; `output_projection*` family, post-AC by default | **RECONSIDER** — only if the delivery grid must differ from UTM, and then **use ACOLITE's own** | **REMOVE as a pre-ACOLITE step** — the reprojected rasters are no longer a SAFE, so there is no ingest path | §5.2, §5.4 |
| **Resampling** | bilinear (continuous) / nearest (categorical) | **`res_method='average'` hardcoded** at read time | — | **REMOVE.** External bilinear/cubic changes the band-to-band radiometric consistency the DSF depends on | §5.4; `l1_convert.py:282` |
| **Mosaicking / multi-tile** | **Nothing** — one scene per invocation | `merge_tiles` before AC, same-orbit and ±600 s guards, per-tile geometry retained | — | **ADOPT ACOLITE's.** External mosaicking degrades the correction | §3.4, §5.4 |
| **Pixel QA / masking** | **Nothing** at this baseline | `l2_flags` int32 bit field, seven named steps, spatially smoothed | **KEEP consumption** — persist `l2_flags`, derive per-AOI valid fractions, define "usable product" | — | §7.1; `CURRENT_STATE.md` §2.3 |
| **Scene-level cloud metric** | `eo:cloud_cover` from STAC (whole-scene, not AOI-specific) | **Nothing — no scene cloud concept at all** | **KEEP.** This gate is genuinely and permanently OCEANOS's | — | §7.5 |
| **Metadata extraction** | STAC properties only; **no SAFE/XML parsing; no solar or viewing geometry captured** | Full SAFE XML parse: calibration constants, sun/view angle grids, detector footprints | **KEEP** the catalogue-level discovery metadata | — | §3.2; `CURRENT_STATE.md` §2.6 |
| **Radiometry (DN→reflectance)** | **Nothing** — scale/offset neither captured nor applied | Applies `(DN + RADIO_ADD_OFFSET)/QUANTIFICATION_VALUE` | **KEEP DOING NOTHING.** The baseline's inaction is now provably correct — pre-scaling would double-apply | — | §5.4; `CURRENT_STATE.md` §2.8 |
| **Water-quality algorithms** | **Nothing** (the Fase 7 attempt is rejected) | Turbidity, SPM, chlorophyll, QAA/P3QAA, hue angle, indices | — | **ADOPT ACOLITE's.** Re-implementing is explicitly a PRD non-goal | §6; PRD §3 |
| **Floating-algae indices** | **Nothing** (the Fase 7 FAI attempt is rejected) | `fai`, `afai`, `fait` — **unmasked** | **KEEP** everything above the index: masking, thresholding, aggregation, tracking | — | §6.7 |
| **Sargassum detection / biomass** | Nothing | **Nothing** | **BUILD.** Neither system provides it; Wang & Hu's own method needs unmixing | — | §6.7 |
| **Atomic publish + rollback** | Staging dir → verify → backup → `os.replace` → restore on failure | **Nothing** | **KEEP.** ACOLITE writes in place with no transactional guarantee | — | `CURRENT_STATE.md` §3.2 |
| **Failure detection** | Exceptions and non-zero exit codes | **Exits 0 on failure** | **KEEP AND EXTEND.** Assert output files exist *and* scan the run log | — | §1 C3, §9.4 |
| **Orchestration / scheduling / job state** | **Nothing** | **Nothing** | **BUILD.** The gap both systems leave, and the one PRD workflows W1/W2 depend on | — | `CURRENT_STATE.md` §6; PRD §6 |

### 11.1 Project fit — how this lands against the PRD

- **PRD open questions 1, 2 and 3 are now answered** (§12). The rollout's step 1 ("resolve the ACOLITE input question before implementing anything") is complete.
- **PRD §7's placeholder is resolvable.** "Water-clarity measure" → `tur_nechad2016` + `spm_nechad2016`; "floating-vegetation indicator" → `fai`/`afai`/`fait`; "usability mask" → `l2_flags`; "surface reflectance" → `rhos_*`/`Rrs_*`.
- **PRD metric M4 is at risk and now has a named mitigation** (§10.2).
- **PRD risk "storage growth"** is quantified: ~10 GB L1R + ~12 GB L2R per full tile at 10 m, uncompressed by default — and a full SAFE is larger than the 5-band set being downloaded today. The `limit` setting is the sanctioned bound.
- **PRD's separate-operator model fits ACOLITE's shape well** — a CLI/Docker process per scene with an explicit `runid` is exactly what an operator-run pipeline wants.
- **One PRD constraint is now known to be wrong in spirit.** `CURRENT_STATE.md` §2.13 listed the `EARTHDATA_*` entries in `.env.example` as dead configuration to delete. They are dead *as spelled* (ACOLITE wants `EARTHDATA_u`/`EARTHDATA_p`), but the requirement they anticipated is real and mandatory. **Recommendation changes from "remove" to "rename and wire up."**

---

## 12. Decisions now considered factual and CLOSED

These are no longer open questions. They are established facts, all **HIGH** confidence, all primary-sourced and independently verified.

| # | Closed | Supersedes |
|---|---|---|
| **F1** | ACOLITE requires **complete Sentinel-2 L1C `.SAFE`** bundles (zip or directory), one granule, all 13 bands, with product XML, granule XML and detector footprints intact | PRD open question 1; `CURRENT_STATE.md` open question 3a |
| **F2** | **L2A is rejected** by the standard flow and cannot reach L2W by any path | PRD open question 1 |
| **F3** | **Loose COG/JP2 band files are not a valid input.** The current five-band acquisition must be replaced, not adapted | `CURRENT_STATE.md` §2.7 |
| **F4** | **ACOLITE owns clipping, resampling and (optionally) reprojection**, performed at L1R before the correction. Pre-ACOLITE spatial processing degrades or invalidates it | PRD open question 3b (partially — see §13.2) |
| **F5** | **ROI is passed as `limit=S,W,N,E` or `polygon`**; output resolution as `s2_target_res` ∈ {10,20,60} | — |
| **F6** | Stage chain is **L1R → L2R → L2W**, and **`l2w_parameters` must be set explicitly** or no L2W file is produced | — |
| **F7** | **NetCDF4 is the authoritative output.** GeoTIFF/COG is per-dataset export; **Zarr is input-only, there is no writer** | PRD open question 2 (partially) |
| **F8** | **`l2_flags`** is the pixel-usability mechanism; the runtime mask constant is **47**, behaving as 15 for S2 | — |
| **F9** | **ACOLITE has no scene-level cloud concept.** That gate stays in discovery, permanently | PRD §7 "usability mask" |
| **F10** | **ACOLITE exits 0 on failure.** Success must be asserted from output files plus the run log | — |
| **F11** | **S2-calibrated products are** `tur_nechad2016`, `spm_nechad2016`, `chl_oc2`/`chl_oc3`, `chl_re_bramich`, and the `740` red-edge variants. **`tur_dogliotti2015` is MODIS-calibrated** by upstream's own warning | PRD §7 |
| **F12** | **ACOLITE provides floating-algae indices, not sargassum detection.** No masking of the indices, no biomass, no unmixing, no aggregation, no tracking | PRD §7 |
| **F13** | **ACOLITE's `fai` uses ρs, not Hu (2009)'s ρrc** — published thresholds are not directly portable | — |
| **F14** | **Latest stable is `20260421.0`**; scheme `YYYYMMDD.N`; no semver; `main` is 88 commits ahead | `CURRENT_STATE.md` open question on pinning |
| **F15** | **A clone install cannot report a meaningful version** — `acolite_version` records the clone date | — |
| **F16** | **Licence is GPLv3.** Internal, non-distributed use carries no source obligation. Separate-process invocation is lower coupling than library import | PRD §12 |
| **F17** | **EarthData credentials with OB.DAAC and LP DAAC approval are required**, and their absence degrades output **silently** | — |
| **F18** | **Docker is officially supported**, documented in the manual, distributed outside the repository | — |

---

## 13. Questions that remain product or architecture decisions

**Not research questions. These need the engineering interview, and this document deliberately does not answer them.**

### 13.1 Acquisition

1. **Which catalogue and client for L1C SAFE discovery?** CDSE OData is the reference. Whether to keep discovery in OCEANOS (retargeted) or delegate to `ac.api.get_scene` — which couples the pipeline to ACOLITE's Python API *and* its credential handling, and whose CDSE branch has no S2C prefix at this tag.
2. **What survives from the existing download layer?** The SHA-256 manifest, atomic publish and re-verification are genuinely valuable and have no ACOLITE equivalent. How much is worth porting to whole-product acquisition?
3. **Zip or extracted SAFE on disk?** Affects storage budget (both must coexist during extraction) and whether `delete_extracted_input` is used.

### 13.2 Spatial

4. **Per-tile with `limit`, or merged with `merge_tiles`,** for a multi-tile AOI? Merging requires same orbit and ≤600 s separation.
5. **Does the delivery grid stay ACOLITE's native UTM, or is an `output_projection` applied?** And if so, before or after the correction — upstream states the position changes the result.
6. **Does the existing `GridSpec`/normalization survive as a post-ACOLITE delivery-grid step, or is it retired?** Its exact-alignment guarantee is valuable for the PRD's cross-date comparability requirement; whether that justifies a second resample is a design call.
7. **What `limit_buffer`,** given the DSF needs dark-target context that a tight AOI removes?

### 13.3 Products and quality

8. **Which products enter the MVP baseline?** §6.7 proposes a starting set; the caveats (Dogliotti is MODIS-calibrated, `chl_oc*` is unreliable in sediment-laden coastal water, AFAI is undocumented) must be weighed per product.
9. **What `l2w_mask_threshold`?** The default `0.0215` masks turbid coastal water as land; the manual's own example uses `0.05`. **This is the highest-impact tuning decision in the whole configuration** for a Puerto Rico coastal AOI.
10. **Enable glint correction?** Both mechanisms are off by default.
11. **What does "usable product" mean in the PRD?** §7 gives the material: `l2_flags == 0` per pixel, a per-AOI valid fraction computed from the flags, and a separate scene-level cloud gate at discovery. The thresholds are a product decision.
12. **For sargassum: `fai` (ρs), `fai_rhot`, `afai`, `fait`, or `rhorc_*` + a downstream literature-native FAI?** F13 makes this consequential. And how much of Wang & Hu's unmixing pipeline is in MVP scope at all?

### 13.4 Operations

13. **Persist the L1R (large) or delete it** (`l1r_delete_netcdf`)?
14. **Pin a DockerHub digest, or build from pinned source?** Manual names only moving tags; immutable tags unverified (§14).
15. **Add `version=20260421.0` to `config/config.txt` in the deployment image?** Strongly indicated by F15, but it is a modification to the vendored tree.
16. **Storage and retention** given ~22 GB per full tile at 10 m, uncompressed by default.

---

## 14. Unknowns that could not be verified

Each names what was checked and what was left unchecked. **None of these blocks the interview; all should be closed before the corresponding design decision.**

| # | Unknown | Checked | Left unchecked | Impact |
|---|---|---|---|---|
| U1 | Whether the **binary release** sets `version=` in `config/config.txt` | source `config.txt` at the tag; release asset listing; `__init__.py` | the 180 MB release tarball (deliberately not downloaded) | **MEDIUM** — would give a cleaner fix for F15 |
| U2 | Whether `l2_flags` carries CF `flag_masks`/`flag_meanings` attributes | the `gemo.write` call (passes no `ds_att`); `nc_write.py` | `config/parameter_cf_attributes.json` | **MEDIUM** — affects how self-describing the flags are to downstream readers |
| U3 | **LUT download size**, and whether a fully offline run works once cached | `config.txt`; manual §2.7, §3.2, §8 | the `acolite_luts` repository; an actual cold run | **MEDIUM** — affects image build and air-gapped operation |
| U4 | Whether the generic `convert_l2` setting wires `sentinel2/l2_convert` into any automated flow | `acolite_run`, `acolite_l1r`, `acolite_l2r`, `acolite_l2w`, `identify_bundle` | `acolite/shared/` (101 files), `acolite/gee/`, the GUI | **LOW** — cannot reach L2W regardless |
| U5 | Whether `masking/land_water_mask.py` and `masking/ocm.py` are reachable from the S2 default flow | `acolite_flags.py`, `acolite_l2w.py` (grepped) | the two module bodies; `acolite_l2r.py` in full | **MEDIUM** — a real land mask would change decision 9 |
| U6 | Precedence when **both** `polygon` and `limit` are supplied | `acolite_run.py` call order | `shared/limit/polygon_check` body | **LOW** — avoidable by supplying only one |
| U7 | **DockerHub image currency, immutable tags, digests** | manual §3.8 | the DockerHub registry API; `acolite_tools` | **MEDIUM** — blocks decision 14 |
| U8 | Whether `get_scene`'s CDSE branch supports **S2C** on `main` | `api/get_scene.py` at the tag (no S2C prefix) | `main` HEAD of that file | **LOW** — only if delegating downloads |
| U9 | **Per-file licence headers** across all 527 modules (v3-only vs v3-or-later) | `LICENCE.txt`, `README.md`, 8 modules — **zero headers found** | ~519 modules, `acolite.spec` | **LOW** unless distribution is contemplated |
| U10 | `acolite_l2r.py` (2233 lines) was **grepped, not read end to end** | `defaults.txt`, the manual, the run flow | the module body | **MEDIUM** — adequate for the responsibility split; insufficient if a design depends on L2R internals (e.g. exactly which bands get `rhos_` under `min_tgas_rho=0.70`) |
| U11 | Literature attribution for `chl_oc2`/`chl_oc3` ← Pahlevan 2020, `tur_dogliotti2015` ← MODIS, `chl_re_bramich` ← Bramich 2021 | ACOLITE coefficient files and manual | the three papers themselves | **LOW** — the coefficient *values* are verified config facts; only attribution is single-pool |

---

## 15. Sources

All fetched or executed **2026-09-11**, against tag `20260421.0` / commit `f73cbe73887c2b114d9d3c70865effee73871525` unless noted.

### Primary — ACOLITE upstream (RBINS)

| Artefact | URL / command |
|---|---|
| Repository | `https://github.com/acolite/acolite` |
| Source at pinned commit | `https://raw.githubusercontent.com/acolite/acolite/f73cbe73887c2b114d9d3c70865effee73871525/<path>` |
| **Official manual, 67 pp.** | `https://github.com/acolite/acolite/releases/download/20260421.0/acolite_manual_20260421.0.pdf` |
| Releases / tags / compare | `api.github.com/repos/acolite/acolite/{releases,tags}`; `.../compare/20260421.0...main` |
| Full file tree (2675 blobs, `truncated:false`) | `api.github.com/repos/acolite/acolite/git/trees/main?recursive=1` |
| Local clone (read + executed) | `~/acolite`; env `~/micromamba/envs/acolite` (gdal 3.13.3, netCDF4 1.7.4, zarr 3.3.0) |

**Key modules read:** `sentinel2/{l1_convert,l2_convert,safe_test,metadata_scene,metadata_granule,projection,multi_tile_extent}.py`; `acolite/{acolite_run,acolite_l1r,acolite_l2w,acolite_flags,identify_bundle,inputfile_test}.py`; `output/{nc_write,nc_to_geotiff}.py`; `api/{get_scene,stac/query,cdse/query,cdse/download}.py`; `zarr/meta.py`; `__init__.py`; `launch_acolite.py`.

**Config and data read:** `config/{config.txt,defaults.txt,credentials.txt,parameter_labels.txt}`; `config/defaults/{S2A,S2B,S2C}_MSI.txt`; `data/Shared/algorithms/{Nechad/Nechad_calibration_201609.txt,Dogliotti/defaults.txt,Dogliotti/dogliotti_fait.txt,chl_oc/defaults.txt}`; `LICENCE.txt`; `README.md`; `environment.yml`.

### Independent corroborators (non-RBINS pools)

| Claim | Source |
|---|---|
| Release metadata, cadence, drift | GitHub REST API (Microsoft/GitHub) |
| Licence identity | GitHub licence-detection API — `spdx_id: GPL-3.0` |
| FAI definition and basis | Hu, C. (2009), *Remote Sensing of Environment* — [S0034425709001710](https://www.sciencedirect.com/science/article/abs/pii/S0034425709001710); [JAXA GCOM-C FAI ATBD](https://suzaku.eorc.jaxa.jp/GCOM_C/data/files/ATBD_FAI_en.pdf); USF DigitalCommons |
| **AFAI provenance and method** | Wang, M. & Hu, C. (2016), *"Mapping and quantifying Sargassum distribution and coverage in the Central West Atlantic using MODIS observations"*, **Remote Sensing of Environment** — [S0034425716301833](https://www.sciencedirect.com/science/article/abs/pii/S0034425716301833) |
| AFAI corroboration | [Frontiers in Marine Science (2023), *"Algorithms applied for monitoring pelagic Sargassum"*](https://www.frontiersin.org/journals/marine-science/articles/10.3389/fmars.2023.1216426/full); [CARICOOS operational AFAI, Eastern Caribbean](https://www.caricoos.org/oceans/observation/modis_aqua/ECARIBE/afai) |
| DSF as the recommended S2 AC | USGS ScienceBase / AWS Open Data, *"Sentinel-2 ACOLITE-DSF Aquatic Reflectance for CONUS"*; Vanhellemont (2019), *RSE* |
| Copernicus Data Space identity portal | `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/account/` |

### Method

Phases 0–4 at `high` effort, broad-topic doubled minimums, 7 tool types. **Coverage ledger: 59 rows, all marked** (gate exit 0). **Artifact gate: exit 0** (`sidecars=11 missing=0 freshness=newer pointer=matches status=usable`). **Independent verification:** fresh-context verifier, six source spot-checks re-derived, ACOLITE executed to confirm the exit-code finding; criterion 7 PASS, criterion 4 PASS for the behavioural body with four provenance FAILs, of which the load-bearing one (AFAI) was closed here. Full evidence, fetch log, conflicts and gaps: `.work/oceanos-pr-mvp/RESEARCH.md` and its 11 sidecars.

**Seven code-vs-manual conflicts were found and resolved in favour of the code:** AFAI undocumented; `netcdf_metadata_profile` default; `l2w_data_in_memory` default; `s2_dilate_iterations` naming; Docker's absence from the repo; S2C coverage in per-product sensor lists; and five parameters present in code but not the manual.

---

## 16. Recommended inputs for the engineering interview

Bring these into the interview as **settled constraints**, not as topics to re-open:

1. **The acquisition contract in §3.5.** It is the hardest constraint in the project and everything else depends on it. Complete L1C SAFE, one granule, all 13 bands, metadata intact, no upstream modification of any kind.
2. **The responsibility matrix in §11.** Its "REMOVE / RECONSIDER" column names the parts of Fase 5 that must not survive contact with ACOLITE in their current position — and, equally important, the parts of Fases 2–4 that are genuinely worth keeping.
3. **§5.4's table of invalidating operations.** Every row describes something the current pipeline does today. It is the clearest available statement of why this is a replacement rather than a refactor.
4. **C3 / F10: ACOLITE exits 0 on failure.** This changes the shape of the orchestration layer before it is designed, not after. Failure detection is a first-class component, not error handling.
5. **F9: the two-gate quality model.** Scene-level cloud at discovery (OCEANOS, permanently), pixel-level `l2_flags` from ACOLITE. They belong in different components and must not be conflated in the PRD's "usable product" definition.
6. **F15 / §10.2: the version-provenance defect**, with its mitigation, because PRD metric M4 depends on it.
7. **Decision 9 (`l2w_mask_threshold`) flagged as the highest-impact single tuning value** for a turbid coastal AOI — the default will mask the water you are trying to measure.
8. **F12 / §6.7: the sargassum scope boundary.** ACOLITE stops at the index. Everything the PRD's sargassum workflow implies — masking the indices, thresholding, aggregation into events, comparison across dates — is OCEANOS's to build, and Wang & Hu's own published method confirms the size of that gap.
9. **The eleven unknowns in §14**, each with its impact rating, so the interview can decide which to close first rather than discovering them mid-design.
10. **The operational prerequisites in §9.5** — EarthData approvals (administrative lead time), LUT pre-fetch, and the silent-degradation behaviour that makes asserting on credentials necessary rather than optional.

**Not for the interview to decide, because they are already facts:** §12's eighteen closed items.

**Explicitly left open for the interview:** all sixteen questions in §13. This document does not answer them, and the recommendations it contains (pin the tag, invoke as a separate process, let ACOLITE subset) are **recommendations grounded in evidence, not decisions**.
