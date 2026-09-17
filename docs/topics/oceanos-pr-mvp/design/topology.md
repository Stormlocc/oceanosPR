# Topology — modules and storage

**Status:** rounds 1–2 resolved · 2026-09-14; the `Status` column below is the design's
intent, not today's state - everything except `index` and `api` is implemented (Phases 0-3).
Reality notes from the 2026-09-17 clean-up are marked inline. Therefore `diagram_dialect.system` is **unset** and no C4 view
is emitted; `diagram_dialect.data` defaults to `mermaid`, but no typed data artifact is produced
here. Diagrams below are plain text, matching `CURRENT_STATE.md`.

---

## 1. Module boundaries

### 1.1 Packages

| Package | Responsibility | May import | Must not import | Status |
|---|---|---|---|---|
| `oceanos.domain` | ids, value objects, enums, profiles, failure taxonomy; **no I/O** | stdlib, pydantic, shapely/pyproj types | anything in `oceanos` except itself | new |
| `oceanos.config` | settings models + loading; new sections `acolite`, `products`, `quality`, `publication`, `storage`, `api` | `domain` | stages, adapters | extend |
| `oceanos.aoi` | AOI load/validate/reproject; derives `AoiId` | `domain` | — | keep (+id) |
| `oceanos.storage` | tier layout (paths from ids), staging + atomic commit + rollback, `file_sha256`/`artifact_ref`, `WriterLock` | `domain` | stages, adapters | new (extracted from `normalize_scene`) |
| `oceanos.catalog` | scene discovery + local scene STAC catalog | `domain`, `config`, `aoi`, `storage` | `acolite`, `processing`, `publishing` | keep; `cdse.py` `CdseODataProvider` (T22a); `sentinel2.py` **deleted 2026-09-16** |
| `oceanos.ingestion` | verified whole-SAFE acquisition: CDSE token, MD5 + SHA-256, zip member check (T22d) | `catalog`, `storage`, `domain` | `acolite`, `processing` | reshape (T22) |
| `oceanos.acolite` | **the only module that knows ACOLITE vocabulary**: settings rendering, probe, runner, log/NetCDF verification, `FlagSpec` extraction | `domain`, `storage` | `processing`, `publishing`, `api`, `pipeline` | new |
| `oceanos.processing` | `grid` (keep + AOI-anchored builder), `normalize` (conform), `quality` (pure core), `masks` (coastal analysis mask) | `domain`, `storage`, `aoi` | `acolite`, `publishing`, `api`, `pipeline` | reshape |
| `oceanos.timeseries` | zone pixel indices, pure aggregation, ad-hoc full-res reader | `domain`, `processing.quality` (valid-pixel predicate only) | `acolite`, `pipeline` | new (replaces `composites/`) |
| `oceanos.publishing` | COG writing with explicit profiles, true colour, STAC item build, release commit | `domain`, `storage` | `acolite`, `pipeline`, `api` | fill |
| `oceanos.index` | SQLite schema, `IndexWriter`, `IndexReader`, rebuild from ledger | `domain`, `storage` | stages, adapters | new |
| `oceanos.pipeline` | orchestration: plan, stage sequencing, ledger, retries, retention, backfill/update/reprocess | everything above except `api` | `api` | new |
| `oceanos.api` | read-only HTTP; role enforcement | `domain`, `config`, `index` (**reader only**), `timeseries` (reader), `storage` (read layout) | `acolite`, `pipeline`, `processing.normalize`, `publishing`, `index` writer | fill |
| `oceanos.__main__` | CLI: thin wiring onto `pipeline` and `catalog` | `pipeline`, `catalog`, `config`, `aoi` | direct stage internals | reshape (fixes the `if/elif` wiring noted in `CURRENT_STATE.md` §2.14) |
| `web/` (repo root) | static viewer | HTTP only | Python | new (T12) |

### 1.2 Dependency graph

```text
                          domain
      ┌──────────┬───────────┼────────────┬──────────────┬─────────────┐
    config      aoi       storage       index       (all below also import domain)
      │          │          │  │          │  │
      │          │   ┌──────┘  └───┐      │  └──────────── reader ──────────┐
      ▼          ▼   ▼             ▼      │                                  │
   catalog ──► ingestion        acolite   │                                  │
      │                            │      │                                  │
      │          processing ◄──────┼──────┼──── (no edge: acolite ⟂ processing)
      │          (grid, normalize, │      │
      │           quality, masks)  │      │
      │               │            │      │
      │          timeseries        │      │
      │               │            │      │
      │          publishing        │      │
      │               │            │      │
      └───────────► pipeline ◄─────┴──────┘ writer
                       │
                    __main__ (CLI)                api ──► index(reader), timeseries(reader), storage(read)
                                                   │
                                                 web/ (HTTP)
```

**Rules enforced by an architecture test** (`tests/test_architecture.py`, since Phase 2.2):

- **A1.** `acolite` and `processing` do not import each other. Conformance reads archived NetCDF
  through GDAL; it never calls ACOLITE code. This keeps ACOLITE's vocabulary in one adapter, the same
  way `catalog/` confines STAC vocabulary.
- **A2.** `api` never imports `pipeline`, `acolite`, `publishing` or the index writer. Read/write
  separation is structural, not a convention.
- **A3.** `domain` imports nothing from `oceanos`.
- **A4.** No module outside `acolite` references an ACOLITE variable name, setting key or log string.
  The `ProductSpec.variable_pattern` is data, resolved inside `acolite`.

### 1.3 ACOLITE deployment boundary

ACOLITE is **not** a Python dependency of `oceanos` (Q1, GPLv3 §10.3). It lives in its own
environment: clone at the pinned tag + micromamba env. `config.acolite` holds its interpreter path,
launcher path, pin, LUT directory and `external_dir`. `pyproject.toml` gains no ACOLITE entry.

**The environment check found a problem (2026-09-14) - RESOLVED in Phase 1.** `~/acolite` was a
shallow clone of `main` at `d61c8de`, not `20260421.0` / `f73cbe7`; the preflight rule
`env.acolite_commit_mismatch` correctly refused it. `scripts/acolite_env.py --install` replaced the
checkout at the pinned tag, preserving the old one, and `--check` now exits 0 at `f73cbe73…`.

---

## 2. Storage topology

### 2.1 Layout

```text
catalog/                                         gitignored since 2026-09-16; rebuilt by `scenes search`
  collections/<h(sentinel-2-l1c)>/items/…        + L1C collection (T22e)

data/                                            gitignored
  raw/sentinel2-l1c/<h(scene_id)>/               TRANSIENT
    <scene_id>.zip  manifest.json                deleted at P9 after archive (Q10)
  work/                                          SCRATCH, same filesystem as archive/ and products/
    runs/<attempt_id>/                           ACOLITE workspace (+ extracted SAFE, L1R deleted by ACOLITE)
    staging/.<stage>-<random>/                   per-stage staging, renamed into place on commit
  archive/<aoi_id>/<overpass_id>/<attempt_id>/   IMMUTABLE, indefinite (Q10)
    run-manifest.json  *_L2R.nc  *_L2W.nc
    acolite_run_<id>_log_file.txt
    acolite_run_<id>_l1r_settings_user.txt
    acolite_run_<id>_l2r_settings.txt          sensor-merged, the resolved settings (B14)
  products/<aoi_id>/                             PUBLISHED
    grid/grid.json  land_mask.{tif,json}         built once per grid from CUDEM (DA-1 amendment)
         coastal_buffer.tif  depth_m.tif  analysis_mask.json
         zones.geojson                            Phase 6
    releases/<overpass_id>/<release_id>/         IMMUTABLE (see contracts §4.3)
    stac/catalog.json  collection.json  items/<overpass_id>.json     atomically replaced
  superseded/<aoi_id>/<overpass_id>/<release_id>/  NOT SERVED; previous release moved here at P8 (DA-5), keep 1
  state/
    index.sqlite (+ -wal, -shm)                  DERIVED; rebuild via ledger scan
    ledger/attempts.jsonl                        append-only attempt ledger (incl. purged events; rebuild source for failures)
    ledger/releases.jsonl                        append-only release/supersession events (rebuild source for releases)
    run/api.sock                                 API Unix socket; directory mode 0750
  external/bathymetry/cudem/                     OCEANOS-owned CUDEM tiles, checksums pinned in scripts
    writer.lock                                  single-writer lock + holder record
```

### 2.2 Tiers

| Tier | Mutability | Truth or derived | Writer | Readers | Retention | Size driver |
|---|---|---|---|---|---|---|
| `catalog/` | append/update | truth (discovery) | pipeline | pipeline | indefinite; **not committed** | tiny |
| `data/raw` | replace | truth until archived | ingestion | P1–P2 | **until P9** | ~790 MB SAFE per selected tile; **1 tile per overpass for the current AOI** (T22b) |
| `data/work` | scratch | — | pipeline | pipeline | published: immediate · failed: 14 d | SAFE expansion + L2R peak; the disk budget in P1 |
| `data/archive` | **immutable** | **truth (processing)** | P4 only | P5 (reprocess), operator | indefinite | L2R + L2W NetCDF, compressed if T25 accepted |
| `data/products/…/releases` | **immutable** | truth (publication) | P8 only | API, viewer | **current only** | ~7 MB per Float32 layer before compression, × published products |
| `data/products/…/stac` | atomic replace | derived from releases | P8 | viewer, API | tracks current | tiny |
| `data/state/index.sqlite` | transactional | **derived** | pipeline | API (read-only, WAL) | rebuildable | series rows: zones × observations × products |

**Placement rule.** `work/`, `archive/` and `products/` must share one filesystem, so every commit is
an atomic `os.replace`. The preflight checks this with `st_dev`.

**Portability.** Manifests and releases store **relative** paths from their tier root (`ArtifactRef.relpath`).
Absolute paths are resolved at runtime from config. This removes the absolute-path annotations
flagged in `CURRENT_STATE.md` §4 for everything new; the existing scene catalog annotations are
left as they are.

**Rebuild guarantee.** Deleting `data/state/index.sqlite` loses nothing. `oceanos index rebuild`
scans `archive/**/run-manifest.json` and `products/**/release.json` and restores every table. Only
`zones` is re-read from `grid/zones.geojson`. This is the same "repairable from manifest" property
`ingestion.fetch` has today (`CURRENT_STATE.md` §2.7).
