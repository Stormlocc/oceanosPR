# OCEANOS Puerto Rico — Current State Assessment (frozen 2026-09-12)

> **FROZEN. This is not the current state of the repository.**
>
> This is the pre-MVP assessment of the Fase 1-5 baseline, written to feed the PLAN. That baseline
> was retired on 2026-09-16 and its code no longer exists. Every file listing, LOC count, test
> count and open question below describes 2026-09-12.
>
> For the current state: `IMPLEMENTATION_HANDOFF.md` (state + next action), `PLAN.md` (phases and
> acceptance criteria), `../../architecture.md` (architecture), `../../../README.md` (what runs).
>
> The eight open questions in §8 were all answered; their answers are the PLAN's Brief.

> **Baseline note (2026-09-12):** work now proceeds on branch `master`, created fresh at `acc6072` and renamed over the previous one. The Fase 6 (`423e485`) and Fase 7 (`74160a8`) commits are **abandoned and unreachable from any ref** — deliberately left to be garbage-collected. References below to `master` holding Fase 6/7 describe the state before that change.

**Scope:** complete local repository assessment prior to designing the remaining system.
**Method:** every `src/` and `tests/` file at the baseline was read in full. Test suite executed. No production code modified.

**Decisions recorded for this assessment:**

| # | Decision | Effect |
| --- | --- | --- |
| D1 | **Baseline is `acc6072` ("Fase5 complete")** — the working tree's detached `HEAD`. | Authoritative current state throughout this document. |
| D2 | **Commits `423e485` (Fase 6) and `74160a8` (Fase 7, branch `master`) are unverified and will not be used.** | Recorded in Appendix A only; nothing here depends on them. |
| D3 | **All downstream processing will be done with ACOLITE.** | Resolves the atmospheric-correction question. Its impact on the existing Fase 2–5 contracts is assessed in §2.8 and §4. |

D3 is the consequential one: ACOLITE is not a library that drops into the current stages, and the input contract it expects differs from what Fases 2–5 were built to produce. §2.8 states what that means, and separates what is verified in this repository from what still needs external confirmation.

All paths are relative to the repository root.

---

## 1. Summary

OCEANOS PR is a small, unusually disciplined Python 3.11 geospatial pipeline (~1,400 lines of `src/`, ~1,500 lines of tests) that runs **Sentinel-2 L2A discovery → local STAC catalog → verified band download → spatial normalization**, and stops there. Five sequential "Fase" commits, each self-contained, documented in a Spanish README section, and covered by tests.

Three findings dominate the current-state picture:

1. **The pipeline ends at spatial alignment.** Five bands (B02, B03, B04, B08, B11) are warped onto one common metric grid as Float32 GeoTIFFs with NaN nodata. **No pixel quality assessment, no cloud/water masking, no spectral index, no composite, no product, and no API exist.** `normalize.py` states this in its own docstring: "no radiometric calibration or indices."
2. **There is no atmospheric correction of any kind — no ACOLITE, no Sen2Cor invocation, nothing.** The pipeline consumes Sentinel-2 **L2A** (surface reflectance already produced upstream and served by Element84 Earth Search). Normalization deliberately *preserves* each band's `scale`/`offset`/`units` as metadata **without applying them**, so the normalized rasters still hold raw stored sample values, not reflectance. Under decision D3 this whole layer becomes ACOLITE's job — and ACOLITE's input expectations do not match what Fases 2–5 currently produce (§2.8).
3. **The codebase has an explicit, consistent architectural discipline** — provider-independent normalized models, an adapter boundary confining STAC vocabulary, atomic publish-or-rollback writes, and refusal to invent missing values. Any remaining design should extend this discipline rather than work around it.

---

## 2. Current state

### 2.1 Repository structure

```text
src/oceanos/
  __init__.py          version only
  __main__.py          argparse CLI, the sole orchestrator (195 lines)
  aoi.py               AOI load / validate / reproject / serialize
  config/
    models.py          pydantic-settings schema
    loader.py          YAML + env loading, path resolution
  catalog/
    models.py          SceneMetadata / SceneAsset / SceneSearchResult
    provider.py        SceneProvider ABC
    sentinel2.py       STAC Item Search adapter
    local.py           PySTAC local catalog persistence
  ingestion/
    fetch.py           verified streaming download + manifest
  processing/
    grid.py            GridSpec / build_grid
    normalize.py       windowed warp to the common grid
  api/                 EMPTY — docstring only
  composites/          EMPTY — docstring only
  publishing/          EMPTY — docstring only

configs/mvp.yaml, configs/aoi/la_parguera_mvp.geojson
catalog/               committed local STAC root (currently holds zero Items)
data/{raw,intermediate,products,catalog}/   gitignored working data
docs/architecture.md, docs/examples/scenes.json
scripts/               reserved, empty (README placeholder only)
tests/                 unit suite + tests/integration (opt-in), tests/fixtures
```

### 2.2 Git history and branch state

| Commit | Subject | Content |
| --- | --- | --- |
| `e1c3c67` | AOI complete v1 | config, AOI, CLI skeleton |
| `fbc2e4f` | fase2 | STAC discovery, `SceneMetadata`, provider ABC |
| `560536b` | Fase3 complete | local PySTAC catalog |
| `5a2c54e` | Fase4 complete | verified materialization |
| `acc6072` | **Fase5 complete** ← **baseline, detached `HEAD`** | grid + normalization |
| `423e485` | Fase6 complete | **excluded — see Appendix A** |
| `74160a8` | Gase7 complete ← `master` | **excluded — see Appendix A** |

Linear history, no merges, no remotes, single author (`mlocc-vivobook-WSL`), last commit `2026-09-07`. The branch is `master`, not `main`.

**The baseline commit is not on any branch.** `HEAD` is detached at `acc6072`; the only branch, `master`, points two commits ahead at excluded work. Any new commit made in this state belongs to no ref and is a garbage-collection candidate. Creating a branch at the baseline before further work is a one-command prerequisite — see Open Question 1.

### 2.3 Implemented pipeline stages

| Stage | Module | CLI | Status |
| --- | --- | --- | --- |
| AOI definition | `aoi.py` | `aoi info` | Complete |
| Scene discovery | `catalog/sentinel2.py` | `scenes search` | Complete |
| Local catalog | `catalog/local.py` | `catalog add` / `catalog list` | Complete |
| Materialization | `ingestion/fetch.py` | `scenes fetch` | Complete |
| Spatial normalization | `processing/normalize.py`, `grid.py` | `process normalize` | Complete |
| Atmospheric correction (ACOLITE, D3) | — | — | **Not started** |
| Pixel QA / cloud & water masking | — | — | **Not started** |
| Spectral indices | — | — | **Not started** |
| Composites / time series | `composites/` | — | **Not started** |
| Publishing | `publishing/` | — | **Not started** |
| API / orchestration | `api/` | — | **Not started** |

Stage coupling is strictly sequential and enforced at runtime: `fetch` requires a cataloged scene; `normalize` requires a verified download manifest and re-verifies every SHA-256 before opening a raster. No stage falls back to downloading or re-deriving a missing upstream artifact.

### 2.4 Satellite providers

**One provider only: Sentinel-2 L2A via Element84 Earth Search** (`https://earth-search.aws.element84.com/v1`, collection `sentinel-2-l2a`). No credentials are required, which is why the Earthdata variables in `.env.example` are dead (§2.13).

`SceneProvider` (`catalog/provider.py:14`) is a 1-method ABC (`search`) defining the discovery contract independently of STAC. `Sentinel2Provider` (`catalog/sentinel2.py:37`) is its only implementation, and is well-hardened:

- POST `/search` with the full AOI geometry as `intersects`; optional STAC Query `eo:cloud_cover <= max`.
- Full `next`-link pagination supporting GET and POST, `body`, `headers`, and `merge`; request-signature cycle detection (`sentinel2.py:101`).
- Bounded retries (`max_retries`, default 2) on transport errors and HTTP 408/429/500/502/503/504, exponential 0.5 s/1 s backoff, `Retry-After` honored up to 30 s.
- **No partial results**: any failed page or malformed item aborts the whole search.
- All STAC property names are confined to `_normalize()` (`sentinel2.py:174`). Nothing downstream reads `eo:cloud_cover` or `file:size` directly.

**Provider selection is hardcoded in the CLI.** `__main__.py:104` constructs `Sentinel2Provider` unconditionally; there is no registry, no config-driven provider key, and no second provider. Adding Landsat, PACE, MODIS, or a NASA CMR/Earthdata source means introducing that selection mechanism — the ABC exists, the wiring does not.

### 2.5 AOI handling

`aoi.py` is a 152-line frozen-dataclass module, and the most conservative code in the repository:

- Accepts RFC 7946 geometry, `Feature`, or single-`Feature` `FeatureCollection`; Polygon/MultiPolygon only.
- **Rejects** legacy GeoJSON `crs` members outright (`aoi.py:110`) to avoid ambiguous coordinate interpretation — input is always EPSG:4326 lon/lat.
- Validates ring closure (≥4 positions, first == last) *before* handing to Shapely, since Shapely silently closes open rings (`aoi.py:120`).
- Validates: nonblank name, 2-D geographic/projected CRS, non-empty geometry, finite 2-D coordinates, `is_valid` topology (reported via `explain_validity`), and WGS84 lon/lat range. **Never auto-repairs** invalid topology.
- `reproject_aoi` uses `always_xy=True` and `errcheck=True`, and re-validates the result.
- `to_geojson()`/`save()` always serialize back to EPSG:4326 regardless of the working CRS.

The configured AOI (`configs/aoi/la_parguera_mvp.geojson`) is a **0.15° × 0.10° axis-aligned rectangle** around La Parguera, self-labeled `"boundary_status": "illustrative_unverified"` with an explicit "not an official or scientifically validated boundary" note. Working CRS is EPSG:32619 (UTM 19N, metres).

`validate_aoi` is also reused as a geometry validator for scene footprints (`sentinel2.py:201`) — a small type-level smell (an "AOI" object is constructed just to validate a scene footprint), harmless today.

### 2.6 Scene metadata model

`SceneMetadata` (`catalog/models.py:41`) is the provider-independent contract. All models set `extra="forbid"` and `allow_inf_nan=False`.

| Field | Type | Notes |
| --- | --- | --- |
| `scene_id` | `str` min 1 | |
| `collection` | `str` min 1 | |
| `platform` | `str \| None` | unknown stays `None`, never invented |
| `datetime` | `AwareDatetime` | coerced to UTC by validator |
| `geometry` | discriminated `Polygon \| MultiPolygon` | always WGS84 |
| `bbox` | 4-tuple | always WGS84 |
| `cloud_cover` | `float \| None` 0–100 | whole-scene, **not** AOI-specific |
| `assets` | `dict[str, SceneAsset]` | keys preserve catalog keys |
| `source_catalog` | `str` min 1 | provenance |

`SceneAsset`: `href`, `media_type`, `title`, `roles`, `file_size`. **It carries no radiometric fields** — no `scale`, `offset`, or `unit`, and `Sentinel2Provider._normalize` does not read STAC `raster:bands`. Radiometry is therefore not captured anywhere at this baseline, which is why §2.3 lists sample→reflectance conversion as unstarted.

`SceneSearchResult` is the versioned wire format (`schema_version: "1.0"`); `{"schema_version":"1.0","scenes":[]}` is a valid zero-result document.

### 2.7 Download flow

`ingestion/fetch.py` materializes **only** a fixed band set:

```python
MVP_BANDS   = ("B02", "B03", "B04", "B08", "B11")
BAND_ASSETS = {"B02":"blue","B03":"green","B04":"red","B08":"nir","B11":"swir16"}
```

`fetch_scene` rejects any band outside `MVP_BANDS`. **SCL — the L2A scene-classification layer — cannot be downloaded at this baseline**, and neither can B8A, B12, previews, or QA files. Any masking design must extend this allowlist.

Layout: `data/raw/sentinel2/{scene_id}/{BAND}.tif|.tiff|.jp2|.bin` + `manifest.json`.

Integrity controls, all enforced:

- Asset-key resolution prefers the exact band name, falls back to the alias; **ambiguous matches raise** rather than pick one. `nir08` (B8A) explicitly does not substitute for B08 (`fetch.py:61`).
- **Preflight**: scene existence, every requested asset, and HTTP(S) scheme are checked before any transfer begins (`fetch.py:229`).
- `scene_id` must match `[A-Za-z0-9][A-Za-z0-9_.-]{0,199}` — path-escape defense, not ID rewriting.
- Symlink refusal on the scene directory and the manifest.
- Streaming to a `.part` temp in the destination directory; requires HTTP 200 (rejects 206 and `Content-Range`), rejects non-`identity` `Content-Encoding`, cross-checks `Content-Length` against catalog `file:size`, aborts mid-stream on overrun, rejects empty files, `fsync` + `os.replace` to publish atomically.
- Reuse requires a **full** manifest record match: asset key, source URL, local filename, size, and SHA-256. A file of the right size without a verified record is re-downloaded.
- **Every** recorded band is re-verified on each invocation, even bands not requested this time, so local corruption cannot leave the catalog marked `complete` (`fetch.py:247`).
- Manifest and catalog are synced after each band (`_sync`, `fetch.py:157`), so a lost catalog update is repairable from the manifest without re-downloading.

Status ladder: `pending` → `partial` → `complete` / `failed`, mirrored into the STAC Item as `oceanos:materialization_status` and `oceanos:processing_status`.

### 2.8 Atmospheric correction — absent today, ACOLITE by decision (D3)

#### What is verified in this repository

An exhaustive case-insensitive search for `acolite`, `atmospheric`, `dark spectrum`, `rhos`, `Rrs`, `L2R`, `py6s`, and `sen2cor` across the entire working tree **and** across all history returns no source, config, dependency, doc, or test hit. There is nothing to build on: this is a greenfield integration.

What exists in its place:

- The pipeline ingests **L2A**, i.e. surface reflectance already atmospherically corrected upstream by Sen2Cor before Element84 publishes it. That correction is inherited, not performed here, and is not configurable, inspectable, or re-runnable from this codebase.
- `normalize_band` copies `scales`, `offsets`, and band units from source to output **without applying them** (`normalize.py:120`). Normalized rasters contain raw stored sample values in Float32 containers, not reflectance.
- No module converts samples to physical units, and `SceneAsset` has nowhere to record the conversion (§2.6).

#### What D3 collides with — and this is the main finding of this revision

Fases 2–5 were built to a specific input contract: **discover `sentinel-2-l2a` on a STAC API, download five individual COG band files, and warp them onto a project-defined grid.** Every one of those three choices is a point of friction with an ACOLITE-based design. The following are stated as *design questions to resolve*, not as settled facts — see the verification note below.

1. **Product level.** ACOLITE performs the atmospheric correction itself, which implies it wants **top-of-atmosphere (L1C)** input, not the already-corrected L2A this pipeline discovers. If so, `SceneSearchSettings.collection` changes from `sentinel-2-l2a` to an L1C collection, and **Element84 Earth Search may not serve L1C in the same form** — which would make this a *provider* change, not a config change. That reaches `Sentinel2Provider`, the catalog, and the integration test.
2. **Asset granularity.** ACOLITE for Sentinel-2 conventionally consumes a **complete SAFE bundle** — all bands plus product and granule metadata (viewing/solar geometry, per-band offsets) — not five loose COGs. If so, `MVP_BANDS`, `BAND_ASSETS`, `_resolve_asset`, `_filename`, and the CLI `--bands` allowlist in `ingestion/fetch.py` are all built around the wrong unit of download. The integrity machinery around them (SHA-256 manifest, atomic publish, re-verification) is sound and reusable; the *band-level granularity* is not.
3. **Overlap with Fase 5.** ACOLITE does its own scene subsetting (an AOI limit), its own reprojection and output gridding, and writes its own outputs (commonly NetCDF, optionally GeoTIFF). That **overlaps directly with `build_grid` + `normalize_scene`**, which exist to impose one exact project grid. Two coherent options, and they lead to different systems:
   - **(a) ACOLITE before normalization** — hand ACOLITE the AOI, let it produce corrected output in its own grid, then run the existing `normalize_scene` over ACOLITE's outputs to force the exact project `GridSpec`. Preserves the repository's grid discipline and `assert_aligned` guarantee. Requires `normalize` to accept ACOLITE's output format and band naming.
   - **(b) ACOLITE as the grid authority** — accept ACOLITE's output grid and retire or bypass `build_grid`/`normalize_scene`. Less code, but discards Fase 5 and the exact-alignment contract that the rest of the design leans on (§3.7).
4. **Integration shape.** ACOLITE is distributed as a standalone program with a settings file, not as a `pip install` library in the way the current dependencies are. A subprocess/settings-file boundary is a different kind of dependency than anything in `pyproject.toml` today: it needs a pinned version, a reproducible invocation, settings generation, exit-code and log handling, and output discovery. None of that has a precedent in this codebase, and it sits awkwardly against the current "no directories created, no side effects on load" discipline.
5. **Licensing.** ACOLITE's license (GPL-family, to be confirmed) is more restrictive than anything currently in the dependency set, and the repo's own STAC Collection declares `license: other`. Worth settling before it is embedded.

#### Verification note

Points 1–5 come from general knowledge of ACOLITE, **not** from anything in this repository and **not** from a source checked during this session. They are the right questions; their answers should be confirmed against ACOLITE's current documentation before any of them drives a design decision. `/discovery:research` is the appropriate next step, scoped to: supported Sentinel-2 input levels and bundle formats, AOI/subsetting and output-grid control, output products and formats, invocation/automation interface, and license.

**Net effect on the assessment:** Fases 1–3 (config, AOI, discovery contract, local catalog) survive D3 largely intact. **Fase 4's band-level download model and Fase 5's position in the pipeline are the parts most likely to need rework**, and how much depends entirely on the answers to points 1–3.

### 2.9 Normalization and processing

**`processing/grid.py`** — one explicit metric grid per scene.

- `metric_crs()` rejects any CRS that is not projected with metre units (`unit_conversion_factor == 1`).
- `build_grid()` opens the reference band (default B02, restricted to native-10 m B02/B03/B04/B08), reprojects the buffered AOI into the target CRS, requires intersection with the scene footprint, and snaps the AOI bounds **outward** to the reference pixel origin. If the reference CRS already matches and is north-up, its origin is preserved exactly; otherwise GDAL's `calculate_default_transform` supplies one shared anchor.
- Roundoff at existing grid lines is suppressed below 1e-9 px.
- `GridSpec.__post_init__` re-validates everything: square north-up pixels at exactly the configured resolution, finite transform, positive integer dimensions, and `bounds == array_bounds(height, width, transform)` **exactly**.

**`processing/normalize.py`** — windowed spatial alignment, no science.

- `WarpedVRT` + 256×256 block loop, one band at a time; `warp_mem_limit` and `GDAL_CACHEMAX` both bounded by `warp_memory_limit_mb` (default 64).
- Output: tiled Float32 GeoTIFF, DEFLATE + predictor 3, `BIGTIFF=IF_SAFER`, nodata = NaN.
- Source nodata/masks and pixel centers outside the buffered AOI become NaN; valid zeros survive.
- Scale, offset, and units are copied to the output **without being applied** (§2.8).
- Categorical inputs are forced to `nearest`; an explicit `bilinear` request for categorical data is an error. **No categorical input exists yet** — `normalize_scene` only ever processes the five continuous bands, so `categorical=True` is a public API path with no in-repo caller.
- Accepted input dtypes: `uint8`, `int8`, `uint16`, `int16`, `float32`.
- Raster tags record `native_resolution`, `native_crs`, `native_resolution_units`, `processing_resolution`, `resampling_method`, `data_kind`, `source_path`, `source_nodata`. B11 correctly records its native 20 m while living on the 10 m processing grid.
- **Publish-or-rollback**: all five bands are written into a staging directory, each re-opened and checked byte-exact against the `GridSpec` (`assert_aligned`), then swapped in via `os.replace` with a backup directory restored on failure. A failed run leaves the previous output set intact.

The CLI reports grid dimensions, bounds, transform, on-disk and uncompressed sizes, peak process RSS, and the warp/GDAL memory limits.

### 2.10 Storage

| Tier | Location | Committed? | Content |
| --- | --- | --- | --- |
| Catalog (metadata) | `catalog/` | **Yes** | STAC root + collections + items |
| Raw | `data/raw/sentinel2/{scene_id}/` | No | source-format bands + `manifest.json` |
| Intermediate | `data/intermediate/{scene_id}/normalized/` | No | Float32 GeoTIFFs + manifest |
| Products | `data/products/` | No | **empty; nothing writes here** |

Path resolution (`config/models.py:141`): component dirs resolve relative to `data_root`, which resolves relative to the project base. `catalog_dir: "../catalog"` deliberately escapes `data_root` to place the STAC root at the repo root.

Observed state of the working data directory:

- `data/raw/sentinel2/S2B_19QFA_20260804_0_L2A/` — **complete** (5 bands, ~796 MB, SHA-256 verified, downloaded 2026-09-10).
- `data/raw/sentinel2/S2B_19QFV_20260804_0_L2A/` — **partial** (B02/B03/B04 only).
- `data/intermediate/S2B_19QFA_20260804_0_L2A/normalized/` — 5 bands + manifest; grid 1602×1125 @ 10 m, EPSG:32619, 0.87 MiB compressed vs 34.4 MiB uncompressed, peak RSS 126 MiB.

**Consistency defect:** `catalog/` currently contains the root catalog and an *empty* `sentinel-2-l2a` collection (`oceanos:extent_status: "empty"`, zero Items), while `data/raw` and `data/intermediate` hold real products for two scenes. The Items that recorded those downloads were removed from the working tree. Because `fetch` and `normalize` both require `catalog.get_scene(scene_id)` to succeed, **no stage can currently be re-run against the existing local data** until `scenes search` + `catalog add` repopulate the catalog. The downloaded rasters are orphaned from their provenance. See Open Question 2.

### 2.11 Data models

- **Config** — `OceanosSettings`, `AOISettings`, `SceneSearchSettings`, `NormalizationSettings`.
- **Metadata** — `SceneAsset`, `SceneMetadata`, `SceneSearchResult`, plus the discriminated `PolygonGeometry | MultiPolygonGeometry` union.
- **Ingestion** — `MaterializedAsset`, `FailedAsset`, `SceneManifest`.
- **Geometry** — `AOI` (frozen dataclass), `GridSpec` (frozen dataclass with a validating `__post_init__`).

Every Pydantic model forbids extra fields and rejects inf/NaN. Both JSON artifacts that cross a stage boundary (`SceneSearchResult`, `SceneManifest`) carry `schema_version: "1.0"`, as does `normalized/manifest.json`.

### 2.12 Tests

`uv run pytest -q` at the baseline: **137 passed in 2.43 s** (verified in this session).

| File | Coverage |
| --- | --- |
| `tests/test_aoi.py` | valid/invalid geometry, MultiPolygon, reprojection round-trip, non-finite coords, single-Feature collection, malformed JSON, invalid CRS |
| `tests/test_config.py` | YAML load, path resolution from both roots, `OCEANOS_*` env overrides incl. `__`-nested, invalid AOI/scene/normalization fields |
| `tests/test_scenes.py` | request contract, normalization, GET+POST pagination, `merge`, dedup, cycle detection, retry/`Retry-After`, per-status attempt counts, no-partial-success, malformed payloads, missing required fields |
| `tests/test_local_catalog.py` | creation, duplicate no-op, conflicting duplicate, persistence/reload, portable relative links, catalog relocation, path-escape via hostile IDs, corrupt catalog not replaced, **STAC schema validation via `jsonschema`** |
| `tests/test_fetch.py` | full download, idempotence, untrusted pre-existing files, corruption, interruption, missing asset preflight, size/`Content-Length`/206/empty-body checks, recovery of a lost catalog update, stale-band demotion, band allowlist |
| `tests/test_normalize.py` | grid dimensions/transform/bounds/buffer, exact reference alignment, scale/offset/nodata, bilinear vs nearest, cross-CRS reprojection, nodata not contaminating interpolation, internal masks + AOI holes, **all-bands-share-exact-grid**, rejection of partial materialization, previous set preserved on failure |
| `tests/test_cli.py`, `tests/test_package.py` | CLI wiring, exit codes, import |
| `tests/integration/test_sentinel2_live.py` | real Earth Search contract; opt-in via `--run-integration`, metadata only |

Test hygiene is strong: `no_network` autouse fixtures monkeypatch the socket layer in the catalog/fetch/normalize suites; HTTP is simulated with `httpx.MockTransport`; rasters are synthetic; integration tests are excluded from collection by a `pytest_ignore_collect` hook unless explicitly enabled.

**Gaps:** no coverage measurement, no property-based or fuzz testing, no concurrency tests (the single-writer assumption is documented but never exercised), no performance/large-scene test, and no end-to-end test spanning search → catalog → fetch → normalize (each stage is tested against fixtures of the previous stage's output *shape*, not against the real previous stage).

### 2.13 Configuration

Single file `configs/mvp.yaml`, four sections: top-level paths, `aoi`, `scenes`, `normalization`. Loading is side-effect-free: it creates no directories and makes no network calls.

Precedence is customized (`config/models.py:126`): **environment variables win over YAML**, then init args, then dotenv, then secrets. Prefix `OCEANOS_`, nested delimiter `__` (e.g. `OCEANOS_AOI__TARGET_CRS`, `OCEANOS_NORMALIZATION__TARGET_RESOLUTION`).

**Dead configuration:** `.env.example` declares `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD`. Nothing in the codebase reads them — there is no Earthdata client, and the `OCEANOS_` prefix means pydantic-settings ignores them anyway. A vestige of an intended NASA Earthdata path that was never built.

### 2.14 CLI entrypoints

`python -m oceanos` (`__main__.py`) is the **only** working entrypoint:

```text
aoi info
scenes search --start --end [--config --collection --cloud-cover-max --output]
scenes fetch SCENE_ID [--bands --config --catalog-dir --raw-dir --timeout]
catalog add SCENES_FILE [--config --catalog-dir]
catalog list [--config --catalog-dir]
process normalize SCENE_ID [--config --resolution --buffer --resampling --target-crs]
```

**Defect: the declared console script is broken.** `pyproject.toml:20` declares `oceanospr = "oceanospr:main"`, but no `oceanospr` module exists (the package is `oceanos`, and `main` lives in `oceanos.__main__`). Verified in this session:

```console
$ uv run oceanospr
ModuleNotFoundError: No module named 'oceanospr'
```

Fix: `oceanospr = "oceanos.__main__:main"`.

The CLI is also the **only** orchestration layer: `main()` is a ~110-line `if/elif` chain that hand-wires config → AOI → provider → catalog → stage for every command. There is no pipeline object, no dependency-injection seam, no batch/multi-scene driver, and no resumable run state. `scripts/` is reserved and empty.

Note `__main__.py:145` dispatches on `args.command == "process"` without checking `args.process_command`, which is correct only while `normalize` is the sole `process` subcommand. Adding a second one requires that check.

### 2.15 Dependencies

Runtime (`pyproject.toml`):

`affine>=2.4,<3` · `httpx>=0.28.1` · `numpy>=2.4.6` · `pandas>=3.0.5` · `pydantic>=2.13.5` · `pydantic-settings>=2.15.0` · `pyproj>=3.7.2` · `pystac>=1.15.2` · `pyyaml>=6.0.3` · `rasterio>=1.4.4` · `shapely>=2.1.2`

Dev group: `jsonschema>=4.26.0`, `pytest>=9.1.1`. Build backend `uv_build`; `uv.lock` committed; Python pinned to 3.11.

Resolved in the current environment: rasterio 1.4.4 (GDAL 3.10.3), pystac 1.15.2, pydantic 2.13.5, numpy 2.4.6, uv 0.12.9.

**`pandas` is declared but never imported anywhere in `src/` or `tests/`** — an unused dependency.

---

## 3. Existing patterns to reuse

These are consistently applied and should be treated as the house style for anything added next:

1. **Adapter boundary for external vocabulary.** All STAC-specific property names live in `Sentinel2Provider._normalize` and `catalog/local.py`. Downstream code touches only `SceneMetadata`. A second provider slots in here.
2. **Staging + atomic publish + rollback.** `normalize_scene` writes to `tempfile.mkdtemp(prefix=".normalized-", dir=parent)` → verifies the complete set → moves the old output to a backup dir → `os.replace(staging, output)` → restores the backup on `OSError` → `rmtree` in `finally`. Copy this shape verbatim for any new stage.
3. **Verify-then-use, never fetch-on-demand-downstream.** Each stage re-verifies its inputs (SHA-256, `assert_aligned`, manifest identity) and errors out rather than silently regenerating an upstream artifact.
4. **Never invent a missing value.** Unknown platform/cloud stays `None` and propagates as an explicit error or an omitted STAC property.
5. **Hash-based on-disk filenames with original IDs preserved inside the documents** (`_Layout`, `local.py:57`) — arbitrary scene IDs cannot escape the catalog directory.
6. **Versioned artifacts.** Every cross-stage JSON carries `schema_version: "1.0"`.
7. **Exact-equality alignment assertions.** `assert_aligned` compares CRS, transform, width, height, and bounds against the `GridSpec` on re-read, before anything is published. Every raster hand-off should go through it.
8. **Explicit resource bounds.** Block-windowed 256×256 processing, `warp_mem_limit`, `GDAL_CACHEMAX`. No stage loads a full scene into memory.
9. **Scientific honesty in metadata.** `boundary_status: illustrative_unverified`, `license: other` granting nothing new, native-vs-processing resolution recorded separately so a 20 m band on a 10 m grid cannot be mistaken for 10 m data.

---

## 4. Constraints on any further design

**Hard constraints**

- **Single writer per catalog and per scene.** Documented in five places; enforced nowhere. No lock file, no advisory locking, no transaction. Any parallel or multi-scene design must add this.
- **Metric projected CRS required** for all processing; `metric_crs()` rejects geographic CRSes.
- **Fixed band set.** `MVP_BANDS` is a hardcoded tuple referenced by `fetch` and `normalize`. Adding SCL, B8A, or B12 touches both, plus the CLI `--bands` choices. Under D3 this constraint is likely to be *removed* rather than extended (§2.8, point 2).
- **Float32 NaN-nodata downstream of normalization**, with exact grid identity enforced by `assert_aligned` at every hand-off.
- **Normalized values are raw samples, not reflectance** (§2.8). Under D3, reflectance is ACOLITE's output, not a conversion this codebase performs.
- **Collection is `sentinel-2-l2a` throughout** — config default, `LocalSceneCatalog` collection id, committed `catalog/collections/<sha256 of "sentinel-2-l2a">/`, and the integration test. A move to L1C under D3 changes the on-disk catalog layout (the directory name is a hash of the collection id), so the existing `catalog/` tree would gain a second collection rather than being rewritten.
- **ACOLITE is an out-of-process dependency** (D3, §2.8 point 4). Nothing in the current design — pure-Python, no subprocesses, no external binaries, fully offline tests — anticipates one. Test strategy in particular: the suite's `no_network` discipline has no equivalent for "don't actually run ACOLITE", so a fake/stub boundary has to be designed alongside the integration itself.
- **`extra="forbid"` on all models.** An unrecognized YAML key or JSON field is a hard error, not a warning. Config additions must update the model.
- **Python 3.11**, per `.python-version` and `requires-python`.

**Portability constraints**

- Absolute machine paths are written into artifacts: `output_directory` and `bands[*].source_path` in the normalization manifest, and `oceanos:local_path` / `oceanos:manifest_path` on STAC Items. The README acknowledges this and instructs re-running `fetch` after relocating data. Catalog *links* are relative and portable; these annotations are not.
- The committed `catalog/` tree is repository state that changes as a side effect of running the CLI — every `catalog add` / `fetch` dirties the working tree.

**Tooling constraints (all absent)**

- No CI: no `.github/workflows/`, no CI config of any kind.
- No linter, formatter, or type checker: no `.editorconfig`, `ruff`, `flake8`, `mypy`, or `pre-commit` config. Type hints are used consistently in `src/` but are never checked.
- No coverage tooling, no logging configuration (a single `logger.info` in `config/loader.py` with no handler setup anywhere).
- `pyproject.toml` still carries `description = "Add your description here"`.

---

## 5. Unfinished, dead, and placeholder code

| Item | Location | Assessment |
| --- | --- | --- |
| `api/`, `composites/`, `publishing/` | `src/oceanos/*/__init__.py` | Docstring-only packages ("not implemented in Phase 0"). Deliberate boundary markers, zero code. |
| `data/products/` | filesystem | Directory exists, is configured as `products_dir`, and **no code writes to it**. |
| `scripts/` | repo root | Reserved, README placeholder only. |
| `data/catalog/` | filesystem | Legacy empty directory; README states it is not auto-migrated. Superseded by `catalog/`. |
| Broken `oceanospr` console script | `pyproject.toml:20` | **Bug.** Verified `ModuleNotFoundError`. |
| Stale `src/nasa_oceanos_pr.egg-info/` | `src/` | Build artifact from a former project name (`nasa-oceanos-pr`), carrying a *better* description than current `pyproject.toml`. Not gitignored. Remove and ignore. |
| Unused `pandas` dependency | `pyproject.toml:12` | Declared, never imported. |
| Dead `EARTHDATA_*` credentials | `.env.example` | Never read by any code path. |
| `normalize_band(categorical=True)` | `processing/normalize.py:39` | Fully implemented and tested, but no in-repo caller — nothing categorical is downloadable yet. Ready-made entry point for a future mask stage. |
| `SceneProvider` with one implementation | `catalog/provider.py` | Abstraction exists; the multi-provider mechanism it anticipates does not. |
| Orphaned local data vs empty catalog | `catalog/` vs `data/` | See §2.10. Not code, but blocks re-running any stage today. |
| Detached `HEAD` | git | Baseline is on no branch; new commits would be unreferenced. See Open Question 1. |

---

## 6. Architectural boundaries

The dependency graph is clean and acyclic:

```text
config ──────────────────────────┐
aoi ────────────┬────────────────┤
                ▼                ▼
          catalog.models ──► catalog.provider ──► catalog.sentinel2
                │                                       │
                ▼                                       │
          catalog.local ◄───────────────────────────────┘
                │
                ▼
          ingestion.fetch
                │
                ▼
     processing.grid ──► processing.normalize
                                  │
                                  ▼
                              __main__  (sole orchestrator)
```

Boundaries that hold:

- `aoi` and `config` are leaves; neither imports another OCEANOS module (`aoi` imports only pyproj/shapely).
- No processing module imports a provider; no provider imports processing.
- STAC vocabulary is confined to `catalog/sentinel2.py` and `catalog/local.py`.
- Each stage depends only on the preceding stage's *artifacts*, not its code paths.

Boundaries that are **missing**:

- **No orchestration layer.** `api/` is empty and `__main__.py` performs all wiring inline. There is no place for multi-scene runs, scheduling, cross-stage retries, or run provenance.
- **No storage abstraction.** Every module builds `Path` objects directly from config. Moving to object storage (S3/GCS) would touch `fetch`, `normalize`, and `local`.
- **No product/publishing boundary.** Nothing writes to `products/`; there is no product contract, no COG/overview generation, no tiling, no STAC Item for derived outputs.
- **No temporal/composite boundary.** Everything is strictly per-scene; nothing aggregates across scenes or dates.
- **No pure computational core.** All raster math currently lives inside I/O-bound functions. A separate I/O-free module for future index math would be testable without fixtures.

---

## 7. Alignment with the documented direction

`docs/architecture.md` accurately and completely describes Fases 1–5 as they exist at this baseline, and ends with: *"Compuestos, publicación y API siguen sin implementar lógica de esas etapas; no se calculan FAI, NDVI ni otros índices científicos."* That statement is **true at the baseline**. The README covers Fases 1–5 in matching detail. Documentation and code are in sync.

The project's stated direction is consistent and worth preserving:

- Reproducibility over convenience (verified hashes, versioned artifacts, atomic publication).
- Explicit scientific honesty (unverified boundary labeled as such, `license: other` granting nothing new, refusal to invent absent values).
- Phase isolation — each commit adds exactly one stage plus its tests and documentation.

Remaining work implied by that direction and by the empty packages: **radiometry → QA/masking → indices → composites/time series → products → publishing → API**.

---

## 8. Open questions

Each has a recommended default and an escape hatch.

1. **Where should the Fase 5 line of work live?** The baseline is on no branch and `master` points at excluded commits. *Default:* create a branch at `acc6072` (e.g. `git switch -c fase5-baseline`) before any further commit, leaving `master` untouched as a historical record of the discarded work. *Escape hatch:* if the excluded commits should be dropped entirely, reset `master` to `acc6072` — destructive, so only on an explicit instruction.
2. **Re-link or discard the orphaned local data?** ~800 MB of SHA-verified downloads plus a normalized set exist with no catalog Items. *Default:* re-run `scenes search` + `catalog add` for the two scenes to restore provenance and make the data usable again. *Escape hatch:* if those scenes were exploratory, delete `data/raw` and `data/intermediate` and start from a clean catalog.
3. ~~Is atmospheric correction in scope?~~ **Resolved by D3: yes, ACOLITE performs all processing.** Superseded by 3a–3c below, which are the questions that decision now forces. None can be answered from this repository; all three need ACOLITE's documentation confirmed first (§2.8, verification note).
   - **3a. Which Sentinel-2 product level and bundle format will feed ACOLITE?** *Default:* assume L1C SAFE bundles, which makes this a discovery+download rework, not a config change — and requires confirming whether Earth Search can serve them or a different provider is needed. *Escape hatch:* if ACOLITE accepts the L2A COG bands already being downloaded, Fase 4 survives unchanged and the rework collapses to almost nothing. **This is the single highest-leverage unknown in the project; resolve it before planning anything downstream.**
   - **3b. Does ACOLITE or the existing `GridSpec` own the output grid?** *Default:* option (a) — ACOLITE first, then the existing `normalize_scene` forces the exact project grid, preserving the `assert_aligned` contract that §3 identifies as the house pattern. *Escape hatch:* option (b), accept ACOLITE's grid and retire Fase 5, if the double-resampling cost or the format mismatch makes (a) impractical.
   - **3c. How is ACOLITE invoked, pinned, and faked in tests?** *Default:* vendor a pinned version, drive it through a generated settings file in a subprocess behind one adapter module (mirroring how `Sentinel2Provider` confines STAC), and stub that adapter in the unit suite exactly as `httpx.MockTransport` stubs the network. *Escape hatch:* if ACOLITE exposes a stable importable Python API, use it directly and skip the subprocess boundary.
4. **Does the system need multi-scene / temporal processing, and at what scale?** *Default:* assume yes — which makes the missing orchestration layer and the unenforced single-writer constraint the first two design problems to solve. *Escape hatch:* if single-scene on-demand analysis is the target, the current CLI shape is adequate and the effort belongs in publishing instead.
5. **Where do derived products live, and what is a "product"?** *Default:* define `data/products/` as the publication tier with COGs, overviews, and derived STAC Items, leaving `intermediate/` for stage scratch. *Escape hatch:* if downstream consumption is via an API/tile server rather than files, the product contract becomes a service schema and `products_dir` stays unused.
6. **Should the repository keep committing `catalog/`?** *Default:* keep it (it is provenance, and it is small), accepting that CLI runs dirty the working tree. *Escape hatch:* move it under `data/` and gitignore it if catalog churn becomes noisy in review.
7. **Is `pandas` intended for future use?** *Default:* remove it; nothing imports it. *Escape hatch:* keep it if tabular time-series output is already planned.

---

## 9. Next-stage handoff

For planning the remaining system, the load-bearing facts are:

- **The baseline is `acc6072` (Fase 5).** The pipeline ends at spatially aligned Float32 rasters on a common metric grid. Everything after that — atmospheric correction, QA/masking, indices, composites, products, publishing, API — is greenfield.
- **ACOLITE (D3) is the next stage, and it is an integration, not a module.** Out-of-process dependency, its own settings/invocation contract, its own subsetting and gridding, its own output format. Nothing in the current design anticipates any of that (§2.8, §4).
- **Resolve Open Question 3a before planning anything else.** Whether ACOLITE needs L1C SAFE bundles or can take the L2A COG bands already being downloaded decides whether Fase 4 survives, whether Earth Search remains a viable provider, and how much of the discovery contract is rework. Every other downstream decision is contingent on it.
- **The parts that survive D3 regardless:** `config`, `aoi`, the `SceneProvider`/`SceneMetadata` contract, `LocalSceneCatalog`, and the integrity machinery inside `fetch.py` (SHA-256 manifests, atomic publish, re-verification). The parts most at risk: `MVP_BANDS`-level download granularity, and Fase 5's position in the pipeline.
- **The missing orchestration layer** (`api/`) and the **missing storage abstraction** are the two boundaries every further stage will press against — and an out-of-process ACOLITE step makes the orchestration gap bind sooner.
- Four cheap defects to fix early: the broken `oceanospr` entry point, the stale `nasa_oceanos_pr.egg-info/`, the unused `pandas` dependency, and the dead `EARTHDATA_*` example credentials.
- The **staging + atomic publish + rollback** pattern and **`assert_aligned`** are the established contracts for any new raster stage; reuse them rather than inventing variants.
- Absent tooling (CI, lint, type checking, coverage) is a gap to close before the codebase grows past its current ~1,400 source lines.

**External research (`/discovery:research`) is now a prerequisite, not an optional follow-up.** Scope it to ACOLITE: supported Sentinel-2 input levels and bundle formats; whether STAC/COG inputs are usable or a SAFE bundle is required; AOI subsetting and output-grid control; output products (rhos/Rrs, indices) and formats; invocation and automation interface; version pinning; and license. Secondary: where to obtain Sentinel-2 L1C if 3a resolves that way, and Sentinel-2 baseline-04 radiometric offset handling.

---

## Appendix A — Excluded commits (recorded, not used)

Two commits exist beyond the baseline and are **excluded by decision as unverified**. They are listed only so their existence on `master` is not mistaken for missing work, and so nothing in this repository is accidentally built on them.

| Commit | Subject | Adds |
| --- | --- | --- |
| `423e485` | Fase6 complete | `processing/quality.py`, `docs/quality_flags.md`, `tests/test_quality.py`; SCL support in `fetch`; CLI `process qa` |
| `74160a8` | Gase7 complete (`master`) | `processing/spectral.py`, `processing/metrics.py`, `docs/spectral_metrics.md`, `tests/test_metrics_raster.py`, `tests/test_spectral.py`; radiometry fields on `SceneAsset`; `metrics` config section; CLI `process metrics` |

Neither commit adds a runtime dependency. Nothing at the baseline references them. If any of that work is ever revisited, it should be re-reviewed from scratch rather than adopted on the strength of these commits existing.
