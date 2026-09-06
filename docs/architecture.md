# Arquitectura hasta Fase 2

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

La CLI conecta la configuración, el AOI y el proveedor, muestra resultados y
opcionalmente escribe un JSON normalizado. No solicita el contenido de assets.
Los paquetes de ingestión, procesamiento raster, compuestos, publicación y API
siguen sin implementar lógica de esas etapas.

Los tests de catálogo simulan HTTP mediante `httpx.MockTransport` y usan fixtures
sintéticos. `tests/integration` solo se recopila con `--run-integration` y valida
el contrato contra el servicio real, sin descargar imágenes.
