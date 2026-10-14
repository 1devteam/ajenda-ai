# Ajenda Intelligence and Runtime Workflow — G.R.A.F.T. Artifact

**Audited implementation commit:** `6d3fafc433651101ea6a4f87ca4629b5876b822e`

**Authority:** diagnostic. This artifact does not queue, authorize, execute, or mutate Ajenda runtime state.

**Artifact manifest:** `docs/validation/graft-intelligence-runtime-6d3fafc4/manifest.json`

## Canonical generated material

| Artifact | Purpose | Digest |
|---|---|---|
| `canonical-dependency-graph.v1.json` | Complete G.R.A.F.T. structural and semantic graph | `sha256:77132735734056eb8f2578e16d22b8c36b5b2d42e38209d53190f5c9f90a3056` |
| `dependency-graph.ascii.v2.txt` | Compact, reproducible rendering of the same graph | `sha256:7c505699931c0abde70ff49079d81e2b69525f65e2457beaf9bda4b435b0f506` |
| `source-topology.v1.json` | Source concentration and relationship topology | `sha256:40e55bff3fedc3cc6f5b093cfeae7b6b9ba18cb0248c25845b1de42bc7813075` |

The canonical graph contains **2,088 nodes** and **5,776 edges** across **1,291 source-backed files**; **613** are production or frontend files. The graph’s own schema is `1.4`. The manifest binds its digest to the audited commit because the current generated graph does not embed commit/timestamp/digest metadata.

## Implemented end-to-end workflow

```text
Customer / tenant principal
  │
  ├─ mission intake ────────────────> Mission(PLANNED) + intake contract metadata
  │                                      backend/api/routes/mission.py:create_mission
  │
  └─ compose request ───────────────> MissionCompositionService.compose
                                         proposal / interpretation / plan candidates
                                         backend/api/routes/mission_composition.py:compose_mission
  │
confirm composition ────────────────> governed Mission + plan + task graph + deliverable state
                                         (no queueing)
                                         MissionCompositionService.confirm
  │
runtime admission ──────────────────> tenant/permission checks + current graph/materialization
                                         + outcome-review + G.R.A.F.T. admission integrity
                                         persisted admission metadata only
  │
task materialization ───────────────> tenant-scoped ExecutionTask rows
                                         action registry resolution; side-effect work held for review
  │
runtime queue admission ────────────> ExecutionCoordinator + QueueAdapter
                                         task becomes queued / pending-review / denied
  │
worker claim/start ─────────────────> queue claim + tenant/task checks + WorkerLease
                                         task claimed → running
  │
TaskDispatcher ─────────────────────> registered handler → governed tool/provider invocation
  │
complete/fail ──────────────────────> task/lease transition + lineage + EvidenceRecord + audit
                                         + deliverable completion/read state + queue cleanup
  │
customer read models ───────────────> mission lifecycle, deliverable, runtime evidence
  │
continuous assurance ───────────────> periodic read-only tenant reconciliation → AssuranceSnapshot
```

## Workflow stages and source-backed contracts

| Stage | Implemented owner | Input → output | Runtime authority | G.R.A.F.T. coverage | Evidence / failure boundary |
|---|---|---|---|---|---|
| Identity and tenant context | route dependencies and permission guards | Request principal + tenant → tenant-scoped DB session/permission decision | Enforce | Tenant-boundary and authority relationship types | Route must reject mismatched tenant or missing permission; static graph does not prove live RLS/session activation. |
| Mission intake | `backend/api/routes/mission.py:create_mission` | Objective, criteria, constraints, budgets, limits → `Mission(PLANNED)` + intake metadata | Mutate | Mission route, contract, persistence relationships | Intake quality, quota and budget checks occur before persistence; this path does not queue work. |
| Interpretation and composition | `backend/services/mission_composition/service.py`; proposal/compile/confirmation phases | Natural-language instruction → composition proposal, interpreted requirements, candidate jobs/plan/graph | Declarative then governed mutation at confirmation | Composition services, job catalog, resolver, semantic nodes | Proposal is explicitly non-runtime. Uncertain interpretation must remain proposal/error rather than execution authority. |
| Confirmation | `MissionCompositionConfirmationPhase.confirm`; `POST /proposals/{proposal_id}/confirm` | Confirmed proposal → canonical mission intake, plan, task graph, deliverable runtime state | Mutate, not execute | Calls/imports, graph/contract relationships | Requires mission-create and mission-manage permission; canonical queueing remains separate. |
| Graph admission | `backend/api/routes/mission.py:admit_mission_graph_to_runtime`; `mission_graph_integrity.py` | Task graph + materialization + current review/tenant authority → admission metadata or HTTP 400 | Enforce admission; mutate metadata | Runtime-admission coverage inventory and G.R.A.F.T. integrity read model | Graph/materialization fingerprint mismatch, missing graph, rejected review, or non-clear G.R.A.F.T. report blocks admission. |
| Task materialization | `MissionRuntimeTaskMaterializationService.materialize`; mission bridge materialization | Current admitted graph → planned `ExecutionTask` rows + materialization metadata | Mutate planned runtime state | Admission-to-materialization source relationships | Runtime readiness and references must match. Action registry resolves declared actions; side-effecting action candidates require review. |
| Queue admission | `MissionRuntimeQueueAdmissionService.admit`; `ExecutionCoordinator.queue_task` | Planned eligible task → queue dispatch + queued task, pending-review, or denial | Enforce and mutate queue/runtime state | Queue boundary and coordinator dependencies | Only materialized/current tasks are admitted; denial/blockers are persisted in admission metadata. |
| Claim and start | `WorkerRuntimeService.claim_next_task` / `start_execution` | Queue message → tenant-owned task + lease → running task | Enforce/mutate | Worker/queue/lease graph relationships | Orphan payloads are quarantined/audited; stale clarification intake cancels task; lease ownership is required. |
| Dispatch and tools | `TaskDispatcher.execute`; handler registry; `ActionRegistry`/tool runtime authority | Running lease-owned task → handler result or failure | Execute external/provider effects through registered governed actions | Runtime actions, selected actions, network-egress relationships | Dispatcher validates handler result and calls canonical complete/fail path. Static graph cannot prove provider availability or actual external result. |
| Completion, failure, and outcome state | `WorkerRuntimeService.complete` / `fail` | Task result or error → terminal state, lease release, lineage, evidence, audit, artifact refs, queue cleanup | Mutate/recover | Task/evidence/lineage/artifact relationships | Completion requires declared output contract. Failure persists failure evidence. Queue-cleanup failure is separately recorded. |
| Customer-visible results | mission deliverable and read-model routes | Canonical mission/task/evidence state → deliverable, lifecycle, runtime-evidence read | Read-only | Read-model and artifact edges | A successful task is not automatically a fulfilled business outcome; deliverable/acceptance state remains distinct. |
| Continuous assurance | `ContinuousAssuranceService`; `assurance_loop` | Tenant runtime facts → append-only `AssuranceSnapshot` + metrics | Observe/evaluate only | G.R.A.F.T. runtime projection and assurance persistence edges | Separate process/history, but it shares G.R.A.F.T. projection semantics and cannot independently validate a defect in that shared projection. |

## Authority boundaries

| Boundary | Permitted role | Prohibited role |
|---|---|---|
| Composition proposal | Interpret, plan, select declarative jobs | Queue, lease, dispatch, or call providers |
| G.R.A.F.T. graph and runtime evidence projection | Observe, evaluate, select proof, report contradictions | Register handlers, resolve runtime credentials, dispatch tasks, mutate tenant state |
| Admission integrity | Block unsafe admission | Provision new authority or execute work |
| Materialization | Create planned task representation | Queue or dispatch directly |
| Queue admission / coordinator | Admit eligible task to queue | Bypass task/tenant/runtime state rules |
| Worker runtime / dispatcher | Claim, start, execute, complete/fail under lease | Execute without tenant scope/lease or silently return without terminal handling |
| Continuous assurance | Append observation history and metrics | Change mission, task, lease, queue, approval, credential, provider, or business state |

## Structural concentration and change impact

The source topology identifies the following high-concentration workflow owners:

| Source | Production relationships | Interpretation |
|---|---:|---|
| `backend/services/mission_composition/job_catalog.py` | 531 | Primary declarative job/action and composition dependency hub. |
| `backend/api/routes/mission.py` | 321 | Mission lifecycle, graph admission, and compatibility-path concentration. |
| `backend/services/mission_composition/capability_resolver.py` | 201 | Capability/action resolution boundary. |
| `backend/services/worker_runtime_service.py` | 159 | Lease, terminal transitions, evidence, and queue reconciliation boundary. |
| `backend/api/routes/mission_deliverable.py` | 83 | Customer-visible outcome and runtime-evidence read boundary. |

These counts justify heightened G.R.A.F.T. impact analysis before changes. They do **not** alone justify refactoring.

## What this artifact proves and does not prove

### Demonstrated by source and local validation

- Static dependency, semantic, action, artifact, queue, tenant, and authority relationships represented by the generated G.R.A.F.T. graph.
- The graph generator and G.R.A.F.T. drift controls completed successfully on the audited implementation.
- Runtime/assurance tests recorded in the reconciliation companion passed at unit level.
- The design separates composition, admission, materialization, queueing, dispatch, and assurance rather than granting a single component all powers.

### Not demonstrated here

- A real provider credential acquisition or external provider action.
- Production queue delivery, concurrent worker behavior, crash recovery, or actual tenant isolation under deployed roles.
- That every statically mapped call edge executes in a given mission.
- That an individual customer mission is semantically fulfilled; this requires a tenant-scoped runtime chain and outcome evidence.

Docker/Testcontainers-backed assurance integration was unavailable in this execution environment and remains an explicit runtime-verification gap.

## Reproduction

```bash
python scripts/validation/build_dependency_graph.py \
  --output /tmp/ajenda-intelligence-runtime-634735e4.json
python scripts/validation/graph_ascii_v2.py \
  --output /tmp/ajenda-intelligence-runtime-634735e4.ascii.txt \
  --preview-lines 80
python scripts/validation/graph_source_topology.py \
  --output /tmp/ajenda-intelligence-runtime-634735e4.topology.json \
  --top 50
sha256sum /tmp/ajenda-intelligence-runtime-634735e4.*
```

Use `docs/development/GRAFT_PLUS_WORKFLOW.md` for changed-file impact and proof selection before altering any mapped runtime owner.
