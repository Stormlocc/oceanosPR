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
| Q6 | Work lives on a branch cut at `acc6072`; `master` untouched as the record of the rejected Fase 6/7 |
| Q7 | Land/sea split by **geometric GSHHG mask** (`ac.masking.land_water_mask`), decoupled from the SWIR threshold, which rises to `0.05` for cloud/bright-target duty only |
| Q8 | Coastal buffer is **layered**: exclude ~100–200 m from analysis (adjacency), retain the coastline in visualisation |
| Q9 | `dsf_aot_estimate=fixed` — the AOI is too small to give the tiled DSF enough valid tiles |
| Q10 | Discard the SAFE after successful processing; `l1r_delete_netcdf=True`; keep L2R + L2W + manifests indefinitely |
| Q11 | `merge_tiles=True` with `limit`; no upstream mosaicking |
| Q12 | Revise the AOI boundary before backfill; fit inside 19QFV if scientifically defensible |
| Q13 | Sun-glint correction **off**; record the glint angle as metadata |
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
- GSHHG (and HydroLAKES, if lakes are wanted) must be downloaded once into ACOLITE's `external_dir` before first use.
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

## Plan

*Empty. `/planning:plan` fills this section once Q16 and Q17 are resolved.*
