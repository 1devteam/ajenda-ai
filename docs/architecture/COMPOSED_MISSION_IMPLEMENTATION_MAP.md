# Composed Mission Implementation Map

This map is derived from the canonical dependency graph and the implementation entry points. It separates persisted contracts from runtime state changes.

```mermaid
flowchart LR
    U[Operator instruction] --> C[POST /v1/missions/compose\nmission_composition.py]
    C --> P[(MissionCompositionRecord\nproposal only)]
    P --> F[POST /v1/missions/proposals/{id}/confirm\nmission_composition.py]
    F --> M[(Mission intake + plan +\ntask graph metadata)]
    M --> K[POST /v1/missions/{id}/compile\nmission.py]
    K --> G[(Server-owned graph\nwith identity/fingerprint)]
    G --> R[POST /v1/missions/{id}/materialize-graph\nmission.py]
    R --> A[(Graph materialization\nmetadata)]
    A --> T[POST /v1/missions/{id}/runtime-task-materialization\nMissionRuntimeTaskMaterializationService]
    T --> E[(ExecutionTask rows\nplanned)]
    E --> Q[POST /v1/missions/{id}/runtime-queue-admission\nMissionRuntimeQueueAdmissionService]
    Q --> D[ExecutionCoordinator.queue_task]
    D --> W[Worker claim/start/run\nlease owner]
    W --> O[(Outcome, evidence,\nCRM projection)]

    F -. missing product orchestration edge .-> K
    K -. missing product orchestration edge .-> R
    R -. missing product orchestration edge .-> T
```

## Implementation status

| Boundary | Source of truth | Status | Proof surface |
|---|---|---|---|
| Compose | `backend/api/routes/mission_composition.py` + composition service | Implemented; read-only proposal | `tests/contract/api/test_mission_composition_routes.py` |
| Confirm | composition service | Implemented; persists intake/plan/graph, does not queue | same contract test |
| Compile | `backend/api/routes/mission.py` + `MissionCompositionService.compile_for_mission` | Implemented; explicit server-owned compilation | mission compile contract/integration tests |
| Graph materialization | `POST /{mission_id}/materialize-graph` | Implemented; metadata only | task-graph runtime boundary contracts |
| Runtime task materialization | `MissionRuntimeTaskMaterializationService` | Implemented; creates `ExecutionTask` rows | `tests/integration/runtime/test_task_graph_runtime_admission_real.py` |
| Queue admission | `MissionRuntimeQueueAdmissionService` | Implemented; sole queue authority | `tests/contract/api/test_mission_queue_contract.py` |
| Worker execution | `TaskDispatcher` / `WorkerRuntimeService` | Implemented; lease-bound | staging/live runtime proof |
| Confirm-to-runtime orchestration | product/API workflow | **Missing**; confirmed proposals can remain `planned` until the explicit compile/materialize/admit sequence is invoked | observed terminal mission `0d07c0f1-fda9-4584-a816-e7594042ea91` |

## Graph-derived invariants

- Tenant identity must remain fixed across proposal, mission, graph, task, queue, lease, and evidence records.
- Compilation and materialization must not grant execution authority or bypass queue admission.
- Every runtime task must be created from the current graph fingerprint and materialization reference.
- Queue admission must continue through `ExecutionCoordinator`; worker execution must continue through lease ownership.
- Clarification-required composition must fail closed and must not materialize or queue tasks.

## Next implementation slice

Add an explicit, idempotent orchestration command/API that invokes compile → graph materialization → runtime task materialization → queue admission, with durable receipts for each boundary and compensation when a downstream boundary fails. Keep the existing endpoints independently callable for review and recovery.
