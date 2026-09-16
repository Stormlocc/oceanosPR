# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Claude Code — OCEANOS PR

OCEANOS PR is a Python 3.11 Sentinel-2 coastal water-quality pipeline for La Parguera, Puerto Rico.
The work currently under way is the **ACOLITE MVP**, defined in `docs/topics/oceanos-pr-mvp/PLAN.md`
(status: APPROVED FOR IMPLEMENTATION, rev 4).

## Role

Claude Code is the primary agent for:

* requirements and design review;
* investigation and technical research;
* PLAN review when implementation evidence invalidates an approved assumption;
* architecture and implementation review.

Codex is normally the primary implementation, testing and debugging agent.

Claude Code may implement an active PLAN unit only when the user explicitly hands that unit to
Claude. When that happens, follow the PLAN and the workflow below exactly, and do not redesign the
system.

## Session startup

At the beginning of work on the OCEANOS PR MVP:

1. Read `docs/topics/oceanos-pr-mvp/IMPLEMENTATION_HANDOFF.md`. It exists and is the live record:
   its top section states the current state and the exact next action. The copy at the repository
   root is a redirect only.
2. Read the active portion of `docs/topics/oceanos-pr-mvp/PLAN.md`: the first phase not tagged
   `[DONE]`, plus "Handoff to implementation".
3. Inspect `git status`, the current branch and recent commits.
4. Read only the design sections referenced by the active PLAN task
   (`docs/topics/oceanos-pr-mvp/design/`).
5. For domain-sensitive work, read `.agents/skills/oceanos-domain/SKILL.md` and only the references
   relevant to the task.
6. Verify that repository reality agrees with the handoff before changing anything.

Do not infer completed work from chat history. Git, PLAN phase tags, tests and
`IMPLEMENTATION_HANDOFF.md` are the durable execution record.

## Commands

The project uses `uv`. Prefix commands with `uv run` unless the venv is active.

```bash
uv sync                                                   # install deps from uv.lock
uv run pytest -q                                          # full offline suite (must stay green every phase)
uv run pytest tests/test_conform.py -q                    # one file
uv run pytest tests/test_fetch.py::test_name -q           # one test
uv run pytest --run-integration tests/integration -q      # opt-in live network tests
uv run python -m oceanos aoi info --config configs/mvp.yaml   # CLI (argparse, src/oceanos/__main__.py)
```

- **Console script.** `oceanospr` works since PLAN Phase 0; `python -m oceanos` is equivalent.
- **Tooling.** `ruff` and `mypy` are configured (Phase 0) and the `--run-acolite` opt-in golden
  test exists (Phase 2.2). There is still no CI.
- **Offline hooks.** `tests/conftest.py` skips collecting `tests/integration` unless
  `--run-integration` is given. Catalog, fetch and normalize tests block sockets with `no_network`
  fixtures and fake HTTP with `httpx.MockTransport`.
- **ACOLITE.** It is **not** a Python dependency. It is an external clone at `~/acolite`, run with
  the micromamba env `~/micromamba/envs/acolite` as
  `python launch_acolite.py --cli --settings=<file>`. The pin is tag `20260421.0`, commit
  `f73cbe73887c2b114d9d3c70865effee73871525`. Phase 1 replaced the shallow clone: the local
  checkout sits at the pin and `scripts/acolite_env.py --check` verifies it.
- **Credentials.** They live in `~/.netrc` (machines `earthdata`, `cdse`) and are never put in config.

## Architecture (current code)

> **Note (2026-09-16).** The Fase 1–5 legacy was retired: `Sentinel2Provider` (the Element84/L2A
> discovery path), `normalize_band` and `build_grid` no longer exist, and `catalog/` is no longer
> versioned. Discovery is `CdseODataProvider`; conformance is `conform_layer`. See PLAN.md,
> "Resolved after lock (legacy retirement pulled forward + study pause, 2026-09-16)".

The pipeline today is **AOI → STAC discovery (Element84, L2A) → local STAC catalog → verified band
download → spatial normalization**, and it stops there. `docs/architecture.md` (Spanish) and the
README "Fase N" sections describe each stage.

**The CLI is the only orchestrator.** `__main__.py` wires config → AOI → provider → catalog → stage.
Each stage depends on the previous stage's **on-disk artifacts**, never on its code paths:

- `fetch` requires a cataloged scene;
- `normalize` requires a verified download manifest and re-checks every SHA-256.

No stage re-fetches or regenerates a missing upstream artifact; it errors instead.

House patterns every new stage must reuse:

- **Adapter boundary.** Provider vocabulary stays in the adapter: STAC property names live only in
  `catalog/cdse.py` and `catalog/local.py`, and downstream code uses `SceneMetadata`. The new
  `oceanos.acolite` package is meant to confine ACOLITE vocabulary the same way (import/literal
  rules A1–A4 in `design/topology.md`).
- **Staging → verify → atomic `os.replace` → rollback.** The shape of `conform_layer`
  (`processing/normalize.py`) and `publish_release` (`publishing/release.py`). A failed run leaves
  the previous output intact.
- **Exact-equality alignment.** `GridSpec` (`processing/grid.py`) validates itself, and
  `assert_aligned` re-reads every raster against the grid before publishing.
- **Strict models.** Pydantic models set `extra="forbid"` and `allow_inf_nan=False`. Cross-stage
  JSON carries `schema_version`. Unknown values stay `None` and are never invented.
- **Config precedence.** `OceanosSettings` resolves paths relative to `data_root`. Environment
  variables (`OCEANOS_`, nested with `__`) override YAML. Loading config creates no directories
  and makes no network calls.
- **Single writer.** Enforced since Phase 2.2 by `WriterLock` (`storage.py`), held across P1-P8 of
  `pipeline run-one`, with stale-holder recovery.

## Where the MVP takes the architecture

These are settled facts. Do not re-litigate them; the evidence is in `docs/topics/oceanos-pr-mvp/`.

- **Input.** Complete Sentinel-2 **L1C SAFE** from CDSE OData. L2A and loose band files are
  rejected by ACOLITE. For the current AOI, tile `19QGV` alone covers every overpass.
- **ACOLITE role.** It runs as a **subprocess** and owns atmospheric correction, clipping and
  resampling, and `l2_flags`.
  - **It exits 0 on failure.** Success is asserted from output files plus a log scan, never from
    the exit code.
  - `l2w_parameters` must be set explicitly, or no L2W file is written.
  - The resolved settings file is `acolite_run_<id>_l2r_settings.txt`.
  - At the pin it never applies its GSHHG land mask, so OCEANOS applies the land mask.
- **OCEANOS role.** It owns everything around ACOLITE:
  - acquisition integrity, run verification, archive;
  - delivery-grid conformance (Fase 5 `GridSpec`/`assert_aligned` survive);
  - quality verdicts;
  - immutable releases with provenance, a static STAC catalog, a SQLite index;
  - a read-only API and a static viewer.
- **Identity.** `RunKey` depends only on what changes ACOLITE's output (`AcoliteProfile`). Quality,
  product or publication changes create a new `ReleaseId` from the archive, without rerunning
  ACOLITE.
- **Rejected work.** The Fase 6/7 commits (SCL QA, in-house NDVI/FAI/RGB) are rejected and
  unreachable. Never revive them.

## Git and branch rules

- **Branch.** Implementation happens on `feat/oceanos-pr-mvp`, created from `master`. It merges back
  into `master` only in PLAN Phase 7, behind a user gate. Never commit implementation directly to
  `master`.
- **Commits.** One commit per PLAN (sub-)phase, message `Fase N.M: <name>`, with the phase tag
  updated (`[TODO]` → `[DOING]` → `[DONE]`) in the same commit. Each phase also adds a Spanish
  "Fase N" section to `README.md`.
- **Never commit** `.agents/` (Codex's project-local skills, deliberately untracked), `data/`, or
  `.work/`.

## Context continuity

When context is becoming constrained:

* do not start another PLAN unit;
* finish the current atomic operation when safe;
* run the most relevant verification available;
* update `IMPLEMENTATION_HANDOFF.md`;
* record the current branch and HEAD;
* record all uncommitted files;
* record the last commands/tests run and their results;
* record the exact next action;
* never mark a PLAN unit `[DONE]` unless its required sanity checks passed.

If work is incomplete, leave it explicitly incomplete. Do not create a misleading completion commit
simply to obtain a clean working tree.

## Conflict rule

If repository evidence contradicts PLAN.md, an approved design decision, the pinned ACOLITE
behaviour, or a domain invariant, stop the affected implementation unit and report the concrete
evidence. Mid-flight plan changes go through `/planning:plan review`. Do not silently alter
architecture or acceptance criteria.
