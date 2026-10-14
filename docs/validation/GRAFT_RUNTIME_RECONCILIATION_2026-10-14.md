# G.R.A.F.T. Runtime Reconciliation Assessment

**Audited commit:** `634735e4a23f7ae7cd0755e12592ccc9830ba410`

**Date:** 2026-10-14

**Machine-readable companion:** `docs/validation/graft-runtime-reconciliation-2026-10-14.json`
**Authority:** diagnostic only; this assessment grants no execution authority and changes no runtime behavior.

## Result

Ajenda Runtime, G.R.A.F.T., and Continuous Assurance do not duplicate execution authority. Runtime owns state transitions and effects; G.R.A.F.T. observes/evaluates structural and runtime evidence; Continuous Assurance rereads runtime facts on a schedule and appends assurance-only history.

They do have overlapping lifecycle evaluation. The overlap is partly intentional, but not yet normalized enough to make their findings independently comparable. Five source-backed findings are recorded in the companion artifact. The two material concerns are historical-evidence applicability and a reachable path where an assurance row can contain an error finding while retaining an `aligned` status.

## Evidence generated in this run

| Evidence | Result | Limitation |
|---|---|---|
| Canonical dependency graph | Passed: 2,088 nodes, 5,776 edges | Output digest: `sha256:77132735734056eb8f2578e16d22b8c36b5b2d42e38209d53190f5c9f90a3056`. The generator does not embed commit/time/hash metadata; the companion artifact binds the digest to this commit. |
| G.R.A.F.T. drift controls | Passed | Validates lifecycle registry, admission source anchors, forbidden authority patterns, and graph generation. It does not prove all runtime branches invoke the anchors. |
| Unit reconciliation and assurance tests | Passed: 9 | Covers status precedence, append-only/read-only behavior, G.R.A.F.T. snapshot lineage, and semantic selection. |
| Database/RLS assurance integration tests | Blocked: 2 skipped | The local execution environment cannot access the Docker daemon required by Testcontainers. This is not a pass. |

## Responsibility map

| System | What it owns | Timing | Authority | Evidence/output | Assessment |
|---|---|---|---|---|---|
| Ajenda Runtime | Mission admission, task materialization, queueing, leasing, dispatch, canonical state and side effects | Request and worker execution | Enforce, mutate, recover | Mission/task/lease/lineage/evidence/audit records | Sole runtime authority in scope |
| G.R.A.F.T. | Static graph, drift controls, change proof selection, diagnostic runtime projection, exported-snapshot reconciliation | CI/development and on-demand review | Observe, evaluate | Graph/report artifacts; runtime-evidence projection; reconciliation report | Complementary diagnostic system; never dispatches |
| Continuous Assurance | Periodic reread of runtime state, append-only assurance history, metrics | Per active tenant on configured interval | Observe, evaluate | `assurance_snapshots`, metric state, operator findings | Independent scheduling/storage; shares G.R.A.F.T. projection semantics |

### The actual data path

```text
Ajenda Runtime canonical records
        ├─ G.R.A.F.T. runtime-evidence route ──> on-demand diagnostic projection
        └─ Continuous Assurance loop ──> same projection + deliverable read ──> append-only snapshot

Exported tenant snapshot ──> G.R.A.F.T. reconciliation CLI ──> passed/blocked report
```

The shared projection is not a competing authority because it is read-only. It does, however, create a common-mode interpretation dependency: a defect in `build_mission_runtime_evidence_projection` affects both the G.R.A.F.T. route and the assurance process.

## Overlap and conflict assessment

### Legitimate overlap

- G.R.A.F.T. and assurance both read canonical runtime facts. This is necessary for on-demand diagnosis and periodic monitoring.
- Runtime enforces its invariants; G.R.A.F.T. verifies declared structural coverage; assurance preserves later observations. These are complementary roles.

### Duplicated or unnormalized evaluation

- `graft_runtime_reconciliation.py` evaluates graph expectation through selected nodes, materialized tasks, queue, evidence, and deliverable stages from an exported snapshot.
- `MissionRuntimeEvidenceProjection` independently derives queue, lease, evidence, output-artifact, and task-state contradictions from live records.
- Continuous Assurance adds its own status reduction over the projection and deliverable state.

There is no shared finding identity, provenance format, or severity-to-status mapping across those three evaluators. This is evaluation duplication, not duplicated runtime authority.

### Confirmed conflicting evaluation

`ContinuousAssuranceService.reconcile_mission` appends `runtime_state.contradiction_codes` as error findings, but `_status` does not consume those codes. Unless another status input is also contradictory, a snapshot can be `aligned` while containing an error finding. This is a source-proven reachable path, not a claim that a production snapshot currently exhibits it.

## Evidence categories

The current implementation must not treat these as equivalent:

| Category | Meaning | Current support |
|---|---|---|
| Demonstrated violation | Canonical runtime records contradict a contract that was applicable when the record was produced | Partially supported by projection contradictions |
| Missing current evidence | A currently applicable producing transition lacks required evidence | Partially supported, but applicability is not encoded |
| Historical unknown / inapplicable | A record predates the contract, was migrated, or cannot establish whether the evidence requirement applied | Not representable today; it is incorrectly folded into missing/contradictory results |

This last gap matters for missions performed before upgrades or evidence-contract changes: absence alone is not proof of a violation.

## Findings and corrective actions

The source locations, proof, impact, severity, and owner-aligned corrective actions are in the JSON artifact. In short:

1. Add evidence-contract applicability/version provenance at the producing transition, so historical absence becomes `historical_unknown`/`not_applicable`, not a violation.
2. Centralize the existing assurance/G.R.A.F.T. severity-to-status mapping and test that any error finding prevents `aligned`.
3. Add provenance and integrity binding to exported reconciliation snapshots; retain the CLI as a read-only validator.
4. Treat runtime-admission coverage as a source-anchor sentinel only, and add call-path/negative proof for actual control invocation.
5. Keep the shared runtime projection as a shared collector rather than creating another evidence store; strengthen independent consumer fixtures around it.

## Reproducibility

```bash
python scripts/validation/build_dependency_graph.py \
  --output /tmp/ajenda-graft-runtime-reconciliation-634735e4.json
sha256sum /tmp/ajenda-graft-runtime-reconciliation-634735e4.json
python scripts/validation/graft_drift_controls.py
python -m pytest \
  tests/unit/services/test_continuous_assurance.py \
  tests/unit/validation/test_graft_runtime_reconciliation.py \
  tests/integration/assurance/test_continuous_assurance_real.py -q
```

The final command requires a usable Docker daemon to execute the two Testcontainers integration cases. A skipped case must remain recorded as blocked verification.
