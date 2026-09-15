# Contracts — pipeline, interfaces, data, lineage, failure, API, viewer

**Status:** rounds 1–2 resolved · 2026-09-14. Types are defined in
[`type-inventory.md`](type-inventory.md); modules in [`topology.md`](topology.md); decisions and
their rationale in [`design-threads.md`](design-threads.md). Signatures below are shapes, not code.

---

## 1. Acquisition contract — discovery → selection → download (T22a–f)

Every fact in this section was verified against the live CDSE service on 2026-09-14
(`design-threads.md` §H.0).

### 1.1 Stages A0–A2

| # | Stage | Consumes | Produces | Module |
|---|---|---|---|---|
| A0 | **discover** | AOI, date range | L1C `SceneMetadata` into the `sentinel-2-l1c` scene collection | `catalog.cdse` (`CdseODataProvider`) + `catalog.local` |
| A1 | **select** | scene catalog, `DeliveryGrid` | per overpass: `TileCoverage` (candidates, minimal cover, `covers_grid`), `discovery_cloud_cover` | `pipeline.plan` (pure selection core in `pipeline/plan.py`) |
| A2 | **acquire** | selected scenes | verified `AcquiredScene` per selected tile | `ingestion.fetch` (whole-SAFE granularity) |

### 1.2 Discovery (A0)

| Aspect | Contract |
|---|---|
| Endpoint | `GET https://catalogue.dataspace.copernicus.eu/odata/v1/Products`, anonymous |
| Filter | `Collection/Name eq 'SENTINEL-2'` ∧ `productType eq 'S2MSI1C'` (**fixed in the adapter**) ∧ `OData.CSC.Intersects(AOI)` ∧ `ContentDate/Start` in range; `$expand=Attributes`; ordered by `ContentDate/Start` |
| Paging | `@odata.nextLink` with the existing cycle guard; any failed page aborts the search (no partial results) |
| Mapping | `Name` minus `.SAFE` → `scene_id`; `Id` → `source_id`; `tileId` → `mgrs_tile`; `cloudCover` → `cloud_cover`; `relativeOrbitNumber`; `platformSerialIdentifier` → `S2A/B/C`; `processorVersion` → `processing_baseline`; `productGroupId` → `datatake_id` → `OverpassId`; `GeoFootprint` → geometry; `ContentLength` → asset `file_size`; `Checksum[MD5, BLAKE3]` → `checksums`; one asset `product` with the download href |
| Guard | `productType != S2MSI1C` in a response → `input.not_l1c`, and the whole search aborts |

### 1.3 Selection (A1)

1. Group scenes by `OverpassId`. Every member must agree on platform, datatake and relative orbit.
2. Grid polygon = `DeliveryGrid` bounds reprojected to EPSG:4326.
3. **Minimal cover:** the smallest subset of candidate footprints whose union contains the grid
   polygon. Ties are broken by lower `cloud_cover`, then lexicographic tile id. The AOI has at most
   four candidates per overpass, so exhaustive subset search is exact and cheap.
4. No subset covers → `input.incomplete_tile_set` (deferred: new tiles may still be published).
5. `discovery_cloud_cover = max(cloud_cover of selected)`. The scene-cloud gate applies only when
   `quality.scene_cloud_max` is configured, and it is **unset during the bounded backfill** (T22c).
6. Only **selected** scenes are acquired.

For the configured AOI, all 23 observed overpasses select `19QGV` alone.

### 1.4 Acquisition (A2)

| Aspect | Contract |
|---|---|
| Auth | Keycloak password grant, `client_id=cdse-public`, `identity.dataspace.copernicus.eu/auth/realms/CDSE`, credentials from `~/.netrc` machine `cdse`. Access token 1800 s; refreshed when < 300 s remain. **Never logged or persisted** |
| Transfer | `GET https://download.dataspace.copernicus.eu/odata/v1/Products(<source_id>)/$value`, streamed to `.part` in the destination dir; require `200`; `Content-Length == ContentLength`; reject `206`/`Content-Range`. The existing rules stay |
| Resume | none; ranges are advertised but not honoured. Retry restarts the transfer, within bounded retries |
| Integrity | MD5 of the stream == catalogue MD5 (else `input.md5_mismatch`); SHA-256 computed as OCEANOS identity; BLAKE3 recorded, not verified |
| SAFE check | zip member listing, **no extraction**: exactly one `GRANULE/*`; `MTD_MSIL1C.xml`, `GRANULE/*/MTD_TL.xml`, 13 `IMG_DATA/*.jp2`, `QI_DATA/MSK_DETFOO*` present (else `input.safe_members_missing`) |
| Offline | `Online == false` → `input.product_offline` (deferred retry); no LTA ordering in the MVP |
| Publish | `fsync` + `os.replace`; manifest + scene Item synced (existing `_sync` shape) |
| Retention | after P9 deletion: scene Item keeps `source_id`, SHA-256, MD5 and sets `oceanos:retained=false`, `oceanos:deleted_at` |

### 1.5 Hand-off to processing

The planner (P0) requires, per observation:

- an `InputSet` whose `coverage.covers_grid` is true;
- every selected scene `AcquiredScene`-verified;
- SHA-256 re-verified at P1.

The planner **never** triggers acquisition implicitly. That is house pattern §3.3 ("verify-then-use,
never fetch-on-demand-downstream"). The orchestrator may chain *discover → acquire → process*, but
each step is its own stage with its own ledger entry.

---

## 2. Pipeline stages

The unit of work is **one observation** (AOI × overpass), per thread T1. Every stage below it is
idempotent, keyed by `RunKey`, and writes only into staging until its commit point.

| # | Stage | Consumes | Produces | Commit point | Module |
|---|---|---|---|---|---|
| P0 | **plan** | scene catalog, `DeliveryGrid`, date range, `AcoliteProfile` | `RunSpec` per observation, or an `Observation` with status `excluded_scene_cloud` / `incomplete_coverage` | ledger row `planned` | `pipeline.plan` |
| P1 | **preflight** | `RunSpec`, `AcoliteInstallation` | pass, or a `batch`/`observation` failure | ledger row `preflighted` | `acolite.probe` |
| P2 | **execute** | `RunSpec`, the rendered settings file | ACOLITE workspace with log + NetCDF + settings files, and the exit code | workspace sealed | `acolite.runner` |
| P3 | **verify** | the workspace | `AcoliteRunOutputs`, or `FailureRecord` | ledger row `verified` | `acolite.verify` |
| P4 | **archive** | `AcoliteRunOutputs` | `data/archive/…/<attempt>/` + `run-manifest.json` | **atomic dir rename** | `pipeline.archive` → `storage` |
| P5 | **conform** | archived L2W + L2R, `ProductSet`, `DeliveryGrid` | Float32 / int32 GeoTIFF layers on the grid, each `assert_aligned`. Grid cells outside the ACOLITE output extent are **NaN** (float) / the **out-of-scene flag** (value taken from `FlagSpec`, bit 4 = 16 at the tag), and `grid_coverage_fraction` is recorded, matching the existing house rule that areas outside the scene become nodata. **`LandMask` sets water products to NaN on land (DA-1)**; `true_colour` and `l2_flags` are not land-masked | staging only | `processing.normalize` |
| P6 | **assess** | conformed layers, `FlagSpec`, `AnalysisMask`, `QualityPolicy`, `AerosolEvidence`, glint angle | `QualityReport` with a verdict: cloud/toa/swir flags dilated by `cloud_dilation_px`; `grid_coverage_fraction < min_grid_coverage` → `incomplete_coverage`; AOT, aerosol model and glint gates; range rules (DA-2) | staging only | `processing.quality` |
| P7 | **package** | conformed layers, `QualityReport`, `ProvenanceRecord`, `PublicationProfile` | staged release: COGs, `l2_flags` COG, true colour, `quality.json`, `provenance.json`, STAC item draft, series rows | staging only | `publishing.package`, `timeseries.extract` |
| P8 | **publish** | staged release | immutable release dir, updated derived STAC item, index rows, `Observation.status`; the previous release moves to non-served `data/superseded/` **last** (DA-5, B1) | **atomic dir rename → atomic item replace → index transaction → superseded move + `releases.jsonl` event; reconciliation at every mutating command and API start-up** | `publishing.publish` |
| P9 | **retain** | published attempt | SAFE deleted (if Q10 conditions hold), workspace removed, `data/superseded/` collected keeping 1 per observation | per file | `pipeline.retain` |

**Only a usable verdict leads to a researcher-visible release.** An unusable verdict still runs P7/P8,
but publishes a *restricted* release (T6): it carries the observation record, true colour and
`l2_flags` only. A failure at P1–P5 publishes nothing. It records `processing_failed` for the
observation, and the previous release, if any, stays current.

### State machine

```text
planned → preflighted → executed → verified → archived → conformed → assessed → packaged → published
   │           │            │          │          │           │           │          │
   └───────────┴────────────┴──────────┴──────────┴───────────┴───────────┴──────────┴──► failed
any non-terminal state + stale writer lock on restart ─────────────────────────────────► abandoned
```

**Invariants**

- **I1.** An attempt reaches `published` only if every earlier stage has a `StageResult` with status
  `ok`.
- **I2.** `archived` is irreversible. A later failure never deletes the archive, so reprocessing from
  NetCDF (P5 onward) needs no ACOLITE.
- **I3.** An observation has **at most one** current release. Replacing it is atomic, and the previous
  release is readable until the replacement commits.
- **I4.** A `RunKey` with a `published` attempt is skipped by P0, unless the operator forces a
  reprocess, which creates a new attempt under the same key.
- **I5.** `abandoned` attempts are never resumed in place; the next attempt starts from P1. The
  archive of an `abandoned` attempt exists only if P4 committed, and P5+ may resume from it.

### Reprocessing entry points

| Trigger | Re-enters at | New `RunKey`? | New `ReleaseId`? |
|---|---|---|---|
| Retry after a retryable failure | P1 | no | yes, if it succeeds |
| Provisional → final (ancillary tier upgrade, T7) | **A2 re-acquisition** by recorded `source_id`, SHA-256 must match (the SAFE was deleted at P9, per Q10 and the Brief criterion "checksum sufficient to re-fetch deterministically"), then P1 | **yes** (profile changed) | yes |
| ACOLITE pin, owned settings or grid changes | A2 re-acquisition → P1 | **yes** | yes |
| Product set, quality policy, land/analysis mask or publication profile change (DA-4) | **P5 from archive** (no ACOLITE, no SAFE) | no | yes |
| AOI boundary change (Q12) | P0 (new grid, new AOI id) | **yes** | yes; old AOI's releases stay under their own `AoiId` |

---

## 3. Interfaces (ports)

Ports are the seams where an implementation can be substituted. Each port lists a real
implementation and the substitute used in tests (T24).

| Port | Operation shape | Real | Test substitute |
|---|---|---|---|
| `SceneProvider` *(existing)* | `search(aoi, start, end, cloud_max) → SceneSearchResult` | `CdseODataProvider` (T22) | `httpx.MockTransport` (existing pattern) |
| `InstallationProbe` | `probe(pin, paths) → AcoliteInstallation` | reads `git rev-parse`, `config/config.txt`, LUT dir, `external_dir`, `~/.netrc`, `statvfs` | fixture installation tree |
| `SettingsRenderer` | `render(owned: OwnedSettings, inputs, output, runid) → text` | writes **only** owned + per-attempt keys | pure, no substitute needed |
| **`AcoliteRunner`** | `run(python, launcher, settings_path, workspace, timeout) → ProcessOutcome{exit_code, duration, log_path, timed_out}` | subprocess `python launch_acolite.py --cli --settings=…` | **`FakeAcoliteRunner`**: copies fixture NetCDF + log (success, skip, ancillary fallback, missing variable) into the workspace |
| `RunVerifier` | `verify(workspace, spec) → AcoliteRunOutputs \| FailureRecord` | log scan + NetCDF attribute/variable read | exercised against fake-runner fixtures |
| `ArchiveStore` | `commit(attempt, outputs) → ArchivedRun` · `open(attempt) → ArchivedRun` | `storage` atomic directory | tmp dir |
| `GridConformer` | `conform(archived, product_set, grid) → ConformedLayers` | rasterio over `NETCDF:"…":var` (driver present, V5) | synthetic NetCDF fixtures |
| `QualityAssessor` | `assess(layers, flag_spec, analysis_mask, policy) → QualityReport` | **pure array core** + thin raster read | arrays |
| `Packager` | `package(layers, report, provenance, pub_profile) → StagedRelease` | GDAL COG driver with explicit `OVERVIEW_RESAMPLING` | tmp dir; asserts on overview method |
| `SeriesExtractor` | `extract(layers, report, zones) → list[SeriesPoint]` | **pure aggregation core** over precomputed pixel indices | arrays |
| `Publisher` | `publish(staged, index) → Release` | release dir rename + STAC item replace + index transaction | tmp tree + in-memory SQLite |
| `IndexWriter` | `record_attempt`, `record_observation`, `replace_series(observation, release, rows)`, `rebuild_from(ledger_root)` | SQLite, WAL mode | in-memory SQLite |
| `IndexReader` | `observations(aoi, range)`, `zone_series(zone, product, range)`, `operator_status(aoi, range)`, `release(release_id)` | SQLite, read-only connection | fixture DB |
| `AdhocSeriesReader` | `series(geometry, product, range) → Series` | windowed **full-resolution** reads of current-release COGs | fixture COGs |
| `WriterLock` | `acquire(path) → context` · `inspect(path) → holder \| stale \| free` | `fcntl.flock` + holder pid/host/attempt file | tmp file |

**Dependency rule for ports.** `pipeline` depends on the ports. `acolite`, `publishing` and `index`
provide implementations. `api` depends only on `IndexReader`, `AdhocSeriesReader` and read-only
release access. The acceptance criterion "a skipped ACOLITE run is detected" is tested entirely
through `FakeAcoliteRunner` + `RunVerifier`, without ACOLITE installed.

---

## 4. Data contracts

### 4.1 Settings file handed to ACOLITE (P2)

**Minimal**, per Brief constraint and research §9.2. Only these keys are written:

| Key | Value | Source |
|---|---|---|
| `inputfile` | comma-separated SAFE `.zip` paths, sorted by tile | per attempt |
| `output` | workspace dir | per attempt |
| `runid` | `RunAttemptId` | per attempt |
| `limit` | `S,W,N,E` = delivery grid bounds → EPSG:4326, expanded outward by one pixel | grid |
| `merge_tiles` | `True` **only when `len(coverage.selected) > 1`**; omitted otherwise | T22b (amends Q11) |
| `extract_inputfile` | `True` | Brief assumption |
| `s2_target_res` | `10` | grid resolution |
| `l2w_parameters` | from `ProductSet`, **never empty** | Q4, C4 of research |
| `rhorc_*` inside `l2w_parameters` | sets `output_rhorc`; written to **L2R** (`acolite_run.py:40-43` at the tag) | Q14 |
| `delete_extracted_input` | `True` | Q10; the extracted SAFE never reaches the archive |
| `rgb_rhot`, `rgb_rhos` | `False` | not used (T4 builds true colour from L2R) |
| `l2w_mask_threshold` | `0.05`; bit 0 informational only | Q7 (role amended by V8) |
| `dsf_residual_glint_correction` | `True` (method `default`, 1500–2400 nm) | Q13 amended (V8) |
| `l2w_mask_water_parameters` | `False` (ACOLITE never blanks water products; OCEANOS masks) | V8 |
| ~~land-mask keys~~ | none: ACOLITE does not call `land_water_mask` at the tag; land is masked by OCEANOS `LandMask` at P5 | Q7 amended (DA-1) |
| `dsf_aot_estimate` | `fixed` | Q9 |
| `ancillary_type` | `GMAO_IT_MET` / `GMAO_MERRA2_MET` by age | Brief constraint |
| `l1r_delete_netcdf` | `True` | Q10 |
| `netcdf_compression` | `True` (proposed; T25) | storage |

~~Glint correction is left at its default of *off* (Q13) by not writing the key.~~ Glint correction is **on** (Q13 amended by V8).

### 4.2 `run-manifest.json` (P4, archive, authoritative)

`schema_version`, `attempt: RunAttempt`, `run_key`, `observation_id`, `input_set: InputSet`,
`acolite_profile: AcoliteProfile` (full, not only its id), `acolite_profile_id`, archived files as an **explicit allow-list** (`*_L2R.nc`, `*_L2W.nc`, log, `l1r_settings_user.txt`, `l2r_settings.txt`), `installation` (commit observed,
version line), `outputs: AcoliteRunOutputs` (every file as `ArtifactRef`), `flag_spec`,
`ancillary`, `glint_angle_deg`.

### 4.3 Release directory (P8, immutable)

```text
<release_id>/
  release.json          Release
  provenance.json       ProvenanceRecord (§5)
  quality.json          QualityReport
  <product_key>.tif     COG, continuous profile       one per published product
  l2_flags.tif          COG, bitfield profile (MODE overviews, PREDICTOR=2)
  true_colour.tif       COG, 3-band byte, display-only
  settings_resolved.txt copy of ACOLITE's acolite_run_<id>_l2r_settings.txt (Q18 metadata asset)
  series.json           SeriesPoint rows for every zone (so the index can be rebuilt)
```

### 4.4 Derived STAC (static, STAC 1.1.0; Q17, Q18)

Separate from the committed scene catalog at `catalog/`.

| Element | Content |
|---|---|
| Catalog | one per AOI; child Collection `oceanos-<aoi_id>` |
| Item `id` | `OverpassId`; the Collection supplies the AOI |
| Item `properties` | `datetime`, `processing:software` `{acolite: "20260421.0@f73cbe7…", oceanos: "<version>@<git sha>"}`, `processing:datetime`, `processing:level` `"L2W"`, `oceanos:status`, `oceanos:tier`, `oceanos:valid_fraction`, `oceanos:release_id`, `oceanos:run_key`, `oceanos:scientific_label` |
| Item `assets` | one per `PublishedAsset`: `bands[]` with `data_type`, `nodata: "nan"`, `unit`, `eo:center_wavelength`; roles `data`/`visual`/`metadata`; `l2_flags` carries `classification:bitfields` generated from `FlagSpec`; `settings_resolved` asset with role `metadata` |
| Item `links` | `derived_from` → each scene Item in `catalog/`; `processing-software` → ACOLITE release URL at the pinned tag; `alternate` → `release.json` |

The Item is rewritten atomically at P8 and always points at the **current** release's assets.

### 4.5 Index (SQLite; derived, rebuildable, T15)

| Table | Key | Columns (logical) |
|---|---|---|
| `observations` | `observation_id` | aoi_id, overpass_id, datetime, status, reason, current_release_id, tier |
| `attempts` | `attempt_id` | run_key, observation_id, state, started_at, ended_at, failure_code, failure_scope, retryable |
| `releases` | `release_id` | observation_id, attempt_id, downstream_profile_id, visibility, supersedes, created_at |
| `zones` | `zone_id` | aoi_id, name, geometry_geojson, grid_id, pixel_count |
| `series` | (`zone_id`, `observation_id`, `product_key`) | release_id, status, valid_pixels, valid_fraction, mean, median, p10, p90, std |
| `scenes_seen` | `scene_id` | overpass_id, cloud_cover, acquired, retained (deleted_at, sha256, source_id) |

The operator status view (PRD §8) is a query over `observations` ⟕ `attempts` ⟕ `scenes_seen`. It needs
no extra state.

### 4.6 API responses

JSON, `schema_version` at top, ISO-8601 UTC, units always inline with values, and every value-bearing
response carries `release_id` plus a provenance URL. Shapes are in §7.

---

## 5. Metadata lineage

Each hop records a reference to the hop before it, **by content hash**, so a chain can be verified
offline after the SAFE is gone.

```text
CDSE product (source_id, name)                  scene catalog Item · scenes_seen
  └─ AcquiredScene (sha256 of .zip)             retained after SAFE deletion
      └─ InputSet (input_set_id = H(scene ids + sha256s))
          └─ RunKey = H(observation, input_set, acolite_profile)
              ├─ AcoliteProfile                  ACOLITE tag+commit · owned settings · grid_id · ancillary tier
              │  (DownstreamProfile keys the Release: product set v · quality policy v · masks v · publication)
              ├─ (legacy line below kept for diff history; read AcoliteProfile / DownstreamProfile above)
              │                                  quality policy v · grid_id · ancillary tier
              └─ RunAttempt                      host · oceanos version+git sha · exit code · stages
                  └─ archive: L2R.nc, L2W.nc     sha256 · acolite_version attr · resolved settings sha256 · log sha256
                      └─ ConformedLayers         source = (L2W sha256, variable name) · grid_id · copy|fail · land_mask {version, sha256} if ProductSpec.land_masked
                          └─ QualityReport       flag_spec (from resolved settings) · policy v · valid fraction
                              └─ Release         publication profile · COG sha256s · overview method
                                  ├─ STAC Item   processing:* · derived_from · settings asset
                                  ├─ series rows release_id
                                  └─ API / viewer every displayed value → release_id → provenance.json
```

**`ProvenanceRecord`** (one file, self-contained): `observation_id`, `release_id`, `attempt_id`,
`run_key`; scenes `[scene_id, source_id, sha256, processing_baseline, platform]`; ACOLITE
`{release_tag, commit_sha, version_attribute, settings_user_sha256, settings_resolved_sha256}`;
OCEANOS `{version, git_sha, profile_id, publication_profile_id, product_set_version,
quality_policy_version}`; `ancillary {type, tier, uoz, uwv, pressure}`; `glint_angle_deg`; per
product `{product_key, acolite_variable, algorithm, reference, unit, s2_calibrated, caveat,
source_sha256}`; timestamps `{acquired, processed, archived, published}`; `scientific_label`.

**Lineage invariants**

- **L1.** Every published value resolves to exactly one `release_id`, and every `release_id` resolves
  to exactly one `ProvenanceRecord`. This is PRD M4 at 100% by construction.
- **L2.** The ACOLITE version is recorded **three times**, and all three must agree at P3 or the run
  fails: the pin in the profile, the observed commit in the installation, and the NetCDF
  `acolite_version` attribute (valid only once Q15's `version=` line exists).
- **L3.** Bit meanings are never taken from code constants. They come from that run's
  `settings_resolved`.
- **L4.** No hash input contains an absolute path.

---

## 6. Failure handling

### 6.1 Two outcomes that must never be conflated

| | Processing failure | Unusable observation |
|---|---|---|
| Meaning | the system could not produce a trustworthy result | the system worked; the sky or the water did not cooperate |
| Retry | depends on the code (below) | never; it is a legitimate result |
| Operator sees | code, scope, evidence, retryability | valid fraction, reason |
| Researcher sees | `processing_failed`: "no observation available" | `no_usable_observation`, with reason (cloud, coverage) |
| Previous release | stays current | replaced by the restricted release (T6) |

### 6.2 Failure codes

| Code | Stage | Detection | Scope | Retryable |
|---|---|---|---|---|
| `input.incomplete_tile_set` | A1/P0 | no subset of candidate footprints covers the grid polygon | observation | when new tiles are published |
| `input.product_offline` | A2 | catalogue `Online == false` | observation | deferred, next `update` |
| `input.md5_mismatch` | A2 | stream MD5 ≠ catalogue MD5 | observation | yes (once), then no |
| `input.safe_members_missing` | A2 | zip listing lacks a required member, or has ≠ 1 granule | observation | no |
| `input.auth_failed` | A2 | token request rejected | **batch** | after credential fix |
| `input.mixed_overpass` | P0 | member scenes disagree on `OverpassId` | observation | no |
| `input.not_l1c` | P0 | `processing_level != Level-1C` | observation | no (defence in depth; discovery should already reject it) |
| `input.checksum_mismatch` | P1 | SAFE sha256 re-verification | observation | after re-fetch |
| `env.acolite_commit_mismatch` | P1 | observed commit ≠ pin | **batch** | after environment fix |
| `env.acolite_version_line_missing` | P1 | `config/config.txt` lacks `version=` (Q15) | **batch** | after fix |
| `env.luts_missing` / `env.gshhg_missing` (OCEANOS `data/external/gshhg`) / `env.credentials_missing` | P1 | probe | **batch** | after fix |
| `env.disk_insufficient` | P1 | free < budget (zip × expansion factor + outputs) | **batch** | after cleanup |
| `acolite.timeout` | P2 | wall clock > limit; process group killed | observation | yes (once) |
| `acolite.nonzero_exit` | P2 | exit ≠ 0 (rare; still recorded) | observation | yes (once) |
| `acolite.skipped` | P3 | log matches a known skip message (research §9.4 list) | observation | no |
| `acolite.missing_output` | P3 | no `*_L2R.nc` or `*_L2W.nc` | observation | yes (once), then no |
| `acolite.missing_variable` | P3 | a `ProductSpec` variable is absent (e.g. band dropped by `min_tgas_rho`) | observation | no |
| `acolite.ancillary_fallback` | P3 | L2R `uoz`, `uwv`, `pressure` equal the defaults (V2) | observation | **yes, deferred** until data latency clears |
| `acolite.version_attr_mismatch` | P3 | NetCDF `acolite_version` ≠ pin | **batch** | after fix |
| `grid.misaligned` | P5 | ACOLITE output transform not phase-aligned to the grid (T13) | **batch** | after decision |
| `grid.no_intersection` | P5 | output bounds ∩ grid = ∅ | observation | no |
| `publish.io_error` | P7/P8 | `OSError` during staging or commit; rollback restores prior state | observation | yes |
| `internal.abandoned` | restart | stale writer lock with a non-terminal attempt; the recorded ACOLITE process group is killed if still alive | observation | yes |
| `internal.writer_locked` | any mutating command | `WriterLock` held by a live holder | **batch** (the command exits non-zero, touching nothing) | yes, after the holder finishes |
| `input.refetch_mismatch` | A2 (re-acquisition) | a re-fetched SAFE's SHA-256 ≠ the recorded SHA-256 | observation | no; the provider changed the product, and planning a new `InputSet` is the operator's call |
| `internal.unexpected` | any | uncaught exception, with traceback archived | observation | yes (once) |

Unusable reason codes (not failures): `quality.below_valid_fraction`, `quality.out_of_range`.

### 6.3 Mechanics

- **Batch vs observation scope.** A `batch` failure stops the orchestrator before the next
  observation. Running 200 observations into the same broken environment would produce 200 identical
  failures and no information.
- **Crash safety.** Every stage writes only to staging under its tier root and commits by
  `os.replace`. That is the existing `normalize_scene` shape, extracted into `storage`. On restart,
  `WriterLock.inspect` finds a stale holder; non-terminal attempts become `abandoned`; staging
  directories older than the lock are removed.
- **ACOLITE process control.** The process is started in its own process group, with a timeout,
  stdout/stderr teed to the attempt log, and `ulimit`-style memory accounting recorded (not
  enforced) for M7 sizing.
- **SAFE deletion (P9)** requires all of the following: the attempt is `archived`; `scenes_seen`
  holds the scene's `source_id` and `sha256`; and no *other* non-terminal attempt references the
  scene. Otherwise the SAFE stays and P9 records why.
- **Workspace retention.** Removed on `published`. On `failed`, kept for a configurable number of
  days (default 14) for inspection, then collected by P9.
- **Retry policy.** Automatic retry happens only for codes marked "yes (once)", within the same
  invocation. Deferred retries (`acolite.ancillary_fallback`, `input.incomplete_tile_set`) are picked
  up by the next `update` run.

---

## 7. API boundary

**Read-only.** No endpoint writes, schedules, or triggers processing (PRD OQ4 default; T10). The
pipeline is driven only by the operator CLI.

| Endpoint | Role | Returns |
|---|---|---|
| `GET /api/v1/aois` | researcher | AOIs with `aoi_id`, name, boundary status, grid |
| `GET /api/v1/products` | researcher | `ProductSet`: keys, units, display ranges, S2-calibrated flag, caveats |
| `GET /api/v1/aois/{aoi}/observations?start&end` | researcher | every `Observation` in range, **including** gaps, with status and reason |
| `GET /api/v1/observations/{observation}` | researcher | current release summary, asset hrefs, quality summary, tier |
| `GET /api/v1/releases/{release}/provenance` | researcher | `ProvenanceRecord` |
| `GET /api/v1/aois/{aoi}/zones` | researcher | predefined `AnalysisZone`s |
| `GET /api/v1/series?zone|geometry&product&start&end` | researcher | `Series`; the `computed_from` field says which path served it (T8) |
| `GET /api/v1/value?observation&product&lon&lat` | researcher | full-resolution value, unit, flag bits decoded, `release_id` |
| `GET /api/v1/operator/status?aoi&start&end` | **operator** | per date: scenes present, acquired, attempt state, outcome, failure code + evidence |
| `GET /api/v1/operator/attempts/{attempt}` | **operator** | `RunAttempt` + log excerpt around matched evidence |
| `GET /data/…` | researcher (everything under `data/products/` is researcher-visible) | COGs, `release.json`, STAC JSON; **HTTP Range required**; same-origin, no CORS (D-6) |

**Not in the API:** tile rendering (no tile server, Q17); per-pixel series tables; processing
triggers; writes of any kind; export beyond the release files (PRD §8).

**Enforcement.** Role checks happen in the API process.

- **Everything under `data/products/` is researcher-visible by construction.** Restricted releases
  (T6) carry only true colour + flags and are researcher-visible. `data/archive/`, `data/work/` and
  `data/state/` are never served over HTTP, so no path-level role check is needed for `/data`, and
  a reverse proxy may serve it directly.
- Operator information (failure evidence, logs) is reachable only through `/api/v1/operator/*`.
- Archive NetCDF is **not** exposed in the MVP (T3).

### 7.1 CLI `pipeline status --json` shape (operator)

```text
{ "schema_version": "1.0", "aoi_id": str, "start": date, "end": date,
  "observations": [ { "observation_id": str, "overpass_id": str, "datetime": iso,
                      "status": ObservationStatus, "reason": str|null, "tier": ProcessingTier|null,
                      "current_release_id": str|null,
                      "last_attempt": { "attempt_id": str, "state": RunState,
                                        "failure_code": FailureCode|null } | null } ] }
```

The same shape backs `GET /api/v1/operator/status`.

---

## 8. Visualization boundary

**The viewer is a presentation client. It holds no science and no state beyond the URL.**

| The viewer does | The viewer never does |
|---|---|
| Reads COGs directly (geotiff.js) for display, using overviews | Computes a statistic, a series, or a threshold |
| Maps values to colour with the `display_range` from `/products` | Chooses a display range per scene (it would break cross-date comparison) |
| Branches on NaN **before** the colour ramp | Renders NaN as a ramp colour |
| Draws flagged-pixel overlays from `l2_flags` using `classification:bitfields` | Hard-codes bit positions |
| Reads single values via `/value` (full resolution) | Reads a value from an overview |
| Lists every date from `/observations`, including gaps, each with its status | Silently skips a date without a usable observation |
| Shows the provenance panel from `/releases/{id}/provenance` | Displays a value without a reachable `release_id` |
| Labels every product surface as uncalibrated / not validated (PRD §12) | Presents a product without its unit and label |
| Synchronizes pan/zoom for side-by-side dates; the grid is shared, so pixels coincide | Reprojects or resamples data for comparison |

**Four visual states that must be distinguishable** (PRD acceptance: "never visually equivalent"):

1. **Valid water value**: colour ramp.
2. **Flagged pixel**: `l2_flags ≠ 0`; hatched or a neutral overlay with a per-bit legend.
3. **No data in an observed scene**: NaN, e.g. land-masked or out of scene. Transparent over the
   basemap, with its own legend entry.
4. **No usable observation for the date**: the whole date is marked in the date navigator. There is
   no raster, or only the restricted true colour + flags (T6).

Operator-only: a fifth state, **processing failed**, shown in the status view and not in the
researcher map.
