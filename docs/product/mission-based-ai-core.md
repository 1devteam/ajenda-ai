# Mission-Based AI Core

## Definition

Ajenda AI is Mission-Based AI.

Companies define outcomes as missions, and Ajenda converts those missions into structured, governed machine-performed work.

Ajenda is:

- outcome-first at the user layer
- system-first internally
- governed at the runtime layer
- transparent and modifiable for technical operators

Core rule:

> Human speaks outcome. Ajenda thinks system. Runtime executes safely.

---

# Why Mission-Based AI

Most systems are centered around:

- workflows
- triggers
- records
- integrations
- chats
- tasks
- agents

Ajenda is centered around the mission.

A mission owns:

- desired outcome
- constraints
- priorities
- success criteria
- plan
- task graph
- required capabilities
- approvals
- evidence
- outcomes
- memory candidates

The mission is the main actor.

Workers, modules, tools, and integrations exist to help complete the mission.

---

# User-Level Model

Ajenda should feel outcome-first to users.

Users should be able to define goals in business language:

- find qualified prospects
- research a market
- recover missed opportunities
- process inbound requests
- prepare reports
- organize follow-up
- automate repetitive operations

The user should not need to understand:

- queues
- leases
- retries
- task dispatch
- orchestration internals
- worker coordination
- runtime recovery

Ajenda converts outcomes into structured mission execution.

Business Profile context supports this user model without replacing it. A simple onboarding flow may capture reusable business facts once, and later missions may use that context to reduce repeated clarification. Business Profile remains additive context above mission intake: the user still speaks in outcomes, Ajenda still builds the Mission Brief and mission intake structure, and runtime still executes only through governed contracts. Durable profile updates must be user-approved; if a user dismisses or declines a suggested update, Ajenda keeps going with no profile update and the information remains only in the current mission context.

See `docs/product/business-profile-and-mission-context.md` for the Business Profile, Mission Brief, and profile update suggestion contract.

---

# Internal System Model

Internally, Ajenda remains system-first.

Outcomes are converted into structured execution objects:

- Mission
- MissionPlan
- MissionConstraint
- MissionTaskGraph
- CapabilitySelection
- WorkerTask
- EvidenceItem
- OutcomeReview
- MemoryCandidate

Ajenda internally coordinates:

- tasks
- queues
- workers
- leases
- retries
- recovery
- approvals
- audit
- evidence
- memory

This keeps execution reliable, inspectable, and recoverable.

---

# Operator Transparency And Modification

Ajenda should support both non-technical users and technical operators.

## Non-technical users

Non-technical users primarily interact with:

- missions
- outcomes
- progress
- approvals
- evidence summaries
- recommended next actions

## Technical operators

Technical users should be able to open the hood and inspect the full execution system:

- mission plan
- task graph
- worker assignments
- capability calls
- queue state
- lease state
- retries and recovery
- evidence
- audit trail
- validation artifacts
- execution logs
- memory updates

Technical users should also be able to refine execution behavior safely, including:

- task ordering
- capability selection
- planning depth
- retry behavior
- confidence thresholds
- approval gates
- model/provider selection
- memory usage
- allowed tools/modules
- risk tolerance
- decomposition strategy
- cost/runtime budgets

Ajenda should be simple by default and transparent by design.

---

# Governance Layer

Governance is not a product module.

Governance is the platform control layer surrounding all execution.

Governance includes:

- audit
- policy
- approvals
- tenant boundaries
- recovery
- observability
- release validation
- execution constraints

Governance exists across all missions, workers, and modules.

---

# Capability And Module Model

Modules are mission capabilities.

Modules are not the center of the platform.

Examples:

- research
- opportunity discovery
- communications/outreach
- iPaaS/connectors
- documents
- analytics
- scheduling
- knowledge retrieval
- reporting
- memory/intelligence
- relationship management

Missions should call registered capabilities rather than arbitrary execution.

---

# Capability Registry

Ajenda should support a capability registry.

Capabilities should declare:

- capability name
- task types provided
- input schema
- output schema
- required permissions/tools
- risk level
- approval requirements
- evidence produced
- evidence expectations
- execution constraints
- enabled/disabled state
- optional tenant scoping
- version/schema version

This allows new modules and capabilities to be added without restructuring the platform. Handler binding and runtime enforcement are separate future layers, not part of the registry contract itself.

---

# Core Execution Loop

The intended mission execution loop is:

1. Mission intake
2. Mission constraints and success criteria
3. Mission plan generation
4. Task graph creation
5. Capability selection
6. Worker execution
7. Evidence capture
8. Outcome review
9. Memory promotion
10. Retrieval and recall contracts

---

# Existing Architecture Fit

Ajenda already contains a strong governed runtime foundation.

## Existing strengths

Current architecture already supports:

- queue-backed execution
- worker leases
- retries and recovery
- dead-letter handling
- audit/governance concepts
- tenant/auth boundaries
- observability
- validation artifacts
- runtime execution coordination

## Missing top-layer systems

The primary missing systems are:

- task graph generation
- capability registry
- real worker skills
- evidence item model
- outcome review
- memory promotion
- retrieval and recall governance

Ajenda is not being rebuilt.

The mission-based top layer is being added over the existing governed runtime foundation.

---


## Mission Intake V1 Implementation

Mission intake is now the first product-layer contract above the governed runtime foundation. `POST /v1/missions` accepts a tenant-authenticated business objective and structured planning inputs, creates a tenant-owned `Mission` in `planned` status, and persists the intake envelope in `Mission.metadata_json["mission_intake"]` with `schema_version = 1`.

First-class in this block:

- objective;
- success criteria;
- constraints;
- operator notes and context;
- priority;
- approval-required expectations;
- budget and scope limits;
- allowed actions and tools;
- compliance category and jurisdiction aligned with existing mission columns.

Deferred by design:

- planner execution;
- dynamic decomposition;
- task graph execution/materialization;
- capability registry enforcement;
- runtime dispatch changes;
- worker handler changes;
- outcome review;
- memory promotion.

Mission intake does not queue work. Runtime admission remains explicit through the existing mission/task queue routes, and queue-backed execution, leases, recovery, and compliance review behavior remain governed by the current runtime layer. Tenant ownership is taken from the validated tenant/auth context, not from request body input.

## Mission Planning V1 Contracts

Mission planning contracts now define durable, tenant-owned execution intent between mission intake and future task graph generation. `POST /v1/missions/{mission_id}/plan` creates or returns the idempotent active `MissionPlan` record for a tenant-owned mission, and `GET /v1/missions/{mission_id}/plan` reads the tenant-owned plan without creating one as a side effect. Legacy `PUT /v1/missions/{mission_id}/plan` metadata upsert remains as a compatibility contract for older metadata-only plan shape, but the durable planning layer is the `mission_plans` table with `schema_version = 1`.

First-class in this block:

- stable plan identity and tenant ownership;
- mission association;
- active plan statuses `draft` and `ready`;
- inactive lifecycle statuses `superseded` and `cancelled`;
- objectives;
- constraints;
- assumptions;
- acceptance criteria;
- typed planned steps;
- risk notes;
- deterministic JSON-safe metadata.

Lifecycle is explicit and intentionally narrow before task graph work exists. Allowed status transitions are `draft -> ready`, `draft -> cancelled`, `ready -> superseded`, and `ready -> cancelled`. The create endpoint always creates new durable plans as `draft`; clients cannot create `ready`, `superseded`, or `cancelled` plans directly, and lifecycle changes require a future explicit transition endpoint or service rather than create-time status injection. Idempotent create returns the existing active plan unchanged, even when a later create request sends different metadata.

Mission plan metadata reads support only `schema_version = 1`. V1 reads normalize deterministic defaults for omitted optional lists, validate JSON safety, and fail closed for unsupported future schema versions instead of guessing compatibility. Planned steps are lightweight planning records, not task graph nodes or execution tasks: each step requires a positive `sequence`, non-empty `title`, non-empty `description`, dependency references in `depends_on`, non-empty `expected_output`, and JSON-safe `metadata`; unknown planned-step fields are rejected.

Mission planning remains a contract layer only. Persisting a plan does not queue work, create execution tasks, generate a task graph, enforce a capability registry, promote memory, run outcome review, dispatch workers, mutate worker leases, or modify runtime recovery/orchestration. Runtime authority remains with the governed queue, lease, policy, recovery, and validation layers.

## Capability Registry V1 Contracts

Capability registry contracts now define durable declarations that future planners and task graphs can reference safely. `POST /v1/capabilities`, `PATCH /v1/capabilities/{capability_id}`, `GET /v1/capabilities`, and `GET /v1/capabilities/{capability_id}` persist and read capability metadata through tenant-authenticated route boundaries. Tenant-scoped capabilities are owned by the request tenant; global capabilities are visible to tenants when seeded through repository/migration/admin-safe paths.

First-class in this block:

- capability name and description;
- supported task types;
- input and output schema hints;
- required permissions and tools;
- risk level;
- approval requirements;
- evidence expectations;
- execution constraints;
- enabled/disabled state;
- tenant or global scope;
- version and schema version.

Capability registry remains a contract layer only. Persisting or updating a capability does not execute work, register worker handlers, bind runtime dispatch, generate DAGs, select capabilities for a plan, enforce routing, or modify queue/recovery behavior. Capability execution and enforcement remain future layers above the governed runtime foundation.


## Task Graph Contracts V1

Task graph contracts now define durable, tenant-scoped planned work structure between mission planning and future materialization/execution. `POST /v1/missions/{mission_id}/task-graph` and `PUT /v1/missions/{mission_id}/task-graph` share one full-replacement write path, and `GET /v1/missions/{mission_id}/task-graph` reads the normalized contract back through the same tenant-scoped mission repository boundary. The graph is persisted additively and only in `Mission.metadata_json["mission_task_graph"]` with `schema_version = 1`.

First-class in this block:

- `schema_version = 1`, `graph_status = "draft"`, mission identity, graph version, and deterministic graph fingerprint;
- graph nodes keyed by non-empty unique `node_key` values and currently also echoing legacy-compatible `key` with the same value;
- graph edges from prerequisite `from_node_key` to dependent `to_node_key`;
- canonical `capability_reference` per node, requiring `capability_id` or `name`, plus a temporary `capability_references` single-item list for downstream compatibility;
- node input and output contracts;
- node and edge metadata plus graph-level metadata.

Task graph contracts remain a product-layer contract only. Persisting a graph validates shape, rejects unsupported fields, rejects duplicate or empty node keys, rejects edges pointing to missing nodes, rejects self-edges, rejects cycles, rejects unsupported schema versions, and rejects non-JSON-safe metadata/contracts. Writes are deterministic and idempotent: when the normalized incoming graph content equals the normalized stored graph content, mission metadata is not updated and the existing `mission_id`, `graph_version`, and `graph_fingerprint` are retained; otherwise the `mission_task_graph` metadata key is replaced, unrelated mission metadata is preserved, graph-dependent materialization/admission/task-materialization metadata is superseded through the existing supersession helpers, stale planned materialized tasks are cancelled through the existing cancellation helper, `graph_version` increments from the prior graph when available, and `graph_fingerprint` is recomputed from normalized graph content. Reads fail closed with 409 when stored graph metadata is invalid, while legacy schema_version=1 graphs produced by the prior writer are adapted into the normalized response shape so existing mission metadata remains readable. Persisting or reading a graph does not create `ExecutionTask` rows, queue work, call `MissionExecutor`, call `ExecutionCoordinator`, dispatch workers, mutate worker leases, enforce capability runtime behavior, or materialize the graph into runtime tasks. Runtime materialization and execution remain future layers above the governed runtime foundation.

## Planner-to-Graph Materialization V1 Contracts

Planner-to-graph materialization contracts now define durable metadata describing how a mission plan becomes a validated task graph using declared capabilities. `POST /v1/missions/{mission_id}/materialize-graph` creates or updates the metadata contract, and `GET /v1/missions/{mission_id}/materialization` reads it back through the same tenant-scoped mission repository boundary. The contract is persisted additively in `Mission.metadata_json["graph_materialization"]` with `schema_version = 1`.

First-class in this block:

- materialization status, source, source version, schema version, and version counter;
- planner provenance;
- capability-selection provenance;
- graph validation result summaries and checks;
- operator review/approval status;
- graph generation metadata and notes;
- deterministic compilation boundaries and fingerprints;
- timestamps for materialization and updates;
- graph reference version/fingerprint so consumers can detect stale materialization metadata.

Planner-to-graph materialization remains a contract layer only. Persisting materialization metadata may mark a mission task graph as materialized for planning continuity, but it does not create `ExecutionTask` rows, enqueue work, call `MissionExecutor`, call `ExecutionCoordinator`, dispatch workers, mutate worker leases, or enforce runtime capability routing. Runtime execution remains behind the explicit runtime admission and task materialization bridges.

## Runtime Admission Readiness V1 Contracts

The read-only runtime admission readiness gate is exposed at `GET /v1/missions/{mission_id}/runtime-readiness`. It evaluates the current mission task graph and graph materialization metadata for a tenant-owned mission and returns deterministic readiness status, blockers, warnings, admitted node keys, fingerprint/materialization references, and version markers. It does not create execution tasks, queue work, dispatch workers, execute nodes, call `MissionExecutor`, call `ExecutionCoordinator`, mutate leases, or invoke capability adapters. The response is read-only and intentionally separates product-layer graph readiness from runtime authority.

The runtime task materialization preview is exposed at `GET /v1/missions/{mission_id}/runtime-task-preview`. It reuses the readiness gate and, when the admitted graph is ready, returns deterministic preview rows for the selected graph nodes in admission order. Each preview row shows the future runtime task type, pending task state, graph node reference, capability/adapter references, materialization selection reference, dependency keys from task graph edges, and a safe payload envelope preview. The preview is read-only and pre-materialization only: it does not persist payloads, create `ExecutionTask` rows, enqueue work, call executors or coordinators, execute graph nodes, dispatch workers, or grant scheduler/runtime authority.

Execution task materialization contracts are exposed at `POST /v1/missions/{mission_id}/runtime-task-materialization` and `GET /v1/missions/{mission_id}/runtime-task-materialization`. The POST endpoint is explicit, tenant-scoped, and only proceeds when the same readiness and deterministic preview mapping are ready for the current graph/materialization/admission references. It creates planned `ExecutionTask` rows from the preview payload envelope, persists `Mission.metadata_json["runtime_task_materialization"]` with created task IDs and runtime-authority flags, and is idempotent for the same current bridge references. This bridge creates planned rows only: it does not enqueue work, dispatch workers, execute graph nodes, call `MissionExecutor`, call `ExecutionCoordinator`, invoke capability adapters, or remove/alter the existing `default_handler`. Graph execution remains future work above this materialization contract.

Runtime queue admission is exposed at `POST /v1/missions/{mission_id}/runtime-queue-admission`. It is an explicit, tenant-scoped runtime bridge for the current `runtime_task_materialization` metadata: the route locks the mission for the request tenant, reads the current materialized execution task IDs, admits only tenant/mission-owned planned tasks, treats already queued tasks as admitted, records blockers for missing, foreign, cancelled, completed, or otherwise non-queueable materialized tasks, checks quota before queueing newly eligible planned tasks, calls `ExecutionCoordinator.queue_task` for those eligible tasks, and persists `Mission.metadata_json["runtime_queue_admission"]` with the admitted, pending-review, denied, blocked, and materialized task IDs. This bridge mutates queue admission state and queue-backed task state, so it is runtime-authoritative for queue admission only. It does not create `ExecutionTask` rows, dispatch workers, execute graph nodes, call `MissionExecutor`, invoke the task dispatcher, run handlers/adapters, alter worker leases, or bypass policy, quota, tenant, or current-materialization checks.

Runtime dispatch readiness is exposed at `GET /v1/missions/{mission_id}/runtime-dispatch-readiness`. It is a tenant-scoped, read-only bridge contract over the current `runtime_task_materialization` and `runtime_queue_admission` metadata. The response verifies that current materialized task IDs are tenant/mission-owned queued `ExecutionTask` rows with explicit non-empty dispatcher `task_type` metadata, classifies planned, cancelled, running, completed, failed, dead-lettered, missing, and foreign rows, and returns ready/partial/blocked status with blockers and warnings. It does not create execution tasks, enqueue work, call `MissionExecutor`, call `ExecutionCoordinator`, dispatch workers, inspect adapter code, execute adapters, or mutate mission/task state.

Worker dispatch eligibility is exposed at `GET /v1/missions/{mission_id}/worker-dispatch-eligibility`. It is a tenant-scoped read-only bridge contract over current runtime dispatch readiness metadata and returns queued task candidates with deterministic worker identity, lease token, dispatcher task type, queue task id, and warnings for tasks that require operator/policy review before runtime claim/start/run admission. It does not claim tasks, create leases, start execution, enqueue work, dispatch workers, inspect adapter code, execute adapters, or mutate mission/task/lease state.

Worker claim preview is exposed at `GET /v1/missions/{mission_id}/worker-claim-preview`. It is a tenant-scoped read-only admission preview over current dispatch-eligible tasks. It derives deterministic lease candidates from queued execution tasks, existing active worker leases, queue task ids, graph node references, and mission/current admission references. It classifies candidates as claimable, already claimed, missing queue task id, review blocked, or state blocked; returns deterministic claim keys, worker ids, lease tokens, lease durations, and blockers; and persists nothing. It does not create leases, claim tasks, start execution, enqueue work, dispatch workers, run handlers/adapters, mutate mission/task/lease state, or bypass worker lease ownership.

Worker claim admission is exposed at `POST /v1/missions/{mission_id}/worker-claim-admission` and `GET /v1/missions/{mission_id}/worker-claim-admission`. The POST endpoint is an explicit tenant-scoped worker-runtime bridge over the current worker claim preview. It establishes worker lease ownership for claimable queued tasks through `WorkerRuntimeService.claim_next_task`, performs bounded queued-to-claimed state transitions, records admitted/blocked/failed lease rows in `Mission.metadata_json["worker_claim_admission"]`, and is idempotent for current preview references. The GET endpoint reads the latest admission metadata without creating leases, claiming tasks, starting execution, dispatching workers, running handlers/adapters, or mutating runtime state.
