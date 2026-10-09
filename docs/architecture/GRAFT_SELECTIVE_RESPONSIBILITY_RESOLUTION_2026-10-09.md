# G.R.A.F.T. Selective Responsibility Resolution — 2026-10-09

## Purpose

This change increases G.R.A.F.T. resolution only where the next Ajenda filesystem stabilization pass needs responsibility-level evidence.

The canonical graph remains module-first. The consuming model remains the architect and planner. G.R.A.F.T. remains the observation/relationship instrument.

## Why this instrument change is necessary

The next coordinated stabilization pass spans five high-pressure areas:

1. `backend/services/worker_runtime_service.py`
2. `backend/api/routes/mission.py`
3. `backend/api/routes/ability_runtime.py`
4. `backend/services/mission_composition/revops_deliverable.py`
5. the web/sales/GTM action implementation cluster

Module-level topology is sufficient to establish that these files are central, but not sufficient to distinguish the internal responsibilities that must move together while preserving stable public/runtime boundaries.

Before this change, the selective function layer covered mission composition top-level functions only. It could not directly express:

- `WorkerRuntimeService` method ownership or method-to-method calls;
- route-handler identity for the large mission and ability-runtime API files;
- runtime action-to-handler implementation binding;
- selected method-level test coverage;
- nested runtime handlers such as `gtm.social_publish`.

## Instrument adjustment

The selective layer now adds resolution for the architecture-critical surfaces above while leaving the rest of the repository module-first.

New source-backed relationships include:

- top-level function nodes;
- class-qualified method nodes;
- nested local function nodes when they carry selected runtime responsibility;
- `calls_function` between selected symbols;
- `http_route -> handler` via `handled_by`;
- `action:<name> -> handler` via `implemented_by`;
- direct selected test-to-function/method edges.

FastAPI route identity is derived from the selected module's `APIRouter(prefix=...)` plus the route decorator method/path.

Runtime action-handler identity is derived from `ActionDefinition(name=..., handler=...)`.

## Explicit non-goals

This change does not:

- expand every Python function in Ajenda into the canonical graph;
- calculate architecture or complexity scores;
- decide how a file must be refactored;
- grant merge or execution authority;
- infer runtime activation from static registration;
- replace full pytest, integration, runtime, or invariant proof.

## Intended use for the next stabilization pass

The consuming model will use the enriched artifact to compare its architectural assumptions against observed method/route/action/test relationships across the five target areas.

The plan should then be crystallized from:

`model architectural hypothesis -> G.R.A.F.T. responsibility evidence -> discrepancy reconciliation -> one cohesive filesystem stabilization PR -> regenerated G.R.A.F.T. -> full proof`

The graph is allowed to increase the scope of the product refactor if the new relationships show that a responsibility cannot be moved coherently in isolation.

## Acceptance

The instrument upgrade is acceptable only if:

- canonical node identity remains unique;
- every new edge endpoint is defined;
- existing mission-composition function identity remains stable;
- selected WorkerRuntimeService methods are represented with class-qualified identity;
- selected FastAPI routes are bound to their handlers;
- selected runtime actions are bound to their handlers;
- selected method tests receive direct supplemental test edges;
- completeness/architecture decision remains clear;
- Ruff, format, mypy, graph tests, and repository CI remain green.

This document records the Ajenda-side instrument change only. Research interpretation belongs in `1devteam/rd-program`.
