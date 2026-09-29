# Ajenda Graph → G.R.A.F.T. → G.R.A.F.T.+ Progression Map

**Status:** Historical progression artifact  
**Recorded:** 2026-09-28  
**Source:** Ajenda git history on `main`, reconciled with the `1devteam/rd-program` lineage records  
**Scope:** Canonical graph lineage, GRAFT runtime contract work, runtime evidence, and GRAFT+ workflow adoption

This map records what the repository history proves. A PR reference in the R&D study is not treated as a merged product change unless the git history confirms it. Formatting, retry, and certification commits are collapsed under their feature/PR phase unless they materially changed the boundary.

## Executive progression

```text
classifier / PR invariants
  → canonical dependency graph
  → impact and proof selection
  → selective CI / completeness / decision manifest
  → authority containment and semantic hardening
  → state-ownership repairs
  → function-level mission-composition graph
  → runtime contract semantics
  → binding adjudication and action reachability
  → instantiated applicability
  → RevOps artifact-consumption repairs
  → runtime evidence and static/runtime reconciliation
  → GRAFT+ workflow and GRAFT1st reconciliation gates
```

## Phase 1 — Foundation: classifier and canonical graph (2026-08-23)

| PR | Confirmed merge commit | Representative commits | Progression |
|---:|---|---|---|
| #453 | `7a14d0c2` | `feat(pr_invariant_classifier)` | Introduced the PR/invariant classification foundation. |
| #454 | `366735a4` | `ec534a3c`, `207594bb`, `9157d0c4` | Added the canonical dependency graph generator, generation proof, and CI artifact production. |
| #455 | `addc6200` | `366735a4` parent series, `0a35e6c4` | Added transitive graph impact analysis and blast-radius semantics. |
| #456 | `12b96f93` | `3956086d`, `ea8c2002` | Added proof selection and proof-manifest generation. |
| #457 | `998f6c11` | selective-CI shadow commits | Added graph-selected CI as a shadow signal. |
| #458 | `93251f1f` | `2c94accd`, `27aa6c84` | Added graph completeness auditing and semantic-gap detection. |
| #459 | `3f8aa41a` | `85f5fed0`, `d178d68d` | Added the architecture decision manifest. |

**Result:** Ajenda had one canonical graph with generated source dependencies, semantic overlay relationships, impact traversal, proof selection, completeness auditing, and architecture decisions.

## Phase 2 — Study boundary and authority containment (2026-08-24–25)

| PR | Confirmed merge commit | Representative commits | Progression |
|---:|---|---|---|
| #460 | `7f8a9ed5` | authority-containment corrective series | Applied authority-containment repairs identified around the graph/runtime boundary. The R&D register correctly leaves graph causal contribution unadjudicated. |
| #466 | `8aabfc4d` | `research/pr-cascade-study-inception` | Established the PR-cascade research protocol. This is study infrastructure, not a runtime feature. |
| #467 | no merge commit found | closed graph-guided pilot | R&D records it as closed with a protocol exception; it is not treated here as a merged product phase. |
| #468 | `eb74c3cc` | `15f8faea`, `42a36be2` | Merged database, egress, and state-ownership semantics into the canonical graph and introduced semantic ratcheting. |
| #469 | `7fefedc1` | RLS/session-boundary repair series | Repaired tenant RLS session boundaries and added graph-backed regression proof. |
| #470 | `eb89b9d0` | post-RLS baseline certification | Certified the post-RLS graph baseline and recorded explicit control-plane exceptions. |

**Result:** The graph stopped being import-only. Tenant isolation, egress, state ownership, known violations, and reviewed exceptions became explicit graph semantics.

## Phase 3 — State ownership and concurrency closure (2026-08-25–26)

| PR | Confirmed merge commit | Representative commits | Progression |
|---:|---|---|---|
| #471 | no merge commit found | superseded corrective design | Design-only work; superseded and not counted as a production closure. |
| #472 | `1d37a34a` | durable HTTP receipt/ownership series | Established durable HTTP idempotency ownership and retry-safe execution claims. |
| #473 | `bdf455a5` | atomic single-use credential transition series | Proved single-use credential consumption before successor authority is minted. |
| #475 | `e8a09d45` | Redis lease-owner integrity series | Closed Redis lease ownership integrity with concurrency proof. |
| #476 | `576bf5ba` | SMTP send-claim ownership series | Added durable SMTP send ownership and evidence of single-send claims. |

**Result:** The graph began selecting and ratcheting concurrency/state proofs, not merely listing dependencies.

## Phase 4 — Function-level composition visibility (2026-08-26)

| PR | Confirmed merge commit | Representative commits | Progression |
|---:|---|---|---|
| #481 | `dd443f1c` | `b306b034`, `f7e6f75b`, `c92d2a89`, `a22724cd` | Added mission-composition function inventory and function-level impact analysis. |

**Result:** The graph could identify individual composition decision functions even when module-level dependencies were too coarse.

## Phase 5 — G.R.A.F.T. runtime contract semantics (2026-08-30–31)

| PR | Confirmed merge commit | Representative commits | Progression |
|---:|---|---|---|
| #501 | `53673d3c` | `dcff3359`, `27c14672`, `7c76fdaa`, `35fb2c7f` | Modeled runtime job contracts, runtime artifacts, and contract semantics as graph nodes. |
| #502 | `d97005bc` | `c273ee6b`, `918bd5e7`, `452fe000`, `ab476f73` | Added runtime binding adjudication, artifact-consumption witnesses, and typed binding evidence. |
| #503 | `8fa4c16d` | optional decision-support contract repair | Repaired a RevOps optional decision-support contract derived from the graph treatment. |
| #504 | no merge commit found; feature commit `0b075114` | action-selection reachability series | Added independent action-selection reachability evidence. |
| #505 | no separate merge commit found; feature commit `27adbbdf` | runtime resolver applicability series | Instantiated resolver applicability and restricted repair authorization to evidenced active violations. |

**Result:** The graph became G.R.A.F.T. in the Ajenda lineage: it modeled jobs, artifacts, actions, reachability, binding, consumption, and applicability while keeping enforcement disabled where documented.

## Phase 6 — RevOps consumption repairs (2026-09-01)

| PR | Confirmed merge commit | Progression |
|---:|---|---|
| #507 | `2041d1f9` | Repaired CRM pipeline artifact consumption. |
| #508 | `f0de18e0` | Bound researched prospects to sales/research consumption. |
| #509 | `3a7caba4` | Corrected the final sales research-context contract/residual. |

**Result:** G.R.A.F.T. findings drove targeted RevOps artifact-consumption repairs without broadening web action authority.

## Phase 7 — Runtime evidence and static/runtime reconciliation (2026-09-16–22)

| Commit/PR | Confirmed commit | Progression |
|---|---|---|
| Runtime evidence slice | `5e8df62e` | Exposed mission runtime evidence. |
| Joined task flow | `c7ec4c3d` | Exposed joined runtime task flow. |
| Record lineage/events | `19d040ac` | Added record lineage and runtime event evidence. |
| Static/runtime join | `79ae46da` | Joined static graph impact with runtime evidence. |
| Materialized node identity | `be951d5c` | Preserved runtime node identity for reconciliation. |
| Acceptance evidence | `e6d93083`, `73847419` | Included GRAFT impact and mission acceptance evidence in the mission flow. |
| Failed-mission evidence | `8148a286`, `ab0e5463` | Preserved evidence and exposed runtime divergence on failure. |
| Deployment support | `e1914dd9`, `f68ac82b`, `72f8a713`, `1ab24134` | Added deployment/runtime support inventory and hardened the runtime truth surface. |
| PR #546 | `1ab24134` | Hardened the GRAFT runtime truth surface. |
| PR #547 | `7d63eb25` | Continued mission runtime hardening. |

**Result:** GRAFT artifacts expanded from static review to typed, tenant-scoped observations of mission, task, queue, lease, lineage, evidence, audit, contradictions, and first divergence.

## Phase 8 — GRAFT+ workflow formalization (2026-09-08–28)

| Commit | Progression |
|---|---|
| `60af34c` | Added the unified GRAFT+ validation gate. |
| `de4b417f` | Mapped graph workflow definitions into the tooling boundary. |
| `c6cfd645` | Improved graph baselines and artifact lineage. |
| `78fd13ab` | Completed CRM, finance, and graph contract integration. |
| `13adcf52` | Established the documented GRAFT+ build workflow. |
| `2763c0a5` | Explicitly distinguished GRAFT1st from GRAFT+. |
| `d53a3e03` | Enforced GRAFT1st implementation conformance. |
| `3eb3e0a9` | Reconciled GRAFT+ WP1 admission status. |

**Result:** GRAFT+ became the documented Ajenda workflow for UPG/LAP, graph-guided implementation, proof expansion, runtime-artifact inspection, and reconciliation. It remains non-authoritative.

## Current boundary

At the current observed `main` commit `42768eb3`:

- the canonical graph lineage is active;
- GRAFT+ is an established build/proof workflow;
- a bounded GRAFT integrity check participates in mission runtime admission;
- runtime evidence is exposed as a read-only artifact;
- GRAFT1st remains a declarative RevOps/CRM contract package;
- external `graft_plus` is not an Ajenda runtime dependency;
- the onboarding-status work most recently proved that account onboarding remains outside mission runtime.

## Historical truth rules

- A PR documented in R&D but absent from git merge history remains an R&D reference, not a confirmed merged product change.
- A feature commit without a merge commit is listed as a commit anchor, not retroactively assigned a merge status.
- Formatting, retry, and certification commits are preserved in git but grouped under their parent phase here.
- The progression demonstrates adoption and capability growth; it does not by itself prove general superiority or causal attribution for every improvement.
