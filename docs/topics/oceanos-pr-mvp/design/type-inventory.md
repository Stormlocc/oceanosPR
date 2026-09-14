# Type inventory — OCEANOS PR

**Status:** rounds 1–3 resolved · 2026-09-14. Types are specified by shape, not code.
Thread references (`T#`) point to [`design-threads.md`](design-threads.md).

## 0. Conventions (inherited, not new)

- **Anything serialized** is a Pydantic model deriving from the existing `MetadataModel`
  (`extra="forbid"`, `allow_inf_nan=False`). **Geometry value objects** stay frozen dataclasses with a
  validating `__post_init__`, like `AOI` and `GridSpec`.
- **Every persisted document** carries `schema_version`. New documents start at `"1.0"`.
- **Unknown stays `None`**; it is never defaulted to a plausible value (`CURRENT_STATE.md` §3.4).
- **Identifiers are validated strings**, each with a regex, so an id can never escape a directory
  (house pattern §3.5). They are listed in §1 and never constructed ad hoc.
- **Datetimes are aware and UTC**, as `SceneMetadata` already does.

---

## 1. Identity

Identity is the load-bearing part of this design. Two rules shape it:

1. **"What" and "which attempt" are different identities.** A `RunKey` names a result that is fully
   determined by its inputs and profile. A `RunAttemptId` names one execution of it. Retrying never
   changes the `RunKey`.
2. **Processing and publication are versioned separately.** Regenerating COGs, or changing the true-colour
   stretch, creates a new `ReleaseId` without re-running ACOLITE.

| Identifier | Form | Derived from | Changes when | Example |
|---|---|---|---|---|
| `AoiId` | `aoi-<slug>-<h12>` | slug of AOI name + SHA-256 of canonical GeoJSON (EPSG:4326, sorted keys) | the boundary changes, e.g. when Q12 is resolved | `aoi-la-parguera-3f9a…` |
| `GridId` | `grid-<h12>` | `AoiId` + canonical `GridSpec.to_dict()` | AOI, CRS, resolution or anchor changes | `grid-81c0…` |
| `SceneId` | *existing*: provider product name without `.SAFE` | provider | never | `S2B_MSIL1C_20260804T150719_N0511_R082_T19QFV_20260804T184512` |
| `OverpassId` | `<platform>_<datatake start>_R<orbit>` | CDSE `productGroupId` minus the baseline suffix + `relativeOrbitNumber`; member scenes must all agree | never; AOI-independent | `S2B_20260804T150719_R082` (from `GS2B_20260804T150719_049157_N05.12`) |
| `ObservationId` | `<AoiId>/<OverpassId>` | — | — | the subject a researcher sees for one date |
| `InputSetId` | `inp-<h16>` | sorted `(SceneId, sha256)` of the member SAFE archives | a tile is added, or ESA reprocesses (new baseline `N05xx`) | — |
| `AcoliteProfileId` | `acp-<h16>` | canonical JSON of `AcoliteProfile` (§3): only what changes ACOLITE's output | ACOLITE pin, owned settings, grid or **ancillary tier** changes | — |
| `RunKey` | `run-<h16>` | `ObservationId` + `InputSetId` + `AcoliteProfileId` | any of the three | the idempotence key; **quality or product changes never change it** (DA-4) |
| `RunAttemptId` | `att-<YYYYMMDDTHHMMSSZ>-<runkey8>` | start time + `RunKey` | every execution | also passed to ACOLITE as `runid` (verify allowed chars, V6) |
| `DownstreamProfileId` | `dsp-<h16>` | canonical JSON of `DownstreamProfile` (§6): product set v + quality policy v + publication profile + land/analysis mask versions | any downstream choice changes; **re-enters at P5 from the archive, no ACOLITE, no SAFE** (DA-4) | — |
| `ReleaseId` | `rel-<h16>` | `RunAttemptId` + `DownstreamProfileId` | a new downstream profile, or a new successful attempt | — |
| `ProductKey` | lower snake, **platform-neutral** (T2) | `ProductSpec` | never for a given product | `tur_nechad2016`, `rhow_b04`, `l2_flags`, `true_colour` |
| Stable address | `<ObservationId>/<ProductKey>` | — | never; it resolves to the current release | what the viewer links to |
| Immutable address | `<ReleaseId>/<ProductKey>` | — | never | what provenance cites |

`h12`/`h16` are lowercase hex prefixes of SHA-256 over canonical JSON. Hash inputs **exclude**
absolute paths, hostnames, timestamps and `runid`, so two machines on the same pin, inputs and
settings compute the same `RunKey`.

**Why the profile is split (DA-4).** Tuning the quality policy, product set, masks or publication
after the bounded backfill must not force SAFE re-downloads and ACOLITE reruns. ACOLITE's output
depends only on the `AcoliteProfile`, because `l2w_parameters` is always the full Q4 list.

**Why `ancillary_tier` is inside the ACOLITE profile.** A run made with `GMAO_IT_MET` and a run made with
`GMAO_MERRA2_MET` are different results. Putting the tier in the profile gives them different
`RunKey`s. The upgrade from provisional to final (T7) then needs no special case: it is an ordinary
new run that supersedes the old release.

---

## 2. Spatial

| Type | Kind | Fields | Notes |
|---|---|---|---|
| `AOI` | dataclass, **keep** | name, geometry, crs | Gains a derived `aoi_id`. Validation unchanged |
| `GridSpec` | dataclass, **keep** | crs, resolution, bounds, width, height, transform | Validation unchanged |
| `DeliveryGrid` | model, new | `grid_id`, `aoi_id`, `spec: GridSpec`, `anchor: (x0, y0)`, `buffer_m`, `created_at` | One per AOI version. Anchor `(0, 0)` in EPSG:32619 (T13) |
| `LandMask` | model, new (DA-1) | `grid_id`, `version`, `coastline_source` (GSHHG version + sha256), `raster: ArtifactRef`, `land_pixels` | Built once per grid. **Applied at P5 to water products (NaN on land)**; recorded in provenance. Amends Q7: ACOLITE never calls its own `land_water_mask` at the tag |
| `AnalysisMask` | model, new | `grid_id`, `version`, `coastal_buffer_m`, `shallow_depth_m`, `coastline_source`, `bathymetry_source` (dataset + version + sha256), `raster: ArtifactRef`, `water_pixels` | **Statistics only**: excludes the coastal buffer (Q8) and optically shallow water (DA-3). `water_pixels` is the `valid_fraction` denominator |
| `AnalysisZone` | model, new | `zone_id`, `aoi_id`, `name`, `geometry` (EPSG:4326), `grid_id`, `pixel_count` | Predefined regions with pre-extracted series (T8) |

## 3. Processing configuration

| Type | Kind | Fields | Notes |
|---|---|---|---|
| `AcolitePin` | model | `release_tag`, `commit_sha` | From config; compared against the installation |
| `AcoliteInstallation` | model | `root`, `python_executable`, `observed_commit`, `config_version_line`, `luts_present: set[sensor]`, `gshhg_present` (OCEANOS `data/external/gshhg`), `credentials_present`, `free_disk_bytes` | Produced by the preflight probe. **Never** part of any hash |
| `AncillaryTier` | enum | `provisional` → `GMAO_IT_MET`, `final` → `GMAO_MERRA2_MET` | Chosen by scene age against a cutover (Brief assumption: 50 d) |
| `OwnedSettings` | model | `limit`, `merge_tiles`, `s2_target_res`, `l2w_parameters`, `l2w_mask_threshold`, `dsf_aot_estimate`, `ancillary_type`, `l1r_delete_netcdf`, `extract_inputfile`, `delete_extracted_input=True`, `rgb_rhot=False`, `rgb_rhos=False`, `netcdf_compression` | **Only** the keys OCEANOS owns. Everything else is left to ACOLITE's sensor-default layer (§9.2). The per-attempt keys `inputfile`, `output` and `runid` are *not* here |
| `AcoliteParameterSet` | model, new (B4) | `version`, `parameters: tuple[str]` (pinned Q4 list) | Owned by `AcoliteProfile`; the only source of `l2w_parameters` |
| `ProductSpec` | model | `product_key`, `acolite_parameter` (∈ `AcoliteParameterSet`), `variable_pattern`, `kind`, `unit`, `masked_by_acolite`, `land_masked: bool` (DA-1/B9: true for tur, spm, chl, rhow, Rrs; false for fai, fait, ndvi, l2_flags, true_colour), `shallow_exclusion_m: float \| None` (B7), `accepted_range`, `display_range`, `s2_calibrated`, `publish: archive_only \| cog`, `caveat` | `kind` ∈ `continuous`, `binary`, `bitfield`, `display` |
| `ProductSet` | model | `version`, `specs: tuple[ProductSpec]` | Versioned YAML; **selects** from `AcoliteParameterSet` (never the source of `l2w_parameters`; B4) |
| `QualityPolicy` | model | `version`, `min_valid_fraction` (0.20, over `AnalysisMask.water_pixels`), `min_grid_coverage`, `cloud_dilation_px`, `aot550_max`, `allowed_aerosol_models`, `glint_angle_min_deg`, `range_rules: tuple[RangeRule]`, `reject_on_ancillary_fallback` | DA-2. Numeric values are fixed in Phase 3 from spike data and reviewed at the DA-6 gate |
| `RangeRule` | model | `product_key`, `min`, `max`, `max_offending_fraction` | DA-2 |
| `AcoliteProfile` | model | `acolite: AcolitePin`, `settings: OwnedSettings`, `parameter_set_version`, `grid_id`, `ancillary_tier`, `contract_version` | Hashed to `AcoliteProfileId` |
| `DownstreamProfile` | model | `product_set_version`, `quality_policy_version`, `land_mask_version`, `analysis_mask_version`, `publication_profile: PublicationProfile` | Hashed to `DownstreamProfileId` |

## 4. Upstream contract and run planning

| Type | Kind | Fields | Notes |
|---|---|---|---|
| `SceneMetadata` | model, **extend** (T22e) | + optional `processing_level`, `processing_baseline`, `relative_orbit`, `datatake_id`, `mgrs_tile`, `source_id`, `checksums: ProviderChecksums` | Unknown stays `None`. `SceneSearchResult` moves to `schema_version "1.1"`; readers accept `"1.0"` |
| `ProviderChecksums` | model | `md5: str \| None`, `blake3: str \| None` | As published by CDSE. MD5 is verified; BLAKE3 is recorded only (T22d) |
| `AcquiredScene` | model | `scene_id`, `source_id` (OData UUID), `archive: ArtifactRef` (SHA-256), `provider_md5_verified: bool`, `safe_members_verified: bool`, `verified_at` | The upstream deliverable; the re-fetch key after the SAFE is deleted |
| `TileCandidate` | model | `scene_id`, `mgrs_tile`, `footprint` (EPSG:4326), `cloud_cover`, `aoi_fraction` | One per intersecting tile of an overpass |
| `TileCoverage` | model | `candidates: tuple[TileCandidate]`, `selected: tuple[mgrs]`, `covers_grid: bool` | `selected` = the **minimal footprint cover** of the grid polygon; ties broken by lower `cloud_cover`, then tile id (T22b). `covers_grid` = union(selected footprints) ⊇ grid polygon |
| `InputSet` | model | `input_set_id`, `overpass_id`, `scenes` (selected only, sorted), `coverage: TileCoverage`, `discovery_cloud_cover` (max over selected) | Invalid unless every scene shares the overpass and `covers_grid` is true. `merge_tiles` is written only when `len(selected) > 1` |
| `RunSpec` | model | `run_key`, `observation_id`, `input_set`, `profile`, `attempt_id`, `workspace` | Everything one attempt needs |

## 5. Run and ACOLITE outputs

| Type | Kind | Fields | Notes |
|---|---|---|---|
| `RunState` | enum | `planned` → `preflighted` → `executed` → `verified` → `archived` → `conformed` → `assessed` → `packaged` → `published`; terminals `failed`, `abandoned` | See `contracts.md` §2 |
| `StageName` | enum | `plan`, `preflight`, `execute`, `verify`, `archive`, `conform`, `assess`, `package`, `publish`, `retain` | — |
| `ArtifactRef` | model | `role`, `relpath` (relative to its tier root), `sha256`, `size`, `media_type` | Paths are **relative**. Fixes the portability defect in `CURRENT_STATE.md` §4 |
| `StageResult` | model | `stage`, `status`, `started_at`, `ended_at`, `artifacts`, `detail` | — |
| `RunAttempt` | model | `attempt_id`, `run_key`, `state`, `host`, `oceanos_version`, `oceanos_git_sha`, `acolite_exit_code`, `stages: list[StageResult]`, `failure: FailureRecord \| None` | Persisted as `run-manifest.json` |
| `FlagBit` | model | `name`, `bit`, `meaning`, `source_setting` | e.g. `swir_threshold`, bit 0, from `flag_exponent_swir` (B16: not called non_water; land is GSHHG's job) |
| `FlagSpec` | model | `bits`, `usable_mask_value` | Built from the **resolved** settings file (§7.1). The source of the STAC `classification:bitfields` |
| `AncillaryEvidence` | model | `ancillary_type`, `uoz`, `uwv`, `pressure`, `wind`, `fallback_detected` | Fallback = `uoz`/`uwv`/`pressure` equal ACOLITE's defaults (V2, confirmed at the tag in Phase 1) |
| `AerosolEvidence` | model | `aot550`, `aerosol_model`, `dsf_fit_diagnostics` | Read from L2R attributes; the attribute names are confirmed in Phase 1 (DA-2) |
| `AcoliteRunOutputs` | model | `l2r`, `l2w`, `log`, `settings_user`, `settings_resolved` (= `acolite_run_<id>_l2r_settings.txt`, the sensor-merged file), `acolite_version_attr`, `aerosol: AerosolEvidence`, `variables_present`, `flag_spec`, `ancillary`, `glint_angle_deg` | Returned only when verification passes |

## 6. Quality, observation, publication

| Type | Kind | Fields | Notes |
|---|---|---|---|
| `FlagStatistics` | model | `water_pixels`, `valid_pixels`, `per_bit_counts` | Over AOI ∩ water ∩ outside the coastal buffer, at full resolution |
| `RangeViolation` | model | `product_key`, `rule`, `offending_fraction` | — |
| `UsabilityVerdict` | enum | `usable`, `unusable` | Paired with `ReasonCode` when `unusable` |
| `QualityReport` | model | `observation_id`, `attempt_id`, `policy_version`, `valid_fraction`, `flags: FlagStatistics`, `range_violations`, `ancillary`, `verdict`, `reason` | `quality.json` |
| `ObservationStatus` | enum | `excluded_scene_cloud`, `incomplete_coverage`, `pending`, `processing_failed`, `no_usable_observation`, `usable` | **The** researcher-facing vocabulary for gaps (T6) |
| `ProcessingTier` | enum | `provisional`, `final` | Mirrors `AncillaryTier` |
| `Observation` | model | `observation_id`, `aoi_id`, `overpass_id`, `datetime`, `status`, `reason`, `current_release_id`, `tier` | One row per date the viewer lists |
| `CogProfile` | model | `compress`, `predictor`, `overview_resampling`, `blocksize`, `data_type` | Two instances: continuous (`DEFLATE`, `PREDICTOR=3`) and bitfield (`DEFLATE`, `PREDICTOR=2`, `MODE`) |
| `PublicationProfile` | model | `version`, `continuous: CogProfile`, `bitfield: CogProfile`, `published_products`, `true_colour: TrueColourSpec` | Hashed to `PublicationProfileId` |
| `TrueColourSpec` | model | `source` (L2R `rhos` bands by S2 name), `stretch` (fixed, not per-scene), `gamma` | Display-only (T4) |
| `PublishedAsset` | model | `product_key`, `href`, `sha256`, `media_type`, `roles`, `unit`, `nodata`, `data_type`, `overview_resampling`, `center_wavelength_nm` | — |
| `Release` | model | `release_id`, `observation_id`, `attempt_id`, `downstream_profile_id`, `tier`, `visibility`, `assets`, `quality: ArtifactRef`, `provenance: ArtifactRef`, `supersedes`, `created_at` | Immutable directory |
| `ProvenanceRecord` | model | see `contracts.md` §5 | `provenance.json` |

## 7. Time series, API, failure

| Type | Kind | Fields | Notes |
|---|---|---|---|
| `SeriesStatistics` | model | `valid_pixels`, `valid_fraction`, `mean`, `median`, `p10`, `p90`, `std` | T9 confirms the set |
| `SeriesPoint` | model | `observation_id`, `datetime`, `product_key`, `status`, `statistics \| None`, `release_id \| None`, `tier` | `statistics` is `None` exactly when the observation has no usable value; a gap is still a row |
| `SeriesQuery` | model | `zone_id` xor `geometry`, `product_key`, `start`, `end` | — |
| `Series` | model | `query`, `unit`, `points`, `computed_from` (`pre_extracted` \| `adhoc_full_resolution`) | — |
| `FailureCode` | enum | see `contracts.md` §6 | Dotted, stage-prefixed |
| `FailureScope` | enum | `observation`, `batch` | A `batch` failure (e.g. wrong ACOLITE commit) halts the whole run; an `observation` failure skips one overpass |
| `FailureRecord` | model | `code`, `scope`, `stage`, `message`, `evidence: list[str]`, `retryable`, `occurred_at` | `evidence` holds matched log lines and artifact paths, never a traceback alone |

---

## 8. Terminology

| Term | Means | Rejected synonyms | Why |
|---|---|---|---|
| **Scene** | one L1C SAFE (one MGRS tile) | granule, tile product | Already means this in `catalog/` and `ingestion/` |
| **Overpass** | the tiles of one datatake that together cover the AOI | acquisition, datatake group, pass | "Acquisition" collides with the download stage; "datatake" is ESA's term for the whole strip, not the AOI-relevant subset |
| **Observation** | outcome for one AOI × overpass, including "no usable observation" | capture, product, date | Covers the gap case, which "product" cannot |
| **Run / attempt** | a `RunKey` result / one execution of it | job, task | "Job" suggests a scheduler that does not exist |
| **Profile** | the versioned, hashed set of choices behind a result | config, recipe, parameters | "Config" is already `OceanosSettings`, which includes paths and is not hashed |
| **Product** | one layer identified by `ProductKey` | band, variable, index | "Band" is sensor vocabulary; "variable" is ACOLITE/NetCDF vocabulary, confined to the `acolite` adapter |
| **Release** | an immutable published set of products for one observation | version, publication | "Version" is overloaded with ACOLITE and package versions |
| **Valid** (pixel) / **usable** (observation) | `l2_flags == 0` ∧ finite ∧ in analysis mask / verdict above policy | clear, good, clean | The PRD's two gates stay lexically distinct (F9) |
| **Flag** / **mask** | an ACOLITE bit / a boolean derived from flags or geometry | — | A mask is always derived; a flag is always ACOLITE's |
| **Conform** (to the delivery grid) | what Fase 5 normalization becomes after ACOLITE | normalize, regrid, resample | "Normalize" suggests value scaling. The module keeps its name `normalize` to preserve history; the stage is named `conform` |
| **Tier** | `provisional` (NRT ancillary) / `final` | quality level, status | Keeps it from being confused with `ObservationStatus` |

No domain-glossary plugin is installed; this table is the glossary of record until one exists.
