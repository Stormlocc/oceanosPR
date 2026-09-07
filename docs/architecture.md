# Arquitectura hasta Fase 3

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
No solicita el contenido de assets.
Los paquetes de ingestión, procesamiento raster, compuestos, publicación y API
siguen sin implementar lógica de esas etapas.

Los tests de catálogo simulan HTTP mediante `httpx.MockTransport` y usan fixtures
sintéticos. `tests/integration` solo se recopila con `--run-integration` y valida
el contrato contra el servicio real, sin descargar imágenes. Los tests del
catálogo local bloquean conexiones de red y validan los JSON contra los esquemas
STAC incluidos en PySTAC, además de comprobar la reconstrucción del modelo.
