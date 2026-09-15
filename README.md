# OCEANOS Puerto Rico

OCEANOS PR prepara productos costeros Sentinel-2 para el área de La Parguera. La implementación
actual cubre el entorno ACOLITE verificado y las etapas A0–A2: descubrimiento L1C, selección de
cobertura y adquisición íntegra de productos SAFE.

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

La prueba del catálogo CDSE real es opt-in:

```bash
uv run pytest --run-integration -q tests/integration/test_cdse_live.py
```
