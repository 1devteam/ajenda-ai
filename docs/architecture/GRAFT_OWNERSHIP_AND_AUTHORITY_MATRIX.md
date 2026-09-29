# Ajenda GRAFT Ownership and Authority Matrix

**Status:** Discovery and governance artifact  
**Recorded:** 2026-09-28  
**Companions:** `GRAFT_INTERNAL_LINEAGE_SURFACE_MAP.md`, `GRAFT_INTERNAL_ENTANGLEMENT_TRACE.md`  
**Scope:** Ownership, authority, and drift controls for graph/GRAFT/GRAFT1st surfaces

This document answers two questions:

1. Which parts of the graph lineage are acting within their intended domain?
2. Who owns each part, and what must be true before any future authority expansion?

It is not itself an authority grant.

## Current ownership matrix

| Surface | Current source of truth | Current effective owner | Current rights | Mutation capability | Drift status |
|---|---|---|---|---|---|
| Canonical graph builder | `scripts/validation/build_dependency_graph.py` | `architecture-runtime-governance` | Generate structural and semantic graph facts | Writes only requested graph/report output | Ledger-owned as diagnostic artifact; no runtime authority |
| Semantic overlay | `docs/contracts/dependency-graph.overlay.v1.json` | `architecture-runtime-governance` with reviewed domain owners | Declare non-import relationships, exceptions, invariants | Changes graph interpretation and CI findings | Ledger ownership is explicit; overlay changes still require review |
| Impact/proof/completeness tooling | `scripts/validation/graph_impact_analysis.py`, `graph_proof_selection.py`, `graph_completeness_audit.py` | `architecture-runtime-governance` | Select impact, proof, and review obligations | Writes reports/CI artifacts; can fail gates | Ledger-owned as diagnostic tooling; no runtime authority |
| GRAFT+ workflow | `docs/development/GRAFT_PLUS_WORKFLOW.md`, `scripts/validation/graft_plus_gate.py` | `architecture-runtime-governance` | Coordinates UPG/LAP, graph, proof, runtime review | Changes review/build behavior and CI outcomes | Explicit ledger owner; cannot dispatch product work |
| Mission graph contract | `backend/api/routes/mission.py`, authority ledger entry `mission_task_graph_contract` | Mission platform owner | Validate/persist normalized graph metadata | Tenant-scoped graph metadata mutation only | Explicitly ledger-owned |
| Runtime GRAFT integrity check | `backend/services/mission_graph_integrity.py`, called by `backend/api/routes/mission.py` | `runtime-admission-governance` | Read task graph and tenant credential metadata; return clear/blocked | No database mutation in implementation/tests | Ledger-owned read model; it can block admission but cannot provision authority |
| Runtime evidence projection | `backend/services/mission_runtime_evidence_projection.py`, `mission_deliverable.py` | `evidence-observability-governance` | Read tenant-scoped runtime facts and emit diagnostic projection | No runtime mutation | Ledger-owned read model; cannot queue, authorize, or mutate |
| GRAFT1st RevOps package | `backend/services/vertical_ops/graft1st_contracts.py` | `revops-composition-governance` | Validate declarative nodes, edges, artifacts, and simulations | In-memory validation only | Ledger-owned declarative contract; execution authority remains elsewhere |
| RevOps know-how | `backend/services/mission_composition/vertical_know_how.py` | `revops-composition-governance` | Select bounded jobs, outputs, budgets, connectors, and review boundaries | Composition/provenance effects through normal composition | Declarative authority is explicit; owner is ledger-declared |
| Job catalog/resolver | `backend/services/mission_composition/job_catalog.py`, capability resolver | Mission composition/runtime contract owner | Resolve jobs to declared candidate actions | Does not itself execute actions | Existing authority boundaries are explicit in adjacent contracts |
| ActionRegistry/TaskDispatcher | Existing runtime contracts and authority ledger | Runtime execution owner | Resolve and execute governed actions | Actual runtime/task/provider/CRM mutations | Explicit runtime authority owner |
| Admission coverage inventory | `backend/services/runtime_admission_coverage.py` | `runtime-admission-governance` | Enumerate every route/service/daemon that can admit work and its integrity controls | Validation metadata only | Fail-closed source-token coverage; does not admit work |
| Drift controls | `scripts/validation/graft_drift_controls.py` | `architecture-runtime-governance` | Reject authority claims, secret resolution, handler registration, stale graph output, and ActionRegistry bypass | CI/build failure only | No product runtime mutation |
| Runtime reconciliation | `scripts/validation/graft_runtime_reconciliation.py` | `evidence-observability-governance` | Compare graph, selected nodes, materialization, queue/lease, evidence, and deliverable snapshots | Diagnostic findings only | Unresolved contradictions remain blocked/visible |

## What “mostly in the right place” means

The implementation evidence supports correct placement for the **rights** of most components:

- graph tooling maps and reports;
- GRAFT+ coordinates build/proof work;
- runtime integrity checks preconditions;
- evidence projection observes;
- GRAFT1st and know-how constrain composition;
- ActionRegistry/TaskDispatcher own execution;
- CRM actions own CRM mutation.

It does **not** mean ownership is fully formalized. The main current weakness is governance metadata: several important surfaces have correct code behavior but implicit accountable owners.

## Confirmed authority boundaries

### Runtime integrity

`evaluate_admission_integrity` is a precondition check. Its unit tests prove credential preflight does not call `commit` or `flush`. The mission admission contract test proves a blocked result prevents authority provisioning and leaves mission/task mutation untouched.

### Runtime evidence

`MissionRuntimeEvidenceProjection` declares `read_only=True` and `grants_execution_authority=False`. Its route requires runtime-view permission and filters mission, task, lease, lineage, evidence, and audit reads by tenant.

### GRAFT1st contracts

`CanonicalContractPackage` declares `authority_class=declarative` and `grants_execution_authority=False`. Validation rejects duplicate/unknown nodes, invalid artifact edges, and hard-dependency cycles.

### CRM mutation

`crm.mutate` is the actual internal CRM write path. It is separate from GRAFT, requires an idempotency key, validates the reconciliation plan, writes through the tenant-scoped record store, reads back the result, and emits an effect receipt.

## Current governance gap

The authority ledger now contains dedicated entries for the runtime integrity check, runtime evidence projection, GRAFT+ workflow, GRAFT1st RevOps package, and artifact lifecycle contract. This closes the explicit-owner gap. The remaining lifecycle limitation is operational: the typed lifecycle registry currently governs artifact metadata and validation, while durable storage/expiration/reconciliation for every generated artifact still requires a separate persistence implementation.

## Required owner declaration for future GRAFT+ authority

Yes—declare an owner now, before granting self-management capabilities. The owner must be an accountable control-plane owner, not the graph itself.

At minimum record:

1. **Product owner:** what outcomes the capability is allowed to pursue.
2. **Technical owner:** which implementation and schemas are maintained.
3. **Authority owner:** which resources/actions may be changed.
4. **Tenant/data owner:** whose data and boundaries are in scope.
5. **Safety/review owner:** approval, policy, and escalation requirements.
6. **Incident owner:** kill switch, rollback, and recovery responsibility.
7. **Lifecycle owner:** versioning, deprecation, migration, and artifact retention.

The future self-management path should be:

```text
declared owner policy
  → bounded capability manifest
  → ActionRegistry authority
  → approval/autonomy policy
  → idempotent governed action
  → evidence + audit + read-back
  → owner-visible reconciliation
```

GRAFT+ must never self-grant that authority. A graph finding may recommend or block; a separately owned, reviewed runtime capability must grant and execute the action.

## Admission coverage and drift controls

The admission inventory now covers graph admission, runtime task materialization, canonical and
legacy queue admission, single-task queue admission, vertical-template queueing, review approval,
bridge authority provisioning, worker claim/start, and daemon dispatch. Each entry names its
source file, integrity controls, owner, mutation scope, and fail-closed requirement. The drift
sentinel checks those anchors and the canonical graph freshness in CI.

The recurring reconciliation contract accepts a tenant-scoped exported runtime snapshot. It
compares the graph expectation through selected nodes, materialized tasks, queued tasks, evidence,
and final deliverable. Dropped nodes, undeclared nodes, tenant mismatches, duplicates, and supplied
unresolved contradictions remain visible and produce a blocked result.

## Drift controls required before authority expansion

- Keep the explicit authority-ledger entries for runtime GRAFT integrity and runtime evidence projection synchronized with their source paths.
- Keep the named owner and change-control policy for the semantic overlay enforced in review.
- Add a versioned graph manifest containing source commit, overlay version, schema, findings, and authority class.
- Prove every runtime admission entry point invokes the required integrity controls.
- Register artifact creation, storage, freshness, expiration, and historical lineage. The typed registry now covers ownership, freshness, retention, tenant scope, and supersession lineage; durable retention/expiration enforcement remains follow-up work.
- Add negative tests preventing graph/GRAFT components from registering handlers, resolving secrets, or mutating tenant data.
- Run static/runtime reconciliation periodically and fail on unexplained divergence.
- Require human/tenant policy approval before any GRAFT-derived capability can move from advisory/blocking to mutating authority.

## Future authority promotion

GRAFT+ has no self-promotion path. Any future authority promotion must be a separately reviewed
capability with this sequence:

```text
named owner
  → explicit capability manifest
  → bounded resources/actions
  → approval/autonomy policy
  → idempotency + rollback
  → audit/evidence/read-back
  → kill switch + periodic review
```

The authority ledger records this as a prohibited-until-reviewed declarative contract. Adding a
graph finding, lifecycle record, or reconciliation result cannot create that capability.

## Conclusion

The current code shows a mostly well-separated architecture, but accountability is less explicit than behavior. The next improvement is not to give GRAFT+ more power. It is to formalize ownership and authority contracts first, so any future self-management capability has a named owner, bounded rights, independent runtime enforcement, and a reversible audit trail.
