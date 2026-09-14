# OCEANOS PR MVP — Implementation Handoff

## Completed boundary

Phase 0, **Branch, hygiene, tooling**, is complete on
`feat/oceanos-pr-mvp`. The work establishes the local tooling and the
architecture guardrails that every later MVP phase must retain.

## Phase 0 deliverables

- `oceanospr` resolves to `oceanos.__main__:main`.
- `pandas` is removed; the lockfile no longer resolves it.
- The development group contains Ruff and mypy. Ruff targets Python 3.11;
  mypy is strict when invoked against the new packages introduced by later
  phases.
- `tests/test_architecture.py` enforces topology rules A1–A4 only. It does
  not enforce the broader may-import matrix and preserves the temporary
  `processing/normalize.py` allowance stated in the PLAN.
- The obsolete ignored `src/nasa_oceanos_pr.egg-info/` output is removed.
- `.env.example` already documents `~/.netrc` credentials for `earthdata` and
  `cdse`; no credential material is tracked.

## Verification record

Run after the Phase 0 changes:

```text
uv run pytest -q
uv run ruff check src tests
uv run oceanospr --help
test ! -d src/nasa_oceanos_pr.egg-info
grep -c '"pandas' pyproject.toml
git branch --show-current
git ls-files .agents | wc -l
```

The default tests remain offline and do not require ACOLITE or network access.

## Protected workspace state

Do not stage, alter, or discard the existing `.gitignore` newline-only change,
untracked `AGENTS.md`, or untracked `.agents/` tree. `.agents/` must remain
untracked through the active PLAN.

## Next authorized unit

Phase 1 is the next unit: establish and verify the pinned ACOLITE environment
and run the feasibility spikes. Do not begin it until Phase 0's checkpoint is
reviewed and committed according to the PLAN.
