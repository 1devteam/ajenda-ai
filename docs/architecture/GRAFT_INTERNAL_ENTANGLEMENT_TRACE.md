# Ajenda GRAFT Entanglement and Authority Trace

**Status:** Discovery trace  
**Recorded:** 2026-09-28  
**Companion:** [`GRAFT_INTERNAL_LINEAGE_SURFACE_MAP.md`](./GRAFT_INTERNAL_LINEAGE_SURFACE_MAP.md)  
**Scope:** Existing Ajenda implementation only. No behavior change is authorized by this document.

This trace follows the graph/GRAFT/GRAFT1st surfaces from entry point to output. It distinguishes code-proven links from relationships that still require runtime or lifecycle proof.

## Trace A — canonical graph to non-runtime proof artifacts

```text
source modules / tests / migrations / frontend imports
        + semantic overlay
        + runtime/action/egress/state inventories
        ↓
scripts/validation/build_dependency_graph.py
        ↓
graph model (nodes, edges, invariants, findings, metrics)
        ↓
graph_impact_analysis.py
        ↓
graph_proof_selection.py
        ↓
completeness / architecture / contract / CI validators
        ↓
JSON reports, CI artifacts, PR review evidence
```

**Proven links:** builder imports the inventory modules and overlay; the impact/proof scripts consume graph-shaped reports; CI invokes the graph validators.  
**Authority:** diagnostic and proof selection only. These outputs do not dispatch tasks, mutate tenant state, grant credentials, or approve side effects.  
**Unknown:** artifact retention, freshness guarantees, and which reports are retained as durable historical provenance after CI completion.

## Trace B — GRAFT runtime admission

```text
mission runtime-admission route
        ↓
server-normalized mission objective + materialized task graph
        ↓
backend.services.mission_graph_integrity.evaluate_admission_integrity
        ↓
credential visibility / eligibility / metadata match / decryptability checks
        + report-materialization check
        + explicit Google Contacts selection check
        + leaked-markdown-input check
        ↓
clear → continue existing authority admission
blocked → HTTP 400 with GRAFT findings
```

**Code evidence:** `backend/api/routes/mission.py:2403-2425`; `backend/services/mission_graph_integrity.py:38-117`.  
**Proven links:** the route invokes the check before continuing to authority provisioning/admission; the check reads tenant-scoped credentials and does not mutate runtime state; a non-clear report blocks admission.  
**Authority:** bounded fail-closed gate. It can block admission, but it cannot dispatch work, create credentials, or authorize a side effect.  
**Potential entanglement:** runtime admission now depends on GRAFT semantics and credential repository behavior. Changes to graph interpretation can change which missions are admitted.  
**Unknown:** complete inventory of all mission paths that can reach admission outside this route and whether every such path invokes the same integrity check.

## Trace C — persisted runtime facts to human-readable GRAFT artifact

```text
tenant-scoped runtime-evidence route
        ↓
mission + execution tasks + leases + lineage + evidence + audit events
        ↓
build_mission_runtime_evidence_projection
        ↓
typed read-only MissionRuntimeEvidenceProjection
        ↓
API response / runtime review artifact / optional joined static-impact report
```

**Code evidence:** `backend/api/routes/mission_deliverable.py:142-186`; `backend/services/mission_runtime_evidence_projection.py:146-562`.  
**Proven links:** route permission is required; every repository read is tenant-scoped; projection records nodes, edges, selected/available nodes, task flows, evidence, contradictions, missing evidence, and first divergence; the model declares `read_only=True` and `grants_execution_authority=False`.  
**Authority:** observation and review only. It does not queue, claim, start, retry, or authorize work.  
**Potential entanglement:** the projection interprets persisted metadata keys (`runtime_admission`, queue admission, worker admission, materialization, artifacts) and therefore couples GRAFT artifact meaning to runtime metadata schemas.  
**Unknown:** retention, version migration, and whether all user-visible deliverables expose the same projection or only selected mission endpoints.

## Trace D — GRAFT1st RevOps contract to CRM path

```text
GRAFT1ST_REQUIRED_NODE_KEYS / typed contracts
        ↓
CanonicalContractPackage validation
        ↓
versioned RevOps know-how identity
        ↓
mission composition / CRM action contract references
        ↓
existing ability resolver + ActionRegistry + governed runtime
```

**Code evidence:** `backend/services/vertical_ops/graft1st_contracts.py:1-5,18-20,276-325`; `backend/services/mission_composition/vertical_know_how.py:19-20,321-322`; `backend/services/tools/crm_actions.py`; reconciliation tests and fixtures.  
**Proven links:** the contract package is declarative, version-pinned, validates node/edge/artifact compatibility, rejects unknown or duplicate nodes, and asserts hard-dependency acyclicity. The package explicitly sets `authority_class=declarative` and `grants_execution_authority=False`.  
**Authority:** composition and contract validation only. Existing CRM runtime authority remains in the resolver, registry, dispatcher, credentials, and tenant-scoped runtime.  
**Potential entanglement:** RevOps know-how carries GRAFT1st package identity, so changing the contract package can affect persisted composition provenance and compatibility checks.  
**Unknown:** full persisted-record migration/read-compatibility behavior for historical GRAFT1st package versions.

## Trace E — findings to CI and selected proof

```text
graph semantic/runtime findings
        ↓
acknowledged baseline / blocking classification
        ↓
completeness and contract gates
        ↓
CI workflow status and uploaded JSON artifacts
        ↓
PR review / release decisions
```

**Proven links:** `.github/workflows/dependency-graph.yml`, `.github/workflows/graft-runtime-contract-adjudication.yml`, and graph-related tests invoke these validators and upload reports.  
**Authority:** CI/review signal. A graph finding does not itself modify product behavior or grant merge authority.  
**Potential entanglement:** a new graph detector or changed baseline can alter CI outcomes without changing product code.  
**Unknown:** whether every uploaded artifact is externally archived and how operators distinguish current findings from historical baseline findings.

## Entanglement classification

| Relationship | Classification | Evidence status |
|---|---|---|
| Builder → overlay/inventories | Intentional structural dependency | Proven by imports and graph output |
| Builder → impact/proof/completeness | Intentional report pipeline | Proven by CLI/report contracts and tests |
| Mission admission → GRAFT integrity | Intentional runtime gate | Proven by route call and blocking behavior |
| Runtime evidence → persisted metadata schema | Intentional but schema-coupled | Proven; migration/freshness behavior open |
| GRAFT1st → RevOps know-how | Intentional compatibility coupling | Proven by imports and provenance fields |
| GRAFT1st → CRM action path | Declarative contract coupling | Partially proven; full runtime trace open |
| Graph findings → CI decisions | Intentional review coupling | Proven by workflows; archival behavior open |
| External `graft_plus` engine → Ajenda runtime | No executable coupling found | Proven absent from production imports; docs references remain |
| Generated graph/report artifacts → long-term provenance | Unknown lifecycle coupling | Requires artifact-retention audit |

## What is intentionally not coupled

- Graph tooling does not directly register handlers or invoke Playwright.
- GRAFT1st contracts do not resolve secrets, persist state, dispatch work, or grant authority.
- Runtime evidence projection does not execute, retry, or authorize work.
- GRAFT+ reports do not replace MissionIntent, BusinessJob, AbilitySelection, ActionRegistry, or WorkerRuntimeService.
- External `graft_plus` prototype code is not an Ajenda runtime dependency.

## Remaining proof obligations

1. Enumerate every runtime admission entry point and prove GRAFT integrity coverage.
2. Trace every runtime metadata key consumed by the evidence projection to its writer and migration history.
3. Trace GRAFT1st package versions through composition records and historical reads.
4. Inventory artifact creation, storage, retention, freshness, and user-visible exposure.
5. Run a static/runtime joined artifact for a real mission and compare selected nodes, tasks, leases, evidence, and deliverables.
6. Classify each remaining relationship as intentional, compatibility, accidental, historical, or unknown.

Until these obligations are closed, no graph/GRAFT surface should be removed, renamed, or broadened on the assumption that it is merely documentation or merely runtime logic.
