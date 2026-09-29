# Ajenda GRAFT Lineage and Surface Map

**Status:** Discovery artifact  
**Recorded:** 2026-09-28  
**Observed repository ref:** `42768eb3ace14a94d8bb3ef85be862c3f132f42e`  
**Purpose:** Establish where graph, GRAFT, GRAFT+, and GRAFT1st behavior exists inside Ajenda before any refactor or feature integration.

This is an inventory artifact, not a runtime contract and not an authorization decision. It records observed implementation, validation, workflow, and documentation surfaces. It does not claim that every graph finding is repaired or that GRAFT+ is generally superior.

## Executive finding

Ajenda contains one canonical dependency-graph lineage with multiple consumers. It does not contain three independent graph engines.

```text
canonical dependency graph
        |
        +--> GRAFT+ build and proof workflow
        |       +--> impact / blast radius
        |       +--> invariant and proof selection
        |       +--> completeness / CI gates
        |       +--> runtime-artifact reconciliation
        |
        +--> bounded runtime admission integrity
        |       +--> mission admission check
        |       +--> read-only runtime evidence projection
        |
        +--> semantic/runtime inventories

separate declarative layer:
GRAFT1st RevOps/CRM contract package

separate Ajenda intelligence layer:
knowledge retrieval, applicability, and decision support
```

## Measured canonical graph snapshot

The graph was generated read-only to `/tmp/ajenda-canonical-graph.json` using `scripts/validation/build_dependency_graph.py`.

| Measure | Observed value |
|---|---:|
| Graph nodes | 1,548 |
| Graph edges | 4,482 |
| Invariants | 16 |
| Semantic findings | 21 |
| Graph-tooling modules represented | 32 |
| Graph workflows represented | 12 |
| Test modules | 526 |
| Production Python modules | 423 |
| Frontend modules | 115 |
| Runtime actions | 53 |
| Runtime artifacts | 30 |

These values are a discovery snapshot, not a persisted product claim. Re-run the builder when the repository changes.

## Surface inventory

### Canonical graph source and model

| Surface | Location | Role | Authority classification |
|---|---|---|---|
| Graph builder | `scripts/validation/build_dependency_graph.py` | Generates source, semantic, migration, runtime, egress, and state-resource topology | Diagnostic/build authority only |
| Semantic overlay | `docs/contracts/dependency-graph.overlay.v1.json` | Records relationships imports cannot safely infer | Contract metadata; not runtime authority |
| Graph architecture contract | `docs/architecture/dependency-graph.md` | Defines node/edge semantics and proof boundaries | Documentation contract |
| Architecture decision | `docs/architecture/graph-architecture-decision.md` | Consolidates graph decisions | Documentation/evidence |
| Function graph | `docs/architecture/mission-composition-function-graph.md` | Adds function-level composition diagnostics | Diagnostic only |

### GRAFT+ workflow and non-runtime artifacts

| Surface | Locations | Role |
|---|---|---|
| Workflow definition | `docs/development/GRAFT_PLUS_WORKFLOW.md` | UPG/LAP, graph, impact, proof, runtime-artifact, and reconciliation procedure |
| Impact analysis | `scripts/validation/graph_impact_analysis.py` | Changed-file consumers, dependencies, risks, invariants, tests, unmapped files |
| Proof selection | `scripts/validation/graph_proof_selection.py` | Selects proof obligations from impact |
| Completeness audit | `scripts/validation/graph_completeness_audit.py` | Detects graph and semantic gaps |
| Architecture decision | `scripts/validation/graph_architecture_decision.py` | Emits graph-backed decision evidence |
| GRAFT+ gate | `scripts/validation/graft_plus_gate.py` | Coordinates mission-contract and graph validation gates |
| Runtime-contract inventories/adjudicators | `scripts/validation/graph_runtime_*.py` | Compare declared contracts with source and runtime evidence; do not execute work |
| CI workflows | `.github/workflows/dependency-graph.yml`, `graft-runtime-contract-adjudication.yml`, `graph-selective-ci-shadow.yml`, and related workflows | Run graph and proof checks in CI |
| Human-readable artifacts | `artifacts/` outputs from validation and runtime proof | Preserve decisions, findings, proof, and runtime observations |

### Runtime-facing GRAFT consumers

| Call path | Role | Boundary |
|---|---|---|
| `backend/api/routes/mission.py` → `backend/services/mission_graph_integrity.py` | Fail-closed mission admission integrity check | Does not dispatch, grant credentials, or bypass `TaskDispatcher` |
| `backend/services/mission_runtime_evidence_projection.py` | Read-only projection of persisted mission/runtime facts for GRAFT review | Does not adjudicate or execute |
| `backend/api/routes/mission_deliverable.py` | Exposes runtime facts for review | Tenant/auth/evidence boundaries remain authoritative |
| Runtime graph-contract validators | Compare selected jobs/actions/artifacts with declared contracts | Diagnostic/admission evidence only |

This means GRAFT is not exclusively development-only inside Ajenda. A bounded integrity check participates in mission admission, while the rest of the graph remains diagnostic and proof-oriented.

### GRAFT1st surfaces

| Surface | Location | Role |
|---|---|---|
| Contract package | `backend/services/vertical_ops/graft1st_contracts.py` | Declarative RevOps/CRM node, edge, adjudication, and applicability contracts |
| Know-how coupling | `backend/services/mission_composition/vertical_know_how.py` | Carries GRAFT1st package identity/version in RevOps know-how |
| CRM action coupling | `backend/services/tools/crm_actions.py` | Uses contract types for governed CRM behavior |
| Fixtures/tests | `tests/fixtures/graft1st/`, `tests/unit/services/test_graft1st_contracts.py` | Contract and reconciliation proof |

GRAFT1st here is a declarative contract package, not the repository graph engine and not a runtime authority grant.

### Related Ajenda intelligence surfaces

| Surface | Location | Role |
|---|---|---|
| Applicability | `backend/services/knowledge/knowledge_applicability.py` | Deterministic typed applicability evaluation |
| Decision support | `backend/services/knowledge/knowledge_decision_support.py` | Bounded support evidence for decision authority |
| Knowledge actions/manifests | `backend/services/tools/knowledge_actions.py`, `backend/services/abilities/knowledge_applicability_manifests.py` | Governed ability/action contracts |

These are Ajenda intelligence/composition layers. They are inventoried by the graph but are not GRAFT itself.

## Authority classification

| Category | Can inspect/map? | Can influence composition/evaluation? | Can execute, dispatch, grant credentials, or approve? |
|---|---:|---:|---:|
| Canonical graph | Yes | Indirectly, through proof selection and diagnostics | No |
| GRAFT+ workflow | Yes | Yes, as change/proof guidance | No |
| Runtime integrity check | Yes | Yes, by fail-closed admission result | No |
| Runtime evidence projection | Yes | Review only | No |
| GRAFT1st RevOps contracts | Yes | Yes, as declarative composition constraints | No |
| Existing runtime authority | N/A | N/A | Yes, through existing governed paths only |

## Known discovery gaps

1. The exact call-chain and ownership map for every graph-tooling module has not yet been written.
2. The runtime admission check and runtime evidence projection need a dedicated source-to-artifact trace.
3. The GRAFT1st RevOps contract package needs an intentionality review: which behavior is required, which emerged from adoption, and which is historical compatibility.
4. Generated artifacts and their retention/freshness rules need an inventory separate from source scripts.
5. Graph findings are not equivalent to study findings; the R&D `rd-program` record explicitly keeps those categories separate.
6. No refactor, removal, or authority expansion is authorized by this discovery artifact.

## Next discovery step

Before integrating new onboarding or Contacts behavior, produce a second artifact with exact call chains for:

1. graph build → overlay → impact/proof;
2. graph/runtime integrity → mission admission;
3. runtime evidence projection → human-readable artifact;
4. GRAFT1st contract → RevOps composition → CRM action validation;
5. graph findings → selected tests and CI workflows.

Only after those traces are reviewed should we decide which surfaces to preserve, rename, separate, or intentionally extend.
