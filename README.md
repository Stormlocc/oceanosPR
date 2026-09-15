# OCEANOS Puerto Rico

OCEANOS PR prepara productos costeros Sentinel-2 para el área de La Parguera. La implementación
actual publica una observación de extremo a extremo: descubrimiento L1C, selección de cobertura,
adquisición íntegra del SAFE, ACOLITE verificado, archivo, conformidad a la grilla de entrega y una
release inmutable con STAC derivado, con veredicto de calidad, máscaras de análisis y procedencia completa.

## Área de interés y grilla de entrega

Instala las dependencias con `uv sync` y ejecuta:

```bash
uv run oceanospr aoi info
uv run oceanospr aoi info --json
uv run oceanospr grid build
```

El AOI se valida como GeoJSON RFC 7946 en EPSG:4326 y puede configurarse en
`configs/mvp.yaml`. `aoi info --json` expone su `AoiId` determinista. `grid build` crea
`grid.json` bajo el tier `products`: una grilla fija EPSG:32619, de 10 m, anclada a múltiplos
UTM de 10 m e identificada por un `GridId` estable.

`configs/aoi/la_parguera_mvp.geojson` sigue siendo un rectángulo aproximado para el MVP, no un
límite oficial ni validado científicamente.

## Descubrimiento y catálogo L1C

```bash
uv run oceanospr scenes search --start 2026-06-01 --end 2026-09-01 --output scenes.json
uv run oceanospr scenes overpasses --start 2026-06-01 --end 2026-09-01
uv run oceanospr scenes overpasses --start 2026-06-01 --end 2026-09-01 --count
```

La búsqueda usa el catálogo OData anónimo de Copernicus Data Space y fija el tipo
`S2MSI1C`; no admite sustituir una colección L2A. Sigue toda la paginación, aborta ante páginas
fallidas o ciclos y registra únicamente metadatos en el catálogo STAC local. El documento de
intercambio usa `schema_version: "1.1"`; el lector conserva compatibilidad con documentos `1.0`.

```yaml
scenes:
  provider: "cdse"
  catalogue_url: "https://catalogue.dataspace.copernicus.eu/odata/v1"
  download_url: "https://download.dataspace.copernicus.eu/odata/v1"
  identity_url: "https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
  cloud_cover_max: null
  timeout: 30
  max_retries: 2
  page_size: 100
```

El catálogo local también puede recibir o listar el contrato normalizado:

```bash
uv run oceanospr catalog add scenes.json
uv run oceanospr catalog list
```

## Selección y adquisición SAFE

La selección agrupa escenas por overpass y calcula exhaustivamente el menor subconjunto de hasta
cuatro footprints que cubre la grilla. Los empates se resuelven por menor nubosidad seleccionada y
por tile ID. Solo esas escenas se adquieren:

```bash
uv run oceanospr scenes acquire --overpass S2A_20260702T150741_R082
```

Las credenciales se leen exclusivamente de la entrada `machine cdse` en `~/.netrc`. Los tokens
solo viven en memoria y se renuevan cuando quedan menos de 300 segundos. Cada descarga es un único
ZIP `product`, escrito como `.part`; se exige HTTP 200 y `Content-Length` completo, se verifica el
MD5 del proveedor, se calcula SHA-256 y se registra BLAKE3 sin verificarlo. Antes de publicación
atómica se inspecciona el ZIP sin extraerlo: un granule, metadata raíz/tile, las 13 bandas JP2 y
máscaras detector-footprint.

Los roots de almacenamiento y retención se configuran sin mezclar rutas persistidas absolutas:

```yaml
storage:
  raw: "raw"
  work: "work"
  archive: "archive"
  products: "products"
  superseded: "superseded"
  state: "state"
  failed_workspace_retention_days: 14
  superseded_releases_to_keep: 1
```

La ruta heredada que descargaba bandas L2A y el comando de normalización por escena fueron
retirados. El directorio local histórico `data/raw/sentinel2/`, si existe, queda huérfano e intacto.

## Preparación y fixtures de ACOLITE

ACOLITE queda fijado en la versión `20260421.0`, commit
`f73cbe73887c2b114d9d3c70865effee73871525`, y se ejecutará como proceso externo. Los LUT se
preparan previamente y GSHHG 2.3.7 se mantiene como dato de referencia propiedad de OCEANOS. Las
credenciales de EarthData y CDSE permanecen exclusivamente en `~/.netrc`.

```bash
scripts/acolite_env.sh --check
scripts/fetch_gshhg.sh --check
```

Los fixtures offline verificados están en `tests/fixtures/acolite/`. No contienen SAFEs ni
credenciales. La suite predeterminada no requiere red ni una instalación de ACOLITE:

```bash
uv run pytest -q
uv run ruff check src tests
```

## Fase 2.2: adaptador ACOLITE, verificación y archivo

`oceanos.acolite` ejecuta el ACOLITE fijado como subproceso y concentra todo su vocabulario:

- `InstallationProbe` comprueba sin importar ACOLITE el commit, la línea `version=`, los LUT de
  S2A/S2B/S2C, GSHHG, la entrada `earthdata` de `~/.netrc` y el disco libre.
- `SettingsRenderer` escribe solo las claves propiedad de OCEANOS más `inputfile`, `output` y
  `runid`. El `limit` es la grilla de entrega en EPSG:4326 ampliada un píxel y debe coincidir con
  el del perfil; `merge_tiles` solo aparece con más de una tesela.
- `SubprocessAcoliteRunner` lanza ACOLITE en su propio grupo de procesos, registra
  pid/pgid/cmdline del hijo en el lock y aplica el timeout configurado.
- `RunVerifier` nunca confía en el código de salida (ACOLITE sale con 0 al fallar): exige un único
  L2R, L2W y archivo de settings de cada tipo, busca mensajes de omisión en el log, valida
  `acolite_version`, variables pedidas (`rhorc_*` en L2R), unidades, ancilares por defecto y
  construye el `FlagSpec` desde los settings resueltos.

La identidad de procesamiento es `AcoliteProfile` → `RunKey`; la lista de `l2w_parameters` vive
solo en `configs/acolite_parameters.yaml` y `configs/products.yaml` únicamente selecciona de ella
lo que se publicará (v0: `tur_nechad2016` y `l2_flags`).

`pipeline/archive.py` copia atómicamente al tier `archive` solo la lista permitida (`*_L2R.nc`,
`*_L2W.nc`, `run.log`, `l1r_settings_user.txt`, `l2r_settings.txt`) junto a `run-manifest.json`.
Cada transición de intento se agrega con `fsync` a `state/ledger/attempts.jsonl`. Un lock libre con
intento no terminal se marca `abandoned`; su grupo de procesos solo se termina si coinciden
`boot_id`, tiempo de inicio y cmdline de `launch_acolite.py`.

```yaml
acolite:
  python_executable: "~/micromamba/envs/acolite/bin/python"
  launcher: "launch_acolite.py"
  root: "~/acolite"
  release_tag: "20260421.0"
  commit_sha: "f73cbe73887c2b114d9d3c70865effee73871525"
  luts_dir: "~/acolite/data/LUT"
  external_dir: "data/external"
  timeout_seconds: 1200
```

La suite predeterminada usa `FakeAcoliteRunner` con los fixtures de Fase 1. La ejecución real
sobre la escena A es opt-in:

```bash
uv run pytest --run-acolite -q tests/acolite_golden
```

## Fase 2.3: conformidad, release mínima y probe real

Una observación (AOI × overpass) se procesa y publica con:

```bash
uv run oceanospr grid build
uv run oceanospr scenes search --start 2026-07-02 --end 2026-07-03
uv run oceanospr pipeline run-one --overpass S2A_20260702T150741_R082 [--force-reprocess]
uv run oceanospr pipeline latest-release --overpass S2A_20260702T150741_R082
```

`run-one` exige una grilla y una búsqueda previas; nunca las crea. Selecciona y adquiere el SAFE,
calcula el `RunKey` y, bajo el `WriterLock`, ejecuta P1–P8. Si el `RunKey` ya está publicado lo omite,
salvo con `--force-reprocess`, que crea un intento nuevo con el mismo `RunKey`.

- **Conformidad (P5).** `processing/normalize.py` copia cada variable del NetCDF archivado a la
  grilla sin remuestrear: exige el mismo CRS, 10 m y alineación de fase, o falla con
  `grid.misaligned`; sin intersección falla con `grid.no_intersection`. Fuera de la extensión de
  ACOLITE los productos continuos quedan en NaN y `l2_flags` recibe el bit *out of scene* tomado del
  `FlagSpec`; se registra `grid_coverage_fraction`.
- **Máscara de tierra (DA-1).** `processing/masks.py` rasteriza GSHHG una vez por grilla en
  `products/<aoi>/grid/land_mask.tif` (centro de píxel en tierra) con su `land_mask.json`. Los
  productos de agua quedan NaN en tierra; `l2_flags` nunca se enmascara.
- **Publicación.** Los COG continuos usan `DEFLATE` + `PREDICTOR=3` y overviews `AVERAGE`; `l2_flags`
  usa `PREDICTOR=2` y overviews `MODE`. Siempre hay al menos una overview. La release
  `products/<aoi>/releases/<overpass>/<release_id>/` contiene `tur_nechad2016.tif`, `l2_flags.tif`,
  `settings_resolved.txt`, `provenance.json` y `release.json` con el SHA-256 de cada activo.
- **STAC derivado.** `products/<aoi>/stac/items/<overpass>.json` (STAC 1.1.0 con extensiones
  processing, classification y eo) apunta siempre a la release actual, con rutas relativas.
- **Commit de release.** Orden: renombrar la release nueva, reemplazar el Item, transacción de
  índice (Fase 4) y solo al final mover la anterior a `superseded/` con un evento en
  `state/ledger/releases.jsonl`. La reconciliación repara un corte en cualquier paso al inicio de
  `run-one`; el resto de comandos mutantes y `latest-release` la ejecutan en solo lectura y se niegan
  a continuar si un Item apunta a una release inexistente.
- **Veredicto.** En esta fase es fijo `usable`; la política de calidad llega en la Fase 3.

Verificación de una release y probe real (requiere red, CDSE, EarthData y ACOLITE fijado):

```bash
uv run python scripts/verify_release.py "$(uv run oceanospr pipeline latest-release --overpass S2A_20260702T150741_R082)"
scripts/probe_run_one.sh
```

Los esquemas STAC usados para validar están vendorizados en `tests/fixtures/stac-schemas/`.

## Fase 3: calidad, máscaras, set completo de productos y procedencia

La configuración científica vive en tres archivos versionados, cada umbral con su base escrita:

- `configs/products.yaml` (`ProductSet` v1): publica como COG `tur_nechad2016`, `spm_nechad2016`,
  `chl_re_gons740`, `fai`, `fait`, `ndvi`, `l2_flags` y `true_colour`; `rhow_*`, `Rrs_*` y
  `rhorc_*` quedan solo en el archivo. Cada producto declara unidad, rangos, corte somero y caveat.
- `configs/quality.yaml` (`QualityPolicy` v1): fracción válida mínima 0.20, cobertura 0.95,
  dilatación de nubes 3 px, AOT550 ≤ 0.5 (MOD1/MOD2), rhos negativo ≤ 10 %, rhow SWIR p90 ≤ 0.02,
  buffer costero 150 m y reglas de rango.
- `configs/publication.yaml` (`PublicationProfile` v1): perfiles COG y el color verdadero (B04/B03/B02
  de rhos, estiramiento fijo 0–0.25 con gamma 2 para todas las fechas).

**Máscaras.** La máscara de análisis (solo para estadísticas) excluye tierra más 150 m de costa y, en
turbidez, SPM y clorofila, el agua con profundidad menor de 7 m según NOAA CUDEM 1/9″ Puerto Rico
(2022v2). `fai`, `fait` y `ndvi` no tienen corte somero. Si algún producto queda con menos de 10 000
píxeles de análisis, el pipeline se detiene para una decisión del usuario.

```bash
scripts/fetch_bathymetry.sh          # 4 tiles con SHA-256 fijados
scripts/fetch_bathymetry.sh --check
```

**Veredicto (P6).** Un píxel es válido si no tiene cirrus ni TOA alto (dilatados), ni rhos negativo, ni
está fuera de escena; el bit 0 (umbral SWIR) es informativo. Los gates se aplican en orden: ancilares
por defecto, cobertura, aerosol, glint residual, rangos y fracción válida por producto sobre sus
píxeles de análisis. `chl_re_gons740` informa pero no decide, porque ACOLITE lo enmascara internamente.
El ángulo de glint lo calcula OCEANOS desde la geometría del L2R y solo se registra.

**Releases.** Una observación usable publica los 8 COG; una no usable publica una release
restringida con `true_colour` y `l2_flags`. Toda release incluye `quality.json`, `series.json`
(filas de la zona AOI completa, con huecos como filas sin estadísticas) y `provenance.json` con
escenas, ACOLITE, perfiles, ancilares, máscaras, derivaciones y `scientific_label`.

**Re-publicación sin ACOLITE (DA-4).** Un cambio en productos, calidad, máscaras o publicación crea un
`ReleaseId` nuevo desde el NetCDF archivado, sin descargar ni reprocesar:

```bash
uv run oceanospr pipeline republish --observation S2A_20260702T150741_R082
uv run oceanospr pipeline republish --range 2026-07-01 2026-07-31
```

El probe real acepta `--force-reprocess` y otra escena de la Fase 1 con `SCENES`/`SCENE_KEY`.

La prueba del catálogo CDSE real es opt-in:

```bash
uv run pytest --run-integration -q tests/integration/test_cdse_live.py
```
