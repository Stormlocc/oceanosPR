---
status: draft
tier: b2b-internal
created: 2026-09-11T00:00:00Z
updated: 2026-09-11T00:00:00Z
---

# OCEANOS PR — Coastal Satellite Products and Viewer

> **Baseline note (2026-09-12):** work now proceeds on branch `master`, created fresh at `acc6072` and renamed over the previous one. The Fase 6 (`423e485`) and Fase 7 (`74160a8`) commits are **abandoned and unreachable from any ref** — deliberately left to be garbage-collected. References below to `master` holding Fase 6/7 describe the state before that change.

Product intent for the next phase of the OCEANOS Puerto Rico platform. Establishes what is being built, for whom, and against what measurable success. **Not an architecture document** — implementation decisions are deliberately deferred.

**Baseline:** the platform as assessed in `CURRENT_STATE.md` (same topic folder). Pipeline runs discovery → local catalog → verified download → spatial normalization, and stops there. Everything this PRD describes is new.

**Inherited decisions** (from `CURRENT_STATE.md`): work from the Fase 5 baseline; the two later commits on `master` are rejected as unverified; **all processing is done with ACOLITE**.

---

## 1. Problem

A marine researcher studying the coastal waters of Puerto Rico cannot currently answer a question with this system.

The platform reliably acquires Sentinel-2 scenes over the study area and aligns their bands to a common metric grid. But the outputs are raw sensor sample values — not reflectance, not a water-quality measure, not anything a researcher can interpret. There is no atmospheric correction, no derived product, no time series, and no way to look at any of it. The only interface is a command line that processes one scene per invocation.

So the work that actually produces knowledge happens outside the platform, by hand, per scene: run a correction tool, manage its outputs in a folder, remember which parameters were used, and build comparisons in a notebook that nobody else can reproduce. That manual path does not scale past a handful of scenes, loses provenance as soon as someone renames a file, and produces nothing a colleague can open.

Two questions go unanswered as a result:

- **Water quality / turbidity** — how is water clarity in the study area changing over months and seasons, and where are the persistent problem areas?
- **Sargassum** — when and where did floating vegetation reach the coast, and how did events compare to each other?

Both are answerable from the satellite data already being downloaded. Neither is answerable from the platform today.

---

## 2. Goals

Outcome-level. None of these prescribe an implementation.

1. **A marine researcher can answer a water-quality or sargassum question about the study area across a date range, without operating the pipeline and without assistance.** Today this requires a technical operator and manual tooling for every scene.
2. **Every product a researcher sees can be traced back to the scene, the processing version, and the parameters that produced it** — enough to defend a finding in review or reproduce it a year later.
3. **A technical operator can process a historical date range once, then keep it current, with bounded and visible effort.** Today each scene is a separate manual command with no view of overall state.
4. **Output that came out badly is visibly distinguishable from output that is usable**, before a researcher builds a conclusion on it.
5. **Findings are shareable** — a researcher can point a colleague at what they are looking at, rather than exporting files.

---

## 3. Non-goals

Explicitly out of scope. Several are deferrals, marked as such.

| Out of scope | Note |
| --- | --- |
| Near-real-time sargassum alerting or warning service | **Permanent for this phase.** The chosen cadence is historical + periodic updates. Products are retrospective observations, never operational warnings. |
| Public access | Internal named users only. Avoids presenting scientifically unvalidated products as authoritative to the public. |
| Coral reef / benthic habitat condition | *Deferred.* Considered and not selected as an MVP use case. Would additionally require water-column correction. |
| Validation against in-situ measurements | *Deferred.* No field data is in scope; products are not calibrated or ground-truthed in this phase. |
| Regions beyond the configured study area | *Deferred.* The area of interest stays configurable, but multi-region operation is not a goal. |
| Replacing or re-implementing ACOLITE's science | ACOLITE is the processing authority. The platform orchestrates and presents; it does not compute its own corrections or invent index variants. |
| The rejected Fase 6/7 work (SCL-based QA, in-house NDVI/FAI/RGB) | **Permanent.** Judged unverified. Not to be revived as a shortcut when ACOLITE integration proves harder than expected. |
| Mobile application | Desktop browser only. |
| Automated statistical inference, trend significance testing, or forecasting | The viewer presents measurements and lets a researcher interpret them. |

---

## 4. Users

### Primary — Marine researcher (consumer)

Studies coastal water conditions in the area of interest. Comfortable with remote sensing concepts and skeptical of numbers without provenance. Does **not** operate the pipeline and should not need to. Works in bursts: prepares for a paper, a review, or a field campaign, and needs to look across many dates at once.

Their day today: request scenes from the technical operator, wait, receive a folder, and rebuild the same comparison workflow by hand. Their day after: open the viewer, pick an area and a date range, and read the answer directly.

### Secondary — Technical operator (producer)

Runs discovery, download, and ACOLITE. Owns processing state and data volume. Needs to know what has been processed, what failed and why, and what still needs attention — without inspecting directories by hand.

**These are separate people.** Every workflow below crosses that boundary, which makes the handoff between them a first-class part of the product rather than an implementation detail.

### User stories

1. **As a marine researcher, I want to see how water turbidity in a selected area changed over a date range, so that I can identify seasonal patterns and persistent problem areas** without processing any scene myself.
2. **As a marine researcher, I want to compare the same location across two dates side by side, so that I can judge whether an apparent sargassum event is real** rather than an artifact of cloud, glint, or correction failure.
3. **As a marine researcher, I want every value I look at to name the scene, processing version, and parameters behind it, so that I can defend the finding** to a reviewer or reproduce it later.
4. **As a technical operator, I want one view of what is processed, what failed, and what is pending, so that I can keep the archive current** without tracking state in my head or in a spreadsheet.
5. **As a technical operator, I want failed or low-quality processing to be held back from the viewer automatically, so that a researcher never builds a conclusion on a bad scene** while I investigate it.

### Acceptance criteria

Untagged, per the resolved `free-text` convention (no convention home bound in this repository; degrades to the documented default).

- A researcher can select an area and a date range and see every usable product for that selection without operator involvement.
- Every displayed product links to its source scene, processing version, and parameters.
- Products are comparable across dates: the same location resolves to the same spatial footprint on every date.
- The viewer distinguishes *no usable observation* (cloud, no coverage, failed processing) from *observed and clear*. These must never be visually equivalent.
- **IF** atmospheric correction fails, or its output falls outside the accepted range, **THEN** the product is not published as usable, and the reason is recorded and visible to the operator.
- The operator can see, for any date in the configured range, whether a scene exists, whether it was processed, and the outcome.

---

## 5. Success metrics

| # | Metric | Threshold | Measurement window |
| --- | --- | --- | --- |
| M1 | **Time to answer.** A researcher, unaided, produces a turbidity time series for a chosen area over a 12-month range. | ≤ 5 minutes, in ≥ 3 of 3 observed sessions | First 30 days after launch |
| M2 | **Archive coverage.** Share of Sentinel-2 scenes over the area of interest, within the backfill range and under the cloud threshold, that are processed and visible. | ≥ 90% | Measured once at backfill completion |
| M3 | **Update latency.** Time from a usable scene's acquisition to its appearance in the viewer. | ≤ 7 days, for ≥ 80% of scenes | Rolling 90 days post-launch |
| M4 | **Traceability.** Displayed products that link to scene, processing version, and parameters. | 100% | Continuous; audited at 30 and 90 days |
| M5 | **False-usable rate.** Products marked usable that a researcher judges unusable, from a sample of 30 reviewed products. | 0 | One audit at 60 days |
| M6 | **Adoption.** Named researchers using the viewer at least once per month. | ≥ 3 | Months 1–3 post-launch |
| M7 | **Operator burden.** Operator time to advance the archive by one month of new scenes. | ≤ 60 minutes | Averaged over months 1–3 |

M2 depends on a cloud threshold that is not yet set (Open question 6). M5 is the metric that directly tests Goal 4; if it exceeds 0, the quality gate is not working regardless of how the other metrics read.

---

## 6. Supported workflows

Five workflows, spanning both roles. Described as intent, not mechanism.

**W1 — Historical backfill (operator).** The operator selects a date range, and the system discovers, acquires, and processes every qualifying scene over the area of interest. Progress and failures are visible throughout. Completion is what makes M2 measurable and gives researchers a usable time series from day one.

**W2 — Periodic update (operator).** New scenes are incorporated as they become available, on a recurring basis. This is what keeps M3 true after launch.

**W3 — Time-series inspection (researcher).** Select an area and a date range; see how a water-quality measure changed over that period. The core water-quality workflow.

**W4 — Date comparison (researcher).** Put two or more dates for the same location beside each other, to judge whether a change is real. The core sargassum workflow, and the check that prevents a cloud edge or a correction artifact from being read as an event.

**W5 — Provenance inspection (researcher).** From any displayed value, reach the scene, processing version, and parameters behind it. What makes Goal 2 real rather than aspirational.

**Not a workflow in this phase:** researcher-initiated processing. With a separate operator, whether a researcher can request a scene not yet processed is undecided (Open question 4).

---

## 7. Expected products

The specific ACOLITE outputs cannot be named until Open question 1 resolves, so this section states what each product must *do* for the user, with the likely ACOLITE family named where it is reasonably clear. Substituting a different ACOLITE product that serves the same purpose is a downstream decision, not a change to this PRD.

| Product | Serves | Purpose |
| --- | --- | --- |
| **Surface reflectance** | Both | The corrected base layer everything else derives from. Not consumed directly by researchers, but its availability and quality determine everything above it. |
| **Water-clarity measure** (turbidity or suspended matter) | Water quality | The primary quantity behind W3. Must be comparable across dates and expressed in a stated unit. |
| **Floating-vegetation indicator** | Sargassum | Distinguishes floating material at the surface from clear water. Must be interpretable at the event scale, not only per pixel. |
| **True-color view** | Both | Visual context and sanity check. What lets a researcher recognize at a glance that an anomaly is a cloud edge. |
| **Usability mask** | Both | Marks where an observation exists and is trustworthy versus where it is absent (cloud, no coverage, correction failure). Required by the acceptance criteria; without it, absence and clarity look identical. |
| **Provenance record** | Both | Per product: source scene, processing version, parameters, timestamps. Serves M4 and W5. |

All products share one spatial footprint per location, so that any two dates are directly comparable.

---

## 8. Visualization capabilities

Internal web application, authenticated named users, desktop browser.

**Required for MVP:**

- **Map view** of the area of interest for a selected product and date, with the usability mask distinguishable from valid observation.
- **Date navigation** across the processed archive, including dates with no usable observation — shown as such, not silently skipped.
- **Area selection** — a point or region the researcher defines, which becomes the subject of the time series.
- **Time series** of the selected measure over the selected area and range, with gaps represented as gaps.
- **Side-by-side date comparison** for the same location.
- **Provenance panel** reachable from any displayed product.
- **Value inspection** — read the underlying number at a location, with its unit.
- **Operator status view** — per date: scene present, processed, outcome, failure reason.

**Explicitly not in MVP:** drawing/annotation tools, user-saved views or dashboards, report generation, export beyond the underlying product files, overlays of external datasets, 3-D or animated playback, and any authoring of new products through the interface.

---

## 9. Operational constraints

Hard realities that shape what the MVP can promise. Several come directly from the baseline assessment.

1. **Cloud cover is the dominant constraint.** Puerto Rico is tropical; a large share of Sentinel-2 passes over the area will be unusable. This is the single biggest threat to M2 and to the usefulness of the time series, and it is outside anyone's control. The MVP must represent sparse coverage honestly rather than interpolate over it.
2. **ACOLITE is an out-of-process dependency.** Not a library in the current dependency set. Its version must be pinned and recorded per product (M4 depends on this).
3. **The required satellite input level is unresolved** and is the highest-leverage open question in the project. If ACOLITE requires top-of-atmosphere bundles rather than the surface-reflectance band files the platform downloads today, the acquisition path changes substantially — potentially including the data provider.
4. **Data volume is significant.** A single scene's band set already runs into hundreds of megabytes; full source bundles would be larger, and a multi-year backfill multiplies it. Storage, retention, and what is kept versus recomputed are operating decisions, not afterthoughts.
5. **The platform processes one scene at a time, with a single writer.** Documented throughout the baseline and enforced nowhere. Backfill (W1) inherently pushes against this.
6. **Products are not scientifically validated.** No in-situ calibration is in scope. The platform's existing convention of labeling unvalidated outputs as such must extend to everything the viewer shows.
7. **No orchestration, scheduling, or job-state capability exists today.** W1 and W2 both depend on capability that is entirely new.
8. **The study-area boundary currently in use is explicitly illustrative and unverified.** Using it for research output requires replacing it with a reviewed boundary first.

---

## 10. Stakeholders

| Role | Interest | Needs from this |
| --- | --- | --- |
| Marine researchers | Primary consumers | Answers they can defend; no dependence on operator availability |
| Technical operator | Runs and maintains the pipeline | Bounded, visible workload; clear failure signals |
| Project lead | Scope, sequencing, resourcing | Realistic MVP; honest read on the ACOLITE unknown |
| Reviewers of resulting work | External credibility | Reproducibility and stated limitations |

---

## 11. Rollout

Sequenced so the largest unknown is resolved before anything is built on top of it.

1. **Resolve the ACOLITE input question** (Open question 1). Everything downstream is contingent. No implementation before this closes.
2. **Single-scene path end to end** — acquire, correct, produce, display one scene for one date. Proves the integration and the quality gate.
3. **Backfill a bounded range** (a season, not years) — exposes volume, cloud sparsity, and operator burden at a survivable scale, and gives M2 and M7 their first real readings.
4. **Viewer with the required capabilities**, against the backfilled range.
5. **Periodic updates** (W2) once the archive is stable.
6. **Launch to named researchers**, starting the M1/M3/M5/M6 measurement windows.

Sequencing risk: step 3 is where cloud sparsity becomes visible. If usable coverage is far below expectation, the product's value proposition needs revisiting before step 4, not after.

---

## 12. Compliance and integration

- **Access.** Authenticated named users; no anonymous access. Researcher and operator capabilities are distinct.
- **Licensing.** Sentinel-2 data carries its own terms. ACOLITE's license is more restrictive than the platform's current dependencies and must be settled before it is embedded — the platform's existing catalog already declines to assert new licensing over source assets, and that stance should hold.
- **Attribution.** Products must credit the data source and the processing tool.
- **Scientific labeling.** Every product surface states that outputs are uncalibrated and not validated against field measurements.
- **No personal data.** The system holds satellite observations and user accounts only.
- **External integrations in MVP:** satellite data provider and ACOLITE. Nothing else — no notifications, no third-party GIS, no institutional identity provider unless one already exists.

---

## 13. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| **ACOLITE needs a different input level than the platform acquires** | High — reworks acquisition, possibly the data provider | Resolve before any implementation (rollout step 1); treat as a research task, not an assumption |
| **Cloud cover leaves the time series too sparse to be useful** | High — undermines the core water-quality value | Measure real usable coverage at step 3 on a bounded range, before building the viewer on top |
| **ACOLITE output quality over shallow coastal water is poor** | High — the study area is exactly this case | The quality gate (M5) is designed to catch it; a researcher reviews real output at step 2 |
| **Operator burden makes the archive fall behind** | Medium — M3 and M7 both fail | Make burden visible early (step 3); it is a measured metric, not an assumption |
| **Storage growth outpaces available capacity** | Medium | Set retention policy before backfill (Open question 5) |
| **Researchers treat unvalidated products as authoritative** | Medium — reputational and scientific | Labeling is a required product surface, not a footnote; public access is a non-goal |
| **Single-writer constraint blocks backfill throughput** | Medium | Surfaced now as a known constraint; the bounded-range step tests it before committing to years of data |

---

## 14. Open questions

Genuinely undecided. Each needs an answer before or during planning.

1. **Which Sentinel-2 product level and bundle format does ACOLITE require, and can the current data provider serve it?** *Highest leverage in the project.* Decides how much of acquisition survives. Resolve via external research before planning. **Blocks rollout step 1.**
2. **Which specific ACOLITE outputs become the water-clarity and floating-vegetation products, and in what units?** Contingent on (1). Determines what §7 actually names.
3. **Does ACOLITE or the platform own the output spatial grid?** Contingent on (1). Decides whether the existing normalization stage stays in the pipeline, moves after correction, or is retired.
4. **Can a researcher request processing of a scene that is not yet in the archive?** With a separate operator, this is a real workflow gap. *Recommended default:* no in MVP — researchers consume, operators produce; revisit if researchers hit the gap more than occasionally.
5. **What is retained versus recomputed?** Source scenes are large. *Recommended default:* retain final products and provenance indefinitely; decide source-data retention once real volume is measured at rollout step 3.
6. **What cloud-cover threshold defines a "qualifying" scene?** M2 is unmeasurable without it. *Recommended default:* set it empirically from the bounded backfill rather than picking a number now.
7. **How deep does the historical backfill go?** *Recommended default:* decide after step 3 measures real cost per month of archive.
8. **What is the reviewed study-area boundary?** The current one is explicitly illustrative. Needed before any research output.
9. **State-driven coverage — considered and not adopted.** The coverage prompt surfaced a state-driven criterion ("while a scene is reprocessing, the previous version stays visible and complete") and it was not selected. Recorded here so the decision is traceable rather than lost; revisit if reprocessing turns out to be frequent.

---

## 15. Next steps

This PRD locks product intent. It does not decide architecture.

1. **External research on ACOLITE** — input levels and bundle formats, subsetting and output-grid control, output products and units, invocation interface, version pinning, license. Answers open questions 1–3. **Do this first.**
2. **Engineering contract** — constraints, untouchable areas, performance budget. Once the ACOLITE shape is known.
3. **Implementation planning** — after 1 and 2.
