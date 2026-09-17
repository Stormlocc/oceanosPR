# Scripts

Puntos de entrada operacionales. Todos son Python; el repositorio no contiene bash.
Las rutas, el tag y el commit de ACOLITE se leen de `configs/mvp.yaml` (`--config` lo cambia)
y nunca se redeclaran aquí.

| Script | Para qué | Uso |
| --- | --- | --- |
| `acolite_env.py` | Instalación fijada de ACOLITE: pin, LUT, credenciales y entorno | `--check` (por defecto, solo lectura), `--install`, `--dry-run` |
| `fetch_reference_data.py` | Tiles CUDEM propiedad de OCEANOS, con tamaño y SHA-256 fijados | `bathymetry` o `all`, con `--check` |
| `probe_run_one.py` | Probe real: una observación de extremo a extremo | `--scene-key`, `--scenes`, `--force-reprocess` |
| `verify_release.py` | Verifica una release publicada, sin red | `RELEASE_DIR` |
| `make_acolite_fixtures.py` | Generó los fixtures offline desde las corridas reales de la Fase 1; herramienta de un solo uso | se ejecuta con el intérprete de ACOLITE |

```bash
uv run python scripts/acolite_env.py --check
uv run python scripts/fetch_reference_data.py all --check
uv run python scripts/probe_run_one.py --force-reprocess
```

Los cuatro primeros se ejecutan con el entorno del proyecto (`uv run python ...`).
`make_acolite_fixtures.py` es la excepción: corre dentro del entorno de ACOLITE y solo usa `netCDF4`.

`verify_release.py` reimplementa a propósito su propio SHA-256 y sus propias comprobaciones en
vez de reutilizar `oceanos.storage`: verifica una release sin confiar en la librería que la
escribió. `probe_run_one.py` lee la escena a correr de `.work/oceanos-pr-mvp/spikes/scenes.json`,
un artefacto de la Fase 1 que no se versiona; con `--scenes` se le pasa otro archivo.
