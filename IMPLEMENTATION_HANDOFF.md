# OCEANOS PR MVP — Implementation Handoff

## Completed boundary

Phase 0, **Branch, hygiene, tooling**, is complete on
`feat/oceanos-pr-mvp`. Phase 1, **ACOLITE environment and feasibility spikes**,
is implemented and verified. Phase 2 has not begun.

## Phase 1 completed work

- ACOLITE is pinned at `20260421.0` / `f73cbe73887c2b114d9d3c70865effee73871525`;
  its environment and LUT checks pass.
- GSHHG 2.3.7 full-resolution level-1 land polygons are fetched and verified
  against the accepted pinned SHA-256.
- The live discovery, complete SAFE acquisitions and valid A/A′/B/C/D/E/F/G,
  D2 and B2 runs are retained under `.work/oceanos-pr-mvp/spikes/`.
- V1–V8 outcomes and supporting measurements are recorded in
  `design/design-threads.md`.
- The V8 amendment activates residual glint correction, makes SWIR bit 0
  informational and defines fixture validity from GSHHG water outside the
  coastal buffer, bits 1/2/3 and finite product values.
- `scripts/make_acolite_fixtures.py` generates the offline fixtures from Run F,
  B2, D2 and E. The committed fixture tree is 9,825,741 bytes.

## V8 fixture resolution

The final 256×256 fixture window starts at row 341, column 251. It contains
3,434 GSHHG land pixels, 8,352 coastal-buffer pixels and 53,750 water pixels
outside that buffer. The GSHHG fixture subset retains a 150 m UTM halo so
rasterized counts at the window edge reproduce `window.json` exactly.

Run F's limiting product is `chl_re_gons740`, with valid fraction
`0.7559255813953488`; every product therefore exceeds 0.20. Run D2's amended
`TUR_Nechad2016_665` valid fraction, including finite-product filtering, is
`0.05041860465116279`, inside the required open interval `(0, 0.20)`. Run B2
retains the fallback atmospheric attributes exactly.

Bathymetry remains deliberately excluded until the Phase 3 research item and
fixture re-check. The full Run F archive is retained under `.work/` for that
possible re-crop.

## Verification record

Run after the current Phase 1 changes:

```text
uv run pytest -q
uv run ruff check src tests scripts/make_acolite_fixtures.py
scripts/acolite_env.sh --check
scripts/fetch_gshhg.sh --check
test "$(du -sb tests/fixtures/acolite | cut -f1)" -lt 10000000
```

The last full run reported `155 passed`; Ruff and all Phase 1 direct sanity
checks passed. The default suite remains offline and does not require ACOLITE
or network access.

**The commands above name the shell scripts as they existed then.** On 2026-09-15 they were
replaced by Python (PLAN.md, "Resolved after lock (operational scripts in Python)"):
`scripts/acolite_env.sh --check` is now `uv run python scripts/acolite_env.py --check`, and
`scripts/fetch_gshhg.sh --check` is now
`uv run python scripts/fetch_reference_data.py gshhg --check`.

## Protected workspace state

Do not stage, alter or discard `.agents/`; it remains untracked by PLAN rule.
The untracked `.work/` tree contains the complete real runs and must be retained
through the Phase 3 fixture re-check.

## Next authorized unit

Phase 2.1, **Domain core, delivery grid, acquisition A0–A2**, is next. Begin with
its mandatory pre-flight consumer check and do not carry forward the retired
L2A/loose-band acquisition path.
