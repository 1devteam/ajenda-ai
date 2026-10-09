# Five-Surface Filesystem Stabilization — 2026-10-09

## Purpose

This refactor stabilizes the highest-pressure Ajenda Python surfaces identified after the mission-composition decomposition sequence.

The architecture rule is:

> Preserve externally meaningful authority and contract boundaries; move responsibility ownership underneath them.

The change is intentionally one cohesive PR because the enriched G.R.A.F.T. artifact shows the seven original files participate in one broad proof surface rather than seven independent local cleanups.

## Pre-change G.R.A.F.T. basis

Canonical graph after selective responsibility-resolution upgrade:

- graph nodes: 1,936
- graph edges: 5,438
- target responsibility nodes across the seven original files: 249
- transitive upstream consumers from those target nodes: approximately 551
- downstream prerequisites: approximately 292
- impacted test modules: approximately 190

The target files and their pre-change topology:

| Surface | Lines | Production incident edges | Neighbor sources | Neighbor namespaces |
| --- | ---: | ---: | ---: | ---: |
| worker_runtime_service.py | 1,317 | 172 | 50 | 11 |
| mission.py | 2,182 | 401 | 54 | 11 |
| ability_runtime.py | 976 | 175 | 34 | 11 |
| revops_deliverable.py | 945 | 115 | 13 | 5 |
| web_actions.py | 1,291 | 74 | 11 | 6 |
| sales_actions.py | 1,235 | 132 | 15 | 11 |
| gtm_actions.py | 1,073 | 135 | 19 | 8 |

The G.R.A.F.T. responsibility layer also exposed:

- WorkerRuntimeService has direct state-transition method/test relationships that must remain stable.
- Mission and ability-runtime route identity must stay attached to their existing FastAPI handlers.
- RevOps already has a natural public assembler boundary.
- GTM runtime handlers were nested inside one registration function, hiding implementation ownership.
- Runtime action identity can now be proven through `action:<name> -> handler` edges.

## Target topology

### Worker runtime

Stable authority:
- `WorkerRuntimeService`
- claim / heartbeat / start / complete / fail / release / cancellation entry points

Extracted responsibilities:
- output and acceptance contracts
- mission completion/acceptance rollup
- terminal queue reconciliation
- high-risk outcome-review bridge

The service remains the runtime transaction/state-transition authority.

### Mission API

Stable authority:
- all existing `/missions` route handlers and decorators

Extracted responsibilities:
- task-graph identity/fingerprinting/versioning
- graph/materialization/runtime supersession
- mission/plan/graph/timeline/lifecycle read-model projection

The route file remains HTTP orchestration rather than becoming a second service layer.

### Ability runtime API

Stable authority:
- all existing `/ability-runtime` handlers
- `launch_task` orchestration

Extracted responsibilities:
- request/response contracts
- exposed-action policy
- principal/autonomy/runtime authority
- task metadata and evidence/lineage/audit projection

### RevOps deliverable

Stable authority:
- `assemble_revops_mission_deliverable`

Extracted responsibilities:
- typed read contracts
- prospect/draft assembly
- artifact/runtime validation
- approval-state projection
- side-effect receipts and limitations

All extracted modules remain descriptive/read-only.

### Runtime actions

Stable authority:
- `register_web_actions`
- `register_sales_actions`
- `register_gtm_actions`
- every existing action name, alias, side-effect classification, input schema, credential requirement, and handler semantics

Extracted implementation families:

Web:
- governed page/browser/open-write I/O
- public identity policy
- public identity verification
- contact observation

Sales:
- common provider/evidence
- records
- research/contact normalization
- qualification/scoring/recommendation
- follow-up/activity

GTM:
- common provider/credential/evidence helpers
- lead enrichment
- drafts
- email send/check
- CRM upsert
- social publish

## Concentrated-file reduction

The seven original hotspots move from a combined 9,026 lines to approximately 3,689 lines, a ~59% reduction in concentrated-file load.

The complete responsibility families total approximately 10,024 lines because imports, module contracts, and stable delegation seams become explicit. The goal is not fewer aggregate lines; the goal is bounded responsibility, lower edit collision, clearer authority, and graph-visible placement.

## G.R.A.F.T. continuity

The selective symbol inventory now follows bounded responsibility families rather than only the old exact hotspot filenames:

- `worker_runtime_*.py`
- `mission_*.py`
- `ability_runtime_*.py`
- `web_action_*.py`
- `sales_action_*.py`
- `gtm_action_*.py`

This preserves responsibility-level graph resolution after code moves.

## Non-goals

This refactor does not intentionally change:

- runtime authority
- tenant isolation
- route paths or HTTP methods
- action names or aliases
- provider credentials/egress authority
- mission queue/worker authority
- side-effect classifications
- artifact schemas
- acceptance semantics
- execution transaction boundaries

## Closure criteria

Merge only when:

1. Ruff lint and format pass.
2. Mypy passes.
3. Full unit/contract/deployment pytest passes with the existing coverage floor.
4. Integration pytest passes.
5. Migration and all Docker build legs pass.
6. Security, recovery, and live-runtime proof pass.
7. Canonical G.R.A.F.T. regenerates with no unintended unmapped production surfaces.
8. Every stable route and action remains bound to a handler.
9. Post-change topology demonstrates reduced responsibility concentration rather than merely displaced hotspots.
10. Predicted vs observed graph impact is recorded in the R&D program.
