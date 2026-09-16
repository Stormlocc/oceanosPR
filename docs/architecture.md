# Arquitectura hasta Fase 5

> **Alcance histórico (nota 2026-09-16).** Este documento describe el linaje **anterior** al MVP
> ACOLITE: descubrimiento STAC contra Element84, materialización de bandas sueltas y
> `normalize_scene`. Ese camino fue reemplazado y su código ya no existe: `Sentinel2Provider`,
> `fetch_scene`, `normalize_scene`, `normalize_band` y `build_grid` fueron retirados.
>
> La arquitectura vigente es **AOI -> descubrimiento L1C en CDSE -> adquisición íntegra del SAFE ->
> ACOLITE como subproceso -> conformidad a la grilla de entrega -> calidad -> release inmutable**,
> descrita en las secciones "Fase N" de `README.md` y en `docs/topics/oceanos-pr-mvp/`
> (`PLAN.md` y `design/`). Reescribir este archivo es una tarea pendiente de la Fase 7.
>
> Lo que de este documento **sigue vigente**: la configuración tipada, `oceanos.aoi`,
> `LocalSceneCatalog`, `GridSpec` y el modelo de un solo escritor.

La configuración tipada (`oceanos.config`) resuelve las rutas del proyecto y
separa la definición del AOI de las opciones de descubrimiento. Cargar el YAML
no realiza peticiones remotas ni crea directorios.

`oceanos.aoi` carga, valida, reproyecta y serializa AOIs. El GeoJSON de La Parguera
es un ejemplo sustituible desde configuración.

`oceanos.catalog.SceneProvider` define el contrato de descubrimiento.
`Sentinel2Provider` implementa STAC Item Search, paginación y tolerancia a fallos;
la interpretación del JSON remoto queda encapsulada en ese adaptador.
`SceneMetadata`, `SceneAsset` y `SceneSearchResult` definen los datos normalizados
que pueden consumir las fases posteriores. Geometrías y bounds de escenas usan
WGS84, independientemente del CRS de trabajo del AOI.

`LocalSceneCatalog` persiste esos modelos con PySTAC. El catálogo raíz contiene
Collections que conservan los IDs de colección de origen; cada escena se guarda
como un Item con geometría, bbox, tiempo y assets remotos originales. La
procedencia local utiliza el namespace `oceanos`. `scene_from_stac_item` devuelve
el mismo `SceneMetadata`, permitiendo que otras etapas sigan usando ese modelo.
Los documentos usan enlaces relativos y nombres de archivo derivados de sus IDs.
La deduplicación es global por ID: una repetición idéntica no escribe cambios y
una repetición con metadatos distintos produce un error. Se admite un escritor
a la vez; cada operación recarga los cambios ya persistidos.

La CLI conecta la configuración, el AOI y el proveedor, muestra resultados,
escribe JSON normalizado y permite registrarlo o listarlo en el catálogo local.
Los comandos de descubrimiento y catálogo no solicitan el contenido de assets.

`oceanos.ingestion.fetch_scene` materializa exclusivamente las bandas MVP
solicitadas de una escena ya catalogada. Resuelve claves de bandas, verifica
copias existentes mediante tamaño y SHA-256, transfiere a temporales y publica
los archivos completos mediante reemplazo atómico. Un manifiesto por escena
registra resultados verificados y fallos. El catálogo recibe anotaciones locales
con namespace `oceanos`, manteniendo intactos los assets remotos y la metadata
científica. `SceneAsset.file_size` conserva el tamaño remoto si estaba disponible.
La materialización utiliza el mismo modelo de un escritor a la vez del catálogo.

`oceanos.processing.GridSpec` define una grilla métrica común, referenciada a
B02 por defecto y ajustada al AOI con buffer. `normalize_scene` verifica el
manifiesto de materialización y aplica esa única grilla a las cinco bandas.
`normalize_band` usa Rasterio/GDAL en bloques, conserva nodata/máscaras y
escala/offset, y distingue reflectancia continua (bilinear por defecto) de
categorías (nearest obligatorio). Los rasters y su manifiesto se publican
conjuntamente después de comprobar la igualdad exacta de CRS, transform,
dimensiones y bounds. La CLI reporta tamaño, dimensiones y memoria del proceso.

Compuestos, publicación y API siguen sin implementar lógica de esas etapas;
no se calculan FAI, NDVI ni otros índices científicos.

Los tests de catálogo simulan HTTP mediante `httpx.MockTransport` y usan fixtures
sintéticos. `tests/integration` solo se recopila con `--run-integration` y valida
el contrato contra el servicio real, sin descargar imágenes. Los tests del
catálogo local bloquean conexiones de red y validan los JSON contra los esquemas
STAC incluidos en PySTAC, además de comprobar la reconstrucción del modelo.
Las transferencias se prueban con streams sintéticos, incluyendo fallos y tamaños
inconsistentes; la suite habitual no descarga archivos reales.
La normalización usa rasters sintéticos con distintas resoluciones y CRS, nodata
y máscaras; comprueba también la conservación de los outputs previos ante fallos.
