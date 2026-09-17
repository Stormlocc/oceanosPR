# AGENTS.md — oceanosPR

## Scope

These instructions apply to the entire repository.

OCEANOS PR implementation is driven by three separate layers:

1. `docs/topics/oceanos-pr-mvp/PLAN.md`

   * what to implement;
   * implementation order;
   * files;
   * acceptance criteria;
   * tests and verification.

2. `.agents/skills/oceanos-domain/`

   * stable domain terminology;
   * geospatial invariants;
   * provenance;
   * ACOLITE responsibility boundaries;
   * raster and quality semantics.

3. This `AGENTS.md`

   * how Codex works;
   * implementation discipline;
   * testing workflow;
   * Git/checkpoint rules;
   * stop conditions.

Do not duplicate responsibilities between these layers.

## Source of truth

Before modifying code, read the active task in:

`docs/topics/oceanos-pr-mvp/PLAN.md`

Then read only the design sections and domain references required by that task.

Do not reinterpret, expand or silently redesign an approved PLAN decision.

## Implementation unit

Implement exactly one implementable PLAN unit at a time.

The normal workflow is:

PLAN task
→ inspect current implementation
→ inspect consumers
→ identify relevant tests
→ add or adjust a failing test when applicable
→ demonstrate the expected failure
→ implement the minimum required change
→ run targeted tests
→ run integration or runtime verification required by the PLAN
→ run baseline verification
→ inspect the diff
→ checkpoint/commit
→ stop before starting the next unit

Do not execute the entire PLAN in one pass.

## Reading discipline

Before changing a public or migrated surface:

* inspect its implementation;
* grep all consumers;
* inspect relevant tests;
* inspect configuration consumers;
* read the PLAN references for that task;
* consult `oceanos-domain` for stable domain invariants.

Do not load unrelated design documents merely because they exist.

## Minimum-change rule

Prefer the smallest change that satisfies:

* the active PLAN task;
* its acceptance criteria;
* its tests;
* the relevant domain invariants.

Do not implement future phases early.

Do not perform opportunistic refactors unrelated to the active task.

## Conflict and stop rule

STOP the active task if implementation reveals a contradiction between:

* `PLAN.md`;
* an approved design decision;
* `oceanos-domain`;
* verified ACOLITE behavior at the pinned version;
* or repository reality in a way that invalidates the planned change.

When stopping:

1. do not redesign the system;
2. do not weaken an acceptance criterion;
3. do not invent a new rule;
4. capture concrete evidence;
5. identify the conflicting files/sections;
6. report the smallest decision that must return to planning.

A contradiction affecting an acceptance criterion or locked decision must return to Claude Code for plan review.

## Testing discipline

The default test suite must remain offline and must not require ACOLITE or network access.

Run targeted tests before the complete suite.

For every completed phase, at minimum run:

```bash
uv run pytest -q
uv run ruff check src tests scripts
```

Use the PLAN-defined opt-in suites only when required:

```bash
uv run pytest --run-integration ...
uv run pytest --run-acolite ...
```

`mypy` strict applies only to the new-package scope defined by the PLAN.

Never remove, skip, weaken or rewrite a valid test merely to make an implementation pass unless the active PLAN task explicitly changes that contract.

## Red-Green-Refactor

When the task changes behavior:

1. add or adjust the relevant test;
2. run it and demonstrate the expected failure;
3. implement the minimum change;
4. rerun the targeted test;
5. refactor only after green;
6. run the required wider verification.

When a task is purely structural and cannot meaningfully begin with a failing behavioral test, explain why before changing it.

## External systems

Never print, persist in source control, or copy credentials into project files.

EarthData and CDSE credentials are runtime state outside the repository.

Network calls, live CDSE tests and real ACOLITE runs occur only when the active PLAN verification explicitly requires them.

Never introduce network access into the default test suite.

## ACOLITE

Do not import ACOLITE as a production Python library.

Respect the ACOLITE/OCEANOS responsibility boundary defined by `oceanos-domain` and the approved design.

Do not infer undocumented ACOLITE behavior.

If observed behavior at the pinned ACOLITE version contradicts the PLAN or approved research baseline, stop and report evidence.

## Git

Follow the branch strategy in the approved PLAN.

Before modifying anything, inspect:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
```

Protect unrelated user changes.

Never discard or overwrite unrelated work.

One behavioral implementation unit should produce one coherent checkpoint/commit unless the PLAN requires otherwise.

Keep structural formatting changes separate from behavioral changes.

Do not merge into `master` until the Phase 7 user gate.

`.agents/` must remain untracked while the active PLAN requires it.

## PLAN task status

When implementation of a PLAN unit begins, mark only that unit `[DOING]` if the PLAN requires status tracking.

Mark it `[DONE]` only after all required sanity checks pass.

Do not mark a task complete because implementation merely appears correct.

## Scope prohibitions

Do not:

* redesign the architecture silently;
* revive the retired L2A workflow unless the PLAN is formally revised;
* invent scientific thresholds or defaults;
* invent ACOLITE settings;
* implement future PLAN phases early;
* expand the MVP scope;
* change locked Brief decisions;
* change acceptance criteria without plan review;
* add external services not authorized by the PLAN.

## End-of-unit report

At the end of each implementation unit report:

1. files changed;
2. behavior changed;
3. tests added or changed;
4. targeted test results;
5. baseline verification results;
6. unresolved risks or contradictions;
7. current Git status;
8. recommended next PLAN unit.

Then stop.
