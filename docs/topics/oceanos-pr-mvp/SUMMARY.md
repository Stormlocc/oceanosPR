# OCEANOS PR — Estado del proyecto

**Fecha:** 2026-09-12 · **Rama:** `master` @ `9fa73b3` · **Fase:** descubrimiento, producto, investigación y contrato **completos**; arquitectura **no iniciada**.

Punto de entrada a todo lo producido. Cada sección enlaza al documento donde vive el detalle.

---

## 1. Qué se hizo, en orden

| # | Etapa | Producto | Estado |
|---|---|---|---|
| 1 | Evaluación del código existente | [`CURRENT_STATE.md`](CURRENT_STATE.md) | Completa — se leyó cada archivo de `src/` y `tests/` |
| 2 | Definición de producto | [`PRD.md`](PRD.md) | `draft` — 7 decisiones de producto |
| 3 | Investigación ACOLITE | [`research/ACOLITE_TECHNICAL_BASELINE.md`](research/ACOLITE_TECHNICAL_BASELINE.md) | Verificada por un agente independiente |
| 4 | Entrevista de ingeniería | [`PLAN.md`](PLAN.md) § Brief | **LOCKED** — 18 decisiones, 0 diferidas |
| 5 | Investigación de publicación | `.work/oceanos-pr-mvp/publication-architecture/` | Compuertas limpias, 6 sidecars |
| 6 | Plan de implementación | `PLAN.md` § Plan | **Pendiente** — siguiente paso |

La evidencia cruda de ambas investigaciones (2 índices, 17 sidecars, 2 ledgers de cobertura) vive en `.work/`, sin versionar.

---

## 2. El sistema hoy

El pipeline corre **descubrimiento → catálogo STAC local → descarga verificada → normalización espacial**, y se detiene. Cinco bandas reproyectadas a una grilla métrica común como Float32 con nodata NaN, conteniendo **valores de muestra crudos, no reflectancia**.

~1 400 líneas de código, 137 tests que pasan, y una disciplina de ingeniería consistente: publicación atómica con rollback, descargas verificadas con SHA-256, artefactos versionados, y una negativa sistemática a inventar valores ausentes.

No hay corrección atmosférica, ni enmascarado de calidad, ni producto espectral, ni API, ni forma de mirar nada.

**Defectos menores pendientes:** el script de consola `oceanospr` está roto, hay un `nasa_oceanos_pr.egg-info/` obsoleto sin ignorar, y `pandas` está declarado pero no se importa en ninguna parte.

---

## 3. Las 18 decisiones cerradas

| # | Decisión |
|---|---|
| Q1 | ACOLITE se invoca como **subproceso** con archivo de settings, un proceso por escena |
| Q2 | **OCEANOS adquiere** el SAFE; descubrimiento reorientado a CDSE OData para L1C completo |
| Q3 | La grilla de la Fase 5 **sobrevive**, reducida a paso de grilla de entrega *posterior* a ACOLITE |
| Q4 | Productos: `rhow_*`, `Rrs_*`, `rhorc_*`, `tur_nechad2016`, `spm_nechad2016`, `chl_re_gons740`, `fai`, `fait`, `ndvi` |
| Q5 | Dos compuertas de usabilidad: nubosidad de escena en descubrimiento + `l2_flags == 0` por píxel |
| Q6 | Trabajo en `master`, creada sobre `acc6072`; Fase 6/7 abandonadas e inalcanzables |
| Q7 | Tierra/mar por **máscara geométrica GSHHG**, desacoplada del umbral SWIR (que sube a `0.05`) |
| Q8 | Buffer costero **en capas**: excluir ~100–200 m del análisis, conservar la costa en visualización |
| Q9 | `dsf_aot_estimate=fixed` — el AOI es demasiado pequeño para el DSF por teselas |
| Q10 | Descartar el SAFE tras procesar; `l1r_delete_netcdf=True`; conservar L2R + L2W + manifiestos |
| Q11 | `merge_tiles=True` con `limit`; sin mosaicado externo |
| Q12 | Revisar el límite del AOI antes del backfill; ajustarlo a 19QFV **si es científicamente defendible** |
| Q13 | Corrección de glint **desactivada**; registrar el ángulo como metadato |
| Q14 | Pedir `rhorc_*` para mantener calculable el FAI nativo de la literatura |
| Q15 | Añadir `version=20260421.0` al `config.txt` de despliegue + registrar el SHA del commit |
| Q16 | **NetCDF archivo + COG publicación**; `l2_flags` en **COG separado** con overviews `MODE`/`NEAREST` |
| Q17 | **STAC 1.1.0 estático**; `classification:bitfields` + `processing:`; **sin servidor de teselas** |
| Q18 | Settings resueltos vía enlace `processing-software` + asset de metadatos *(rodeo aceptado)* |

---

## 4. Hechos establecidos sobre ACOLITE

Dieciocho cerrados, todos con fuente primaria y verificación independiente. Los que cambian el diseño:

**La adquisición actual es incompatible por tres motivos simultáneos.** Nivel equivocado (L2A se rechaza en duro), empaquetado equivocado (bandas COG sueltas, no un `.SAFE`), e insumos destruidos (el reproyectado previo descarta geometría y calibración). **Se reemplaza, no se adapta.** Y ACOLITE necesita ocho bandas que el conjunto actual omite.

**ACOLITE ya hace casi todo lo que construyó la Fase 5** — recorte, remuestreo, reproyección, enmascarado, y todos los algoritmos. Duplicarlo aguas arriba es, en el mejor caso, trabajo repetido.

**Productos calibrados para Sentinel-2**: `tur_nechad2016`, `spm_nechad2016`, `chl_oc2`/`chl_oc3`, `chl_re_bramich`, y las variantes red-edge `740`. **`tur_dogliotti2015` usa calibración MODIS** por advertencia del propio manual — es el que un pipeline costero adoptaría por defecto, y no está calibrado para tu sensor.

**Para sargazo, ACOLITE da índices, no detección.** `fai`, `afai` y `fait` son nativos pero **sin enmascarar** — se calculan sobre tierra y nube por igual. El método publicado de Wang & Hu exige clasificación, **desmezclado lineal** y agregación *encima* del índice. Nada de eso existe.

**Licencia GPLv3.** Uso interno sin distribución no genera obligación de código fuente. Invocar como proceso separado es menor acoplamiento que importar.

---

## 5. Hechos establecidos sobre publicación

**El campo de bits no puede viajar como una banda más.** GDAL pone `OVERVIEW_RESAMPLING` en CUBIC por defecto, que fabrica combinaciones de flags que nunca ocurrieron. Y hay una razón estructural más fuerte: un COG lleva **un** predictor y **un** método de remuestreo por archivo, y los correctos para Float32 (`PREDICTOR=3`, cúbico) y para un bitfield int32 (`PREDICTOR=2`, modo) **son incompatibles**.

**Invariante derivado: los overviews son solo para mostrar; toda estadística lee resolución completa.** Porque el modo pierde las clases raras, que es justo para lo que existe una banda de flags.

**Leer rásters por petición para una serie temporal está ~2400× mal dimensionado.** El coste es estructural: descomprimes una tesela entera para leer un píxel. Un servidor de teselas más rápido no lo arregla — las series se pre-extraen.

**Tres herramientas populares, descartadas con razón:** **Zarr** (su modelo de muchos archivos pequeños no aporta nada en disco local único), **GeoZarr** (no existe como especificación publicada), y **un servidor de teselas en el MVP** (geotiff.js lee los COG directamente).

**Landsat no cierra ninguna puerta.** Collection 2 ya se entrega como COG con banda QA empaquetada, ya se publica por STAC, y es el ejemplo canónico de la extensión recomendada para `l2_flags`.

---

## 6. Verificado ejecutando, no leyendo

Esto distingue lo comprobado de lo documentado:

| Hallazgo | Cómo se comprobó |
|---|---|
| ACOLITE **devuelve exit 0 al fallar** | Se ejecutó con tres clases de entrada inválida; los tres exit 0 |
| Datos auxiliares llegan con **~40–60 días de retraso** | 2026-08-04 falla, 2026-07-10 y 2026-06-15 funcionan |
| `GMAO_IT_MET` resuelve esa latencia | Devuelve valores plausibles para la fecha que fallaba |
| Las credenciales EarthData **autentican** | Descarga real con valores coherentes para el Caribe |
| El **AOI cruza tiles y los datos están incompletos** | Bounds de los rásters descargados reproyectados a EPSG:4326 |
| Los overviews de flags usan **MODE** | Lectura por rangos HTTP del `SCL.tif` real de Element84 para **19QFV, tu propio tile**: 52/52 bloques |
| Series temporales: **2606 ms vs 1.09 ms** | Medido en esta clase de máquina, 500 escenas |
| ACOLITE **no reporta su versión** desde un clon | Reporta `Generic GitHub Clone c2026-09-11T19:09:09` |

---

## 7. Correcciones hechas sobre el camino

Cosas que resultaron distintas de lo que se asumió al principio:

- **Existían Fase 6 y 7 completas** en `master`, con QA por SCL e índices propios. Las rechazaste por no verificadas; hoy están abandonadas e inalcanzables por decisión explícita.
- **Las variables `EARTHDATA_*`** se evaluaron como configuración muerta a eliminar. Están muertas *como estaban escritas*, pero ACOLITE sí requiere esas credenciales — la recomendación cambió de "eliminar" a "renombrar y conectar".
- **La métrica M3 del PRD era inalcanzable.** ≤7 días desde adquisición hasta visor no se puede cumplir con datos auxiliares que tardan mes y medio. Resuelto con `ancillary_type` según edad de escena.
- **Cuatro errores en la investigación**, detectados por el verificador independiente: conteo de commits (89→88), la constante de máscara es 47 y no 15, un rango de líneas, y una fila de checklist sobremarcada. Corregidos antes de escribir el informe.
- **La procedencia de AFAI** descansaba solo en un string del código. Cerrada con tres fuentes ajenas a RBINS.

---

## 8. Entorno operativo

| Componente | Ubicación | Estado |
|---|---|---|
| Clon ACOLITE (`20260421.0` es el pin candidato) | `~/acolite` | Funcional |
| Entorno conda (gdal 3.13.3, netCDF4, zarr) | `~/micromamba/envs/acolite` | Funcional |
| Credenciales | `~/.netrc`, permisos `600` | **Verificadas** |
| LUTs de corrección atmosférica | `~/acolite/data/LUT` | **Vacío — falta pre-descargar** |
| GSHHG (línea de costa) | `external_dir` | **Falta descargar** |

`pyproject.toml` y `uv.lock` intactos: instalar ACOLITE como dependencia del proyecto es una decisión de arquitectura que sigue sin tomarse.

---

## 9. Lo que sigue abierto

**Decisión tuya, no técnica:**

- **Q12 quedó condicional.** ¿Necesita La Parguera científicamente la franja oriental que cae fuera de 19QFV? Ajustar el AOI a un solo tile reduce descarga, cómputo y complejidad **a un tercio** en tu máquina. Mantener tres tiles es defendible si la ciencia lo exige. **Hay que decidirlo antes del backfill.**

**Salvedades honestas de la investigación** — conviene conocerlas antes de tratar todo como consenso:

- La hipótesis "convertir a COG" quedó **parcialmente falsada**: NASA y Development Seed sirven NetCDF directamente vía `titiler.xarray`. Aquí COG se justifica por la lectura en navegador y el tamaño de tus productos, **no por precedente de industria**.
- El precedente NASA de doble formato es **MEDIUM**, no HIGH — no se halló documento de operador que lo declare.
- **deck.gl y MapLibre no se investigaron.** Si el visor va a usar MapLibre, eso queda abierto.
- Once incógnitas menores en §14 del informe técnico, cada una con impacto calificado.

**Pendiente operativo:**

- Pre-descargar LUTs y GSHHG.
- Cuatro documentos de este tema sin commitear.

---

## 10. Siguiente paso

`/planning:plan`. Tiene todo lo que necesita: producto definido, estado actual evaluado, línea base de ACOLITE verificada, contrato de ingeniería cerrado con 18 decisiones y cero preguntas diferidas, e investigación de publicación validada.

El orden de despliegue que fija el PRD §11 sigue vigente, y su paso 3 es el que más información nueva aporta: **un backfill acotado a una temporada** mide la escasez real por nubosidad *antes* de construir el visor encima.
