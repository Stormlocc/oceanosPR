# Arquitectura

> **Alcance.** Este documento describe la arquitectura **vigente** (MVP ACOLITE, fases 0–3
> completas). Reescrito el 2026-09-17 en la limpieza integral; sustituye a la versión que describía
> el linaje Fase 1–5 (descubrimiento L2A en Element84, bandas sueltas, `normalize_scene`), retirado
> el 2026-09-16 y ya inexistente en el código.
>
> Las fuentes autoritativas siguen siendo `docs/topics/oceanos-pr-mvp/PLAN.md` (fases y criterios de
> aceptación), `design/contracts.md` (contratos), `design/topology.md` (módulos y almacenamiento) y
> `IMPLEMENTATION_HANDOFF.md` (estado y próxima acción). Este archivo es el mapa de lectura.

## 1. La tubería, de extremo a extremo

```text
AOI (GeoJSON)
  └─> grid build ............ DeliveryGrid fija: EPSG:32619, 10 m, anclada a múltiplos de 10 m
       └─> scenes search .... CdseODataProvider (OData anónimo) -> catálogo STAC local
            └─> run-one ...... una observación = AOI × overpass, bajo el WriterLock
                 A1 selección de cobertura mínima de teselas
                 A2 adquisición íntegra del SAFE (MD5 del proveedor + SHA-256 + miembros del ZIP)
                 P1 preflight: re-verificación del SAFE y sonda de la instalación fijada
                 P2 ACOLITE como subproceso, en su propio grupo de procesos
                 P3 verificación: artefactos + log + atributos NetCDF, nunca el código de salida
                 P4 archivo atómico e inmutable (la verdad del procesamiento)
                 P5 conformidad a la grilla: copia sin remuestrear
                 P6 calidad: predicado de píxel válido y compuertas de observación
                 P7 empaquetado: COG, color verdadero, quality.json, series.json, provenance.json
                 P8 publicación: release inmutable + Item STAC + ledger de eventos
```

`pipeline republish` vuelve a entrar en P5 desde el archivo, sin red y sin ACOLITE, cuando cambia
el perfil aguas abajo (productos, calidad, máscaras o publicación).

## 2. Quién es dueño de qué

| Responsabilidad | Dueño |
| --- | --- |
| Corrección atmosférica, recorte, remuestreo, algoritmos de producto, `l2_flags` | **ACOLITE** (fijado, subproceso) |
| Integridad de la adquisición, verificación de la corrida, archivo | OCEANOS |
| Conformidad a la grilla de entrega (`GridSpec` / `assert_aligned`) | OCEANOS |
| Máscara de tierra y máscara de análisis | OCEANOS (CUDEM, enmienda DA-1) |
| Veredicto de calidad y visibilidad de la release | OCEANOS |
| Releases inmutables, procedencia, STAC estático, índice | OCEANOS |

ACOLITE **no es una dependencia Python** del proyecto (Q1, GPLv3 §10.3): vive en su propio clon y
entorno micromamba. `pyproject.toml` no lo menciona.

**Tres hechos sobre ACOLITE que la arquitectura da por sentados:**

1. **Sale con código 0 cuando falla.** El éxito se afirma desde los archivos de salida y un barrido
   del log (`RunVerifier`), nunca desde el código de salida.
2. `l2w_parameters` debe fijarse explícitamente o no se escribe ningún L2W.
3. En el pin nunca aplica su máscara de tierra GSHHG, así que la máscara la aplica OCEANOS. Desde la
   enmienda DA-1 esa máscara se deriva de la batimetría CUDEM (elevación > 0 m), no de GSHHG, que se
   retiró del repositorio el 2026-09-17.

## 3. Módulos

`design/topology.md` §1 tiene la tabla completa con sus reglas de importación. En resumen:

| Paquete | Qué hace |
| --- | --- |
| `oceanos.domain` | Identificadores, modelos estrictos, perfiles, taxonomía de fallos. **Sin I/O y sin importar nada de `oceanos`.** |
| `oceanos.config` | Settings tipados: YAML + variables de entorno, resolución de rutas. Cargar no crea directorios ni hace red. |
| `oceanos.aoi` | Carga, valida, reproyecta y serializa AOIs; deriva el `AoiId`. |
| `oceanos.storage` | Layout de tiers, `file_sha256`/`artifact_ref`, commit atómico con rollback, `WriterLock`. |
| `oceanos.catalog` | Descubrimiento L1C (`CdseODataProvider`) y catálogo STAC local. **Todo el vocabulario STAC queda aquí.** |
| `oceanos.ingestion` | Adquisición verificada del SAFE completo: token CDSE, MD5, SHA-256, miembros del ZIP. |
| `oceanos.acolite` | **El único módulo que conoce el vocabulario de ACOLITE**: settings, sonda, runner, verificación, `FlagSpec`. |
| `oceanos.processing` | `grid`, `normalize` (conformidad), `quality` (núcleo puro), `masks`. |
| `oceanos.timeseries` | Estadísticas por zona, agregación pura, sin I/O. |
| `oceanos.publishing` | COG con perfiles explícitos, color verdadero, Item STAC, commit de release. |
| `oceanos.pipeline` | Orquestación: plan, secuencia de etapas, ledgers, re-publicación. |
| `oceanos.api` | Frontera de lectura, vacía hasta la Fase 5. |
| `oceanos.__main__` | La CLI: el **único** orquestador. |

Cuatro reglas las verifica `tests/test_architecture.py`, no la buena voluntad:

- **A1.** `acolite` y `processing` no se importan entre sí.
- **A2.** `api` nunca importa `pipeline`, `acolite`, `publishing` ni el escritor del índice.
- **A3.** `domain` no importa nada de `oceanos`.
- **A4.** Ningún módulo fuera de `acolite` menciona un nombre de variable, clave de settings o
  cadena de log de ACOLITE. El `ProductSpec.variable_pattern` es dato, y se resuelve dentro de
  `acolite`.

## 4. Patrones que toda etapa nueva reutiliza

- **Frontera de adaptador.** El vocabulario del proveedor se queda en el adaptador; aguas abajo solo
  viaja `SceneMetadata`. `oceanos.acolite` confina el de ACOLITE igual.
- **Staging → verificar → `os.replace` atómico → rollback.** La forma de `conform_layer` y de
  `publish_release`. Una corrida fallida deja la salida anterior intacta.
- **Alineación por igualdad exacta.** `GridSpec` se valida a sí misma y `assert_aligned` vuelve a
  leer cada ráster contra la grilla antes de publicar.
- **Modelos estrictos.** `extra="forbid"`, `allow_inf_nan=False`, `schema_version` en el JSON que
  cruza etapas. Un valor desconocido se queda en `None`; nunca se inventa.
- **Un solo escritor.** `WriterLock` se sostiene a lo largo de P1–P8, con recuperación del tenedor
  obsoleto.
- **Dependencia por artefactos.** Cada etapa depende de los **archivos en disco** de la anterior,
  nunca de sus rutas de código; `normalize` vuelve a comprobar cada SHA-256. Ninguna etapa
  regenera un insumo que falta: falla.

## 5. Almacenamiento

El layout completo está en `design/topology.md` §2. Los tiers viven bajo `data/` (nunca versionado)
y `work/`, `archive/` y `products/` deben compartir sistema de archivos para que cada commit sea un
`os.replace` atómico.

| Tier | Mutabilidad | Verdad o derivado |
| --- | --- | --- |
| `raw/` | reemplazable | verdad hasta que se archiva |
| `work/` | scratch | — |
| `archive/` | **inmutable** | **verdad del procesamiento** |
| `products/…/releases/` | **inmutable** | verdad de la publicación |
| `products/…/stac/` | reemplazo atómico | derivado de las releases |
| `state/` | append-only / transaccional | ledgers = fuente de reconstrucción |
| `superseded/` | no se sirve | release anterior |

## 6. Cómo se prueba

La suite por defecto es **offline y sin ACOLITE**: 183 tests. Los adaptadores de red se falsean con
`httpx.MockTransport`, los tests de catálogo y adquisición bloquean sockets, y ACOLITE se sustituye
por `FakeAcoliteRunner`, que copia fixtures **reales y recortados** de la Fase 1
(`tests/fixtures/acolite/`, < 10 MB, sin SAFEs ni credenciales).

Dos suites son opt-in y no corren por defecto:

```bash
uv run pytest --run-integration tests/integration    # catálogo CDSE real
uv run pytest --run-acolite tests/acolite_golden     # ACOLITE local fijado
```

Y hay dos verificaciones operacionales fuera de pytest: `scripts/verify_release.py` (valida una
release publicada sin red, y **deliberadamente no reutiliza** `oceanos.storage` para no confiar en
la librería que la escribió) y `scripts/probe_run_one.py` (una observación real de extremo a
extremo).
