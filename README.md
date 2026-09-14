# OCEANOS Puerto Rico

## Fase 1: Areas Of Interest

Instala las dependencias con `uv sync` y, desde la raíz del proyecto, ejecuta:

```bash
uv run python -m oceanos aoi info
# Con el entorno virtual activado:
python -m oceanos aoi info
python -m oceanos aoi info --config configs/mvp.yaml
```

La CLI muestra nombre, CRS de trabajo, bounds `(min_x, min_y, max_x, max_y)`,
tipo de geometría y estado de validación. Los bounds usan las unidades del CRS
de trabajo (metros para el EPSG:32619 del MVP). Un error devuelve código 1.

El archivo `configs/aoi/la_parguera_mvp.geojson` es un **rectángulo aproximado
para configuración del MVP**, no un límite oficial ni validado científicamente.
Para sustituirlo, modifica únicamente esta sección de `configs/mvp.yaml`:

```yaml
aoi:
  name: "Mi área de estudio"
  path: "configs/aoi/mi_area.geojson"
  target_crs: "EPSG:32619"
```

Las rutas relativas del AOI se resuelven desde la raíz configurada del proyecto,
igual que `data_root`, no desde el directorio de datos. `load_config` permite
cambiar esa raíz mediante `base_dir`; por defecto usa el padre del directorio
del YAML. También se admiten rutas absolutas y variables como
`OCEANOS_AOI__PATH` y `OCEANOS_AOI__TARGET_CRS`.

```python
from oceanos.aoi import load_aoi, validate_aoi, get_bounds, reproject_aoi

aoi = load_aoi("tests/fixtures/aoi.geojson", name="Ejemplo")
validate_aoi(aoi)  # True o AOIError con el motivo
projected = reproject_aoi(aoi, "EPSG:3857")
bounds = get_bounds(projected)
projected.save("/tmp/ejemplo.geojson")
```

La entrada admite geometrías Polygon/MultiPolygon, Features y colecciones con
una sola Feature, incluyendo polígonos con huecos. Se exige GeoJSON RFC 7946
en EPSG:4326, con coordenadas `(longitud, latitud)`. Los miembros `crs` antiguos
se rechazan explícitamente. Se validan cierre de anillos, topología, geometría
no vacía y coordenadas finitas bidimensionales; no se reparan geometrías
automáticamente. La reproyección devuelve un AOI nuevo y mantiene el orden x/y.
`to_geojson()` y `save()` serializan en EPSG:4326 para mantener compatibilidad
con GeoJSON, incluso si el AOI está en un CRS proyectado.

Ejecuta los tests con `uv run pytest`. Los tests geométricos utilizan un AOI
sintético en `tests/fixtures/aoi.geojson`. Esta fase no realiza búsquedas
satelitales ni ingestión.

## Fase 2: descubrimiento de escenas Sentinel-2

```bash
python -m oceanos scenes search --start 2024-01-01 --end 2024-01-10 --output scenes.json
python -m oceanos scenes search --start 2024-01-01 --end 2024-01-10 --cloud-cover-max 20
```

Con el entorno sin activar, antepone `uv run`. La CLI muestra una tabla con ID,
colección, plataforma, fecha UTC, porcentaje de nubes y número de assets.
`--config` permite usar otro YAML y `--collection` sustituye la colección
configurada. Un día final como `2024-01-10` incluye todo ese día UTC; también
se admiten timestamps ISO con zona horaria. El intervalo es inclusivo.

La sección `scenes` de `configs/mvp.yaml` configura:

```yaml
scenes:
  catalog_url: "https://earth-search.aws.element84.com/v1"
  collection: "sentinel-2-l2a"
  cloud_cover_max: null
  timeout: 30
  max_retries: 2
  page_size: 100
```

Estas opciones admiten variables de entorno, por ejemplo
`OCEANOS_SCENES__CATALOG_URL`. El proveedor utiliza POST `/search`, la geometría
completa del AOI en WGS84 y, si se pide un máximo de nubes, la extensión STAC
Query con `eo:cloud_cover <= máximo`. Ese porcentaje describe la escena completa,
no la nubosidad específica dentro del AOI. El catálogo seleccionado debe admitir
POST Item Search y Query cuando se utiliza este filtro.

`SceneProvider.search(aoi, start_datetime, end_datetime, collection,
cloud_cover_max=None)` devuelve `list[SceneMetadata]`. `Sentinel2Provider` adapta
STAC a ese contrato; las etapas posteriores consumen los modelos de
`oceanos.catalog`, sin interpretar propiedades particulares del catálogo.
`SceneMetadata` contiene ID, colección, plataforma, fecha UTC, geometría y bbox
WGS84, nubosidad, referencias a assets y catálogo de origen. Los assets normalizan
`href`, `media_type`, `title` y `roles`; sus nombres conservan las claves del
catálogo. No se accede a sus URLs. Plataforma y nubosidad desconocidas se expresan
como `null`, y la ausencia de assets como `{}`. La fecha de adquisición,
geometría, bbox, ID y colección son obligatorios; respuestas que no los aportan
producen un error explícito.

La búsqueda sigue enlaces `next` GET o POST, incluidos `headers`, `body` y
`merge`, hasta agotarlos; `page_size` no limita el total. Se conserva la primera
aparición de cada `scene_id` y se detectan ciclos de paginación. El timeout se
aplica a las operaciones de conexión/lectura/escritura de cada petición, no a la
búsqueda completa. Por defecto hay hasta tres intentos por página ante fallos de
transporte o HTTP 408/429/500/502/503/504, con pausas de 0,5 y 1 segundos.
`Retry-After` se respeta con un máximo de 30 segundos. Los demás errores HTTP y
las respuestas malformadas fallan sin reintentos. Si falla una página, no se
publican resultados parciales ni se sustituye el JSON existente.

`--output` escribe un documento normalizado versionado:

```json
{"schema_version": "1.0", "scenes": []}
```

Ese es también el resultado válido de cero coincidencias; la CLI termina con
código 0. Los errores terminan con código 1. Un ejemplo completo, **sintético**,
está en [docs/examples/scenes.json](docs/examples/scenes.json), generado mediante
el mismo adaptador con `tests/fixtures/stac_item.json`. Puede volver a cargarse
con `SceneSearchResult.model_validate_json(...)`.

```bash
# Suite habitual: STAC simulado, sin Internet.
uv run pytest -q

# Prueba manual: servicio real, AOI de La Parguera, páginas de una escena.
uv run pytest --run-integration tests/integration -q
```

Los tests de integración no se recopilan por defecto. La prueba manual requiere
conectividad y disponibilidad del catálogo; consulta únicamente metadatos de una
ventana histórica corta. Esta fase no descarga bandas ni procesa rasters.

Referencias del protocolo: [STAC Item Search y paginación](https://github.com/radiantearth/stac-api-spec/tree/main/item-search)
y [colección Sentinel-2 L2A de Earth Search](https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a).

## Fase 3: catálogo STAC local

```bash
python -m oceanos catalog add scenes.json
python -m oceanos catalog list
```

`catalog add` recibe el JSON **normalizado de Fase 2**. El MVP guarda el catálogo
en `catalog/catalog.json`, con una Collection inicial `sentinel-2-l2a`. Las
escenas con otra colección conservan su ID de colección en una Collection
separada. Se incluye un catálogo inicial vacío, sin importar los ejemplos
sintéticos como si fueran observaciones reales.

En `configs/mvp.yaml`, `catalog_dir: "../catalog"` se resuelve desde `data_root`
para situar el catálogo en la raíz del proyecto. Puedes cambiarlo con
`OCEANOS_CATALOG_DIR`, otro YAML (`--config`) o `--catalog-dir /ruta/catalogo`
en cualquiera de los dos comandos. No se migra automáticamente el antiguo
directorio vacío `data/catalog`.

```text
catalog/
  catalog.json
  collections/<hash de collection>/
    collection.json
    items/<hash de scene_id>.json
```

Los nombres de archivo usan SHA-256 para mantener rutas estables y admitir IDs
con caracteres que no son seguros en rutas. Los IDs originales permanecen
intactos dentro del STAC. Los enlaces entre documentos son relativos; todo el
directorio puede copiarse y recargarse. Los assets conservan exactamente sus URLs,
tipos MIME, títulos y roles, sin consultar ni descargar su contenido.

La conversión conserva geometría, bbox, fecha UTC, plataforma, colección y
nubosidad (`eo:cloud_cover`, con la extensión EO declarada cuando corresponde).
La procedencia se añade separadamente:

| Propiedad del Item | Significado |
| --- | --- |
| `oceanos:original_scene_id` | ID de la escena descubierta; coincide con `id`. |
| `oceanos:source_catalog` | Catálogo remoto original. |
| `oceanos:source_provider` | Adaptador de origen; por defecto `Sentinel2Provider`. |
| `oceanos:ingested_at` | Fecha UTC del primer registro **de metadatos** local. |
| `oceanos:processing_status` | `discovered`; no implica descarga ni procesamiento. |

No se inventan valores científicos ausentes: plataforma y nubosidad opcionales
se omiten del Item y se reconstruyen como `None`. La Collection vacía tiene una
extensión espacial global y un intervalo temporal abierto, identificados con
`oceanos:extent_status = empty`; al añadir escenas se recalcula su extensión
real y el estado pasa a `from_scenes`. `license: other` no concede una licencia
nueva sobre los assets remotos.

```python
from oceanos.catalog import (
    LocalSceneCatalog, SceneSearchResult, scene_from_stac_item,
)
from pathlib import Path

catalog = LocalSceneCatalog("catalog")
scenes = SceneSearchResult.model_validate_json(Path("scenes.json").read_text())
for scene in scenes.scenes:
    inserted = catalog.add_scene(scene)  # True al añadir; False si ya era idéntica
    assert catalog.scene_exists(scene.scene_id)
    assert catalog.get_scene(scene.scene_id) == scene
    item = catalog.get_stac_item(scene.scene_id)
    assert scene_from_stac_item(item) == scene

matches = catalog.search_local_catalog(cloud_cover_max=20)
```

`get_scene` devuelve `SceneMetadata` o `None` si no existe el ID.
`search_local_catalog` devuelve resultados ordenados por ID; admite filtros por
AOI, colección, plataforma, fechas `datetime` con zona horaria (límites
inclusivos) y máximo de nubes. La nubosidad desconocida no satisface un máximo.
Todas estas operaciones trabajan con documentos locales, sin red.

Añadir una escena idéntica dos veces no crea archivos ni enlaces duplicados,
ni cambia `ingested_at`. Un ID existente con metadatos distintos produce
`LocalCatalogError`, conservando la escena original. Cada adición se persiste
antes de devolver el resultado. Las escrituras reemplazan cada JSON de forma
atómica y están previstas para **un escritor a la vez**; la importación de una
lista registra las escenas sucesivamente, no como una transacción de lote.

`uv run pytest -q` incluye creación, catálogo vacío, duplicados, conflictos,
recuperación, búsquedas, persistencia, recarga, traslado del catálogo,
reconstrucción desde Items y validación con esquemas STAC locales. No se han
añadido descargas de raster ni procesamiento.

La persistencia utiliza el formato de catálogo con enlaces relativos de
[PySTAC](https://pystac.readthedocs.io/en/stable/api/catalog.html).

## Fase 4: materialización controlada de una escena

La escena debe estar registrada previamente en el catálogo local:

```bash
python -m oceanos scenes fetch SCENE_ID
python -m oceanos scenes fetch SCENE_ID --bands B02 B03 B04 B08 B11
# También puedes materializar solo una parte del MVP:
python -m oceanos scenes fetch SCENE_ID --bands B02 B03
```

El comando admite `--config`, `--catalog-dir`, `--raw-dir` y `--timeout` (60
segundos por operación HTTP por defecto). Usa `raw_dir` de la configuración,
creando `data/raw/sentinel2/{scene_id}/` en el MVP. Solo se permiten las cinco
bandas indicadas; no se solicitan otras bandas, previews ni archivos de QA.

| Banda | Clave alternativa del asset |
| --- | --- |
| B02 | `blue` |
| B03 | `green` |
| B04 | `red` |
| B08 | `nir` |
| B11 | `swir16` |

Se priorizan las claves B02/B03/B04/B08/B11 sobre sus alternativas. `nir08`
(B8A) no sustituye a B08. Antes de iniciar transferencias se comprueba que la
escena y **todos** los assets solicitados existen. Esta implementación admite
URLs HTTP(S); otros protocolos producen un error explícito antes de descargar.
Los IDs deben ser componentes de ruta seguros, como los IDs habituales de
Sentinel-2.

Cada archivo completo se registra en `manifest.json`:

```json
{
  "schema_version": "1.0",
  "scene_id": "S2A_EXAMPLE",
  "status": "partial",
  "assets": {
    "B02": {
      "asset_key": "blue",
      "source_url": "https://assets.example/blue.tif",
      "download_timestamp": "2024-01-01T12:00:00Z",
      "local_path": "B02.tif",
      "file_size": 123456,
      "sha256": "<64 caracteres hexadecimales calculados del archivo>"
    }
  },
  "failures": {}
}
```

Este fragmento es ilustrativo. Las rutas del manifiesto son relativas al
directorio de la escena; las fechas y SHA-256 reales se calculan al completar
cada transferencia. Los nombres locales conservan la extensión `.tif`, `.tiff`
o `.jp2` cuando figura en la URL; en otros casos usan `.bin`, sin convertir el
formato del archivo.

Antes de reutilizar un archivo se comprueba que existe, coincide con su asset
y URL originales, conserva el tamaño y tiene el mismo SHA-256 del manifiesto.
Si el catálogo aporta `file:size`, también debe coincidir. Ese tamaño ahora se
conserva en el modelo normalizado `SceneAsset.file_size` y al guardar/recargar
STAC. Un archivo sin un registro completo, aunque tenga el tamaño esperado,
se vuelve a descargar. No se confía en archivos `.part` sobrantes.

Las transferencias usan streaming y un temporal `.part` en el mismo directorio
del destino. Se exige una respuesta HTTP 200 completa y se compara el tamaño
con `file:size` y/o `Content-Length`, cuando estén disponibles. Se rechazan
respuestas parciales HTTP 206, archivos vacíos y tamaños inconsistentes. Cuando
no hay tamaño remoto, se exige que el stream termine sin error y se registra
el tamaño recibido. Tras cerrar y sincronizar el temporal, `os.replace` publica
el archivo atómicamente. Se guardan el manifiesto y el resultado en el catálogo
después de completar cada banda.

Una transferencia fallida elimina su temporal, registra el error en `failures`
y termina con código 1. Las bandas ya completadas quedan disponibles para
reutilizarse al repetir el comando; la banda interrumpida comienza desde cero.
Un archivo publicado antes de un fallo al guardar el manifiesto no se reutiliza
sin una verificación registrada. Si solo falló la actualización del catálogo,
la siguiente ejecución puede repararla usando el manifiesto ya guardado, sin
repetir la transferencia. Como en Fase 3, se admite un escritor a la vez.

El catálogo conserva los `href` originales y añade `oceanos:local_path`,
`oceanos:file_size`, `oceanos:sha256` y `oceanos:download_timestamp` a los assets
materializados. El Item registra `oceanos:manifest_path` y
`oceanos:materialization_status`: `complete` significa que las **cinco bandas
MVP** están verificadas; `partial` indica que solo algunas lo están; `failed`
indica un fallo sin bandas verificadas; `pending` indica que aún no hay archivos
ni fallos registrados. Su `oceanos:processing_status` pasa respectivamente a
`materialized`, `partially_materialized`, `materialization_failed` o `discovered`.
La geometría, fecha, nubosidad y metadatos científicos originales permanecen
intactos, y sigue siendo posible reconstruir `SceneMetadata` desde el Item.

La repetición de una materialización ya verificada no realiza peticiones de
assets ni modifica archivos, timestamps o metadatos. Todos los archivos del
manifiesto se verifican de nuevo, incluso si la nueva petición selecciona menos
bandas, para detectar archivos borrados o alterados. Las rutas locales anotadas
en STAC son absolutas; tras mover los datos, vuelve a ejecutar `fetch` con la
nueva raíz para verificarlos y actualizar esas rutas.

`uv run pytest -q` cubre descargas simuladas, archivos existentes, interrupciones,
ausencia de assets, verificación de tamaños y checksums, idempotencia,
manifiestos y actualización del catálogo. Los tests bloquean conexiones reales
y no descargan bandas de Sentinel-2. Esta fase no calcula índices ni transforma
rasters.

## Fase 5: normalización espacial

```bash
python -m oceanos process normalize SCENE_ID
python -m oceanos process normalize SCENE_ID --resolution 10 --buffer 100
```

Se requieren las cinco bandas materializadas en Fase 4. Se verifica su tamaño,
URL de origen y SHA-256 contra el manifiesto antes de abrir los rasters; una
banda ausente o incompleta produce un error, sin iniciar una descarga.

La configuración `normalization` define la grilla y el remuestreo:

```yaml
normalization:
  target_resolution: 10
  buffer_m: 0
  reference_band: "B02"
  continuous_resampling: "bilinear"
  warp_memory_limit_mb: 64
```

La resolución y el buffer se expresan en **metros**. El CRS de destino es
`aoi.target_crs`, que debe ser proyectado y usar metros. La CLI admite
`--target-crs`, `--resolution`, `--buffer`, `--resampling nearest|bilinear` y
`--config`. También se admiten variables como
`OCEANOS_NORMALIZATION__TARGET_RESOLUTION`.

`GridSpec` contiene `crs`, `resolution`, `bounds`, `width`, `height` y
`transform`. Se crea una sola vez por escena usando B02 como referencia inicial
(alternativas configurables de 10 m: B03, B04 o B08). Si el CRS coincide, se
conserva el origen de píxel de la referencia; al reproyectar se calcula un
origen común con Rasterio/GDAL. Los límites del AOI con buffer se ajustan hacia
afuera a esa grilla, que puede extenderse menos de un píxel más allá del recorte
solicitado. El recorte usa la forma completa del AOI, incluidos huecos y
MultiPolygon; los centros de píxel fuera del AOI con buffer se escriben como
nodata. Las zonas sin cobertura de la banda también son nodata.

Las cinco bandas de reflectancia continua usan `bilinear` por defecto;
`continuous_resampling: nearest` permite sustituirlo. La API
`normalize_band(..., categorical=True)` utiliza obligatoriamente `nearest` para
máscaras o categorías y rechaza una petición explícita de `bilinear`. Esta fase
no descarga ni incorpora nuevas bandas de QA.

```python
from oceanos.processing import build_grid, normalize_band

# aoi es un objeto AOI cargado mediante oceanos.aoi.load_aoi.
grid = build_grid("B02.tif", aoi, target_crs="EPSG:32619", resolution=10, buffer_m=100)
normalize_band("B11.tif", "B11_normalized.tif", grid)
# Para una máscara local, si se dispone de ella:
normalize_band("SCL.tif", "SCL_normalized.tif", grid, categorical=True)
```

La salida de la CLI queda en:

```text
data/intermediate/{scene_id}/normalized/
  B02.tif
  B03.tif
  B04.tif
  B08.tif
  B11.tif
  manifest.json
```

Cada GeoTIFF tiene **exactamente el mismo CRS, transform, width, height y
bounds**. Se comprueba la igualdad al releer los archivos, antes de publicar el
conjunto. Las bandas se generan en un directorio temporal; una normalización
fallida conserva el conjunto anterior. La sustitución usa un directorio de
respaldo durante el cambio y está prevista para un escritor a la vez.

Los outputs son GeoTIFF Float32 con compresión DEFLATE y nodata NaN. Se respetan
el nodata y las máscaras del raster de origen, preservando ceros válidos cuando
no representan nodata. Se conservan escala, offset y unidades del origen, sin
aplicarlos a los valores numéricos. Los inputs admitidos en este MVP son
enteros de hasta 16 bits o Float32. Las categorías enteras admitidas se conservan
exactamente con nearest aunque su contenedor de salida sea Float32.

Tanto los tags del raster como `manifest.json` registran `native_resolution`,
`processing_resolution` y `resampling_method`, junto con el CRS y las unidades
de la resolución nativa. Por ejemplo, B11 conserva su resolución nativa de 20 m
aunque la grilla de procesamiento sea de 10 m. El manifiesto registra además la
grilla completa, la banda de referencia, el buffer, las rutas y tamaños.

La reproyección utiliza Rasterio `WarpedVRT` y lee/escribe bloques de 256 × 256
píxeles, procesando una banda a la vez. `warp_memory_limit_mb` limita la memoria
de warp y se aplica también, separadamente, a la caché GDAL. Estos límites no
son un límite estricto sobre la memoria total del proceso. Al terminar, la CLI
reporta dimensiones, bounds, transform, tamaño real de los rasters en disco,
tamaño sin compresión y pico RSS del proceso (cuando la plataforma lo permite).
Ese pico incluye el intérprete y las bibliotecas; no se presenta como memoria
exclusiva de los arrays ni como una lectura instantánea.

`uv run pytest -q` valida mismo CRS, reproyección, cambios de resolución,
dimensiones, transform, bounds, nodata, máscaras, remuestreo categórico y
alineación exacta de todas las bandas. Se usan rasters sintéticos pequeños y no
se consulta Internet. No se calculan FAI, NDVI ni otros índices científicos.

Referencia: [reproyección con Rasterio](https://rasterio.readthedocs.io/en/stable/topics/reproject.html).

## Fase 0: preparación del MVP ACOLITE

La preparación del MVP corrige el script de consola a `oceanospr`, elimina la
dependencia no utilizada `pandas` y añade Ruff y mypy al grupo de desarrollo.
Ruff apunta a Python 3.11; mypy opera en modo estricto cuando se incorporen los
paquetes nuevos definidos por el plan.

`tests/test_architecture.py` protege los límites iniciales del MVP: ACOLITE y
procesamiento no se importan mutuamente, la API no importa escritores ni
etapas de procesamiento, el dominio no depende de otros paquetes OCEANOS y el
vocabulario de ACOLITE queda restringido a su adaptador. La suite predeterminada
continúa siendo offline.
