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
