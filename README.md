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
