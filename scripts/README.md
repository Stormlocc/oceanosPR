# Scripts

Puntos de entrada operacionales. Todos son Python; el repositorio no contiene bash.
Las rutas, el tag y el commit de ACOLITE se leen de `configs/mvp.yaml` (`--config` lo cambia)
y nunca se redeclaran aquí.

| Script | Para qué | Uso |
| --- | --- | --- |
| `acolite_env.py` | Instalación fijada de ACOLITE: pin, LUT, credenciales y entorno | `--check` (por defecto, solo lectura), `--install`, `--dry-run` |
| `fetch_reference_data.py` | Datos de referencia propiedad de OCEANOS, con tamaño y SHA-256 fijados | `gshhg`, `bathymetry` o `all`, con `--check` |
| `probe_run_one.py` | Probe real: una observación de extremo a extremo | `--scene-key`, `--scenes`, `--force-reprocess` |
| `verify_release.py` | Verifica una release publicada, sin red | `RELEASE_DIR` |
| `make_acolite_fixtures.py` | Genera los fixtures offline desde las corridas reales de `.work/` | se ejecuta con el intérprete de ACOLITE |

```bash
uv run python scripts/acolite_env.py --check
uv run python scripts/fetch_reference_data.py all --check
uv run python scripts/probe_run_one.py --force-reprocess
```

Los cuatro primeros se ejecutan con el entorno del proyecto (`uv run python ...`).
`make_acolite_fixtures.py` es la excepción: corre dentro del entorno de ACOLITE y solo usa `netCDF4`.
