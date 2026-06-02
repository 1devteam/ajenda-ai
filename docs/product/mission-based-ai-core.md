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

Planner-to-graph materialization remains a contract layer only. Persisting materialization metadata may validate mission ownership, the existence of a task graph, and referenced capability visibility, but it does not create `ExecutionTask` rows, queue work, call `MissionExecutor`, call `ExecutionCoordinator`, register worker handlers, execute capabilities, dispatch workers, or materialize runtime queue entries. Task graph replacement increments the graph version, changes the graph fingerprint, and supersedes any existing materialization metadata so approved/validated materialization cannot silently point at an older graph. Runtime execution/materialization remain future layers above the governed runtime foundation.

## Graph-to-Runtime Admission V1 Contracts

Graph-to-runtime admission contracts now define a governed bridge from a materialized mission task graph toward future runtime task creation. `POST /v1/missions/{mission_id}/runtime-admission` creates or updates admission metadata, and `GET /v1/missions/{mission_id}/runtime-admission` reads it back through the same tenant-scoped mission repository boundary. The contract is persisted additively in `Mission.metadata_json["runtime_admission"]` with `schema_version = 1`.

First-class in this block:

- admitted mission graph reference, graph version, and graph fingerprint;
- materialization reference and materialization version used for admission;
- selected graph node keys;
- runtime task type each selected node would map to later;
- capability and optional adapter references involved in each selected node;
- operator/system identity that approved admission;
- admission status, validation result, validation gaps, and timestamps;
- explicit `execution_task_records` metadata, currently empty because this block does not create runtime tasks;
- runtime-authority flags documenting that admission does not queue work, dispatch workers, or bypass explicit queue admission.

Graph-to-runtime admission remains a product-layer bridge only. Persisting admission metadata validates tenant ownership, task graph presence, materialization presence, non-superseded materialization state, materialization graph version/fingerprint alignment, selected node existence, duplicate selected node rejection, runtime task type availability, capability visibility, adapter visibility, and rejected outcome-review blockers where represented. It does not create `ExecutionTask` rows, enqueue work, call `MissionExecutor`, call `ExecutionCoordinator`, register handlers, execute adapters, dispatch workers, alter worker leases, or change recovery behavior.

The read-only runtime admission readiness gate is exposed at `GET /v1/missions/{mission_id}/runtime-readiness`. It evaluates whether the currently admitted mission graph is eligible for future runtime task materialization by re-checking current task graph, materialization, admission, selected-node, capability, adapter, and outcome-review state through tenant-scoped read paths. The readiness gate returns structured checks, blockers, and warnings; it does not write mission metadata, create tasks, queue work, call runtime coordinators, execute graph nodes, or dispatch workers. Live runtime graph execution remains future work above the governed queue-backed runtime foundation.

The runtime task materialization preview is exposed at `GET /v1/missions/{mission_id}/runtime-task-preview`. It reuses the readiness gate and, when the admitted graph is ready, returns deterministic preview rows for the selected graph nodes in admission order. Each preview row shows the future runtime task type, pending task state, graph node reference, capability/adapter references, materialization selection reference, dependency keys from task graph edges, and a safe payload envelope preview. The preview is read-only and pre-materialization only: it does not persist payloads, create `ExecutionTask` rows, enqueue work, call executors or coordinators, execute graph nodes, dispatch workers, or grant scheduler/runtime authority.

Execution task materialization contracts are exposed at `POST /v1/missions/{mission_id}/runtime-task-materialization` and `GET /v1/missions/{mission_id}/runtime-task-materialization`. The POST endpoint is explicit, tenant-scoped, and only proceeds when the same readiness and deterministic preview mapping are ready for the current graph/materialization/admission references. It creates planned `ExecutionTask` rows from the preview payload envelope, persists `Mission.metadata_json["runtime_task_materialization"]` with created task IDs and runtime-authority flags, and is idempotent for the same current bridge references. This bridge creates planned rows only: it does not enqueue work, dispatch workers, execute graph nodes, call `MissionExecutor`, call `ExecutionCoordinator`, invoke capability adapters, or remove/alter the existing `default_handler`. Graph execution remains future work above this materialization contract.

Runtime queue admission is exposed at `POST /v1/missions/{mission_id}/runtime-queue-admission`. It is an explicit, tenant-scoped runtime bridge for the current `runtime_task_materialization` metadata: the route locks the mission for the request tenant, reads the current materialized execution task IDs, admits only tenant/mission-owned planned tasks, treats already queued tasks as admitted, records blockers for missing, foreign, cancelled, completed, or otherwise non-queueable materialized tasks, checks quota before queueing newly eligible planned tasks, calls `ExecutionCoordinator.queue_task` for those eligible tasks, and persists `Mission.metadata_json["runtime_queue_admission"]` with the admitted, pending-review, denied, blocked, and materialized task IDs. This bridge mutates queue admission state and queue-backed task state, so it is runtime-authoritative for queue admission only. It does not create `ExecutionTask` rows, dispatch workers, execute graph nodes, call `MissionExecutor`, invoke the task dispatcher, run handlers/adapters, alter worker leases, or bypass policy, quota, tenant, or current-materialization checks.

Runtime dispatch readiness is exposed at `GET /v1/missions/{mission_id}/runtime-dispatch-readiness`. It is a tenant-scoped, read-only bridge contract over the current `runtime_task_materialization` and `runtime_queue_admission` metadata. The response verifies that current materialized task IDs are tenant/mission-owned queued `ExecutionTask` rows with explicit non-empty dispatcher `task_type` metadata, classifies planned, cancelled, running, completed, failed, dead-lettered, missing, and foreign rows, and returns ready/partial/blocked status with blockers and warnings. It does not create execution tasks, enqueue work, call `MissionExecutor`, call `ExecutionCoordinator`, dispatch workers, inspect adapter code, execute adapters, or mutate mission/task state.

Worker dispatch eligibility is exposed at `GET /v1/missions/{mission_id}/worker-dispatch-eligibility`, and worker claim preview is exposed at `GET /v1/missions/{mission_id}/worker-claim-preview`. Both endpoints are tenant-scoped and read-only. Eligibility determines which current materialized, queue-admitted, dispatch-ready, queued tasks with explicit `task_type` metadata are eligible for a future worker claim. Claim preview returns the deterministic future worker handoff envelope for each eligible task, including queued-to-claimed expectations, lease scope, runtime contract requirements, source references, and task metadata summaries. These contracts do not claim leases, start execution, dispatch workers, execute handlers or adapters, enqueue work, mutate mission metadata, mutate task state, or alter queue backend state.

Worker claim admission is exposed at `POST /v1/missions/{mission_id}/worker-claim-admission` with readback at `GET /v1/missions/{mission_id}/worker-claim-admission`. It is the first controlled mutation after worker claim preview: the POST endpoint reuses the current preview/eligibility proof, claims only eligible queued current materialized tasks with explicit `task_type` metadata through the canonical queued-to-claimed state path, establishes WorkerLease-backed claim ownership, and records deterministic claim receipts in `Mission.metadata_json["worker_claim_admission"]`. The contract stops at claim admission. It does not start execution, dispatch workers, execute handlers or adapters, enqueue work, call the task dispatcher, complete/fail tasks, or perform graph orchestration; worker loop execution remains future work above this governed bridge.

Worker execution start admission is exposed at `POST /v1/missions/{mission_id}/worker-start-admission` with readback at `GET /v1/missions/{mission_id}/worker-start-admission`. It is the second controlled mutation after worker claim preview and worker claim admission: the POST endpoint consumes only durable `worker_claim_admission.claimed_task_ids` and claim receipts, validates tenant/mission ownership plus current WorkerLease holder/scope/status, starts only claim-admitted tasks that remain in `claimed` state with explicit `task_type` metadata, and records deterministic start receipts in `Mission.metadata_json["worker_start_admission"]`. The contract performs the governed claimed-to-running transition and lease activation/heartbeat update, then stops. It does not dispatch workers, execute handlers or adapters, enqueue work, call the task dispatcher, complete/fail tasks, or perform graph orchestration; full worker-loop execution remains future work above this bridge.

Worker run admission is exposed at `POST /v1/missions/{mission_id}/worker-run-admission` with readback at `GET /v1/missions/{mission_id}/worker-run-admission`. It is the first governed runtime bridge allowed to invoke the existing `TaskDispatcher` and registered handler path. The mutation consumes only the current `worker_start_admission.started_task_ids` and start receipts, executes only tenant-owned running tasks with explicit `task_type` metadata and valid active same-tenant/same-task WorkerLease ownership, requires tenant/RLS-aware dispatcher DB sessions, and requires queue claim/processing authority before dispatch completion or failure paths can run. The contract records queue-claim receipts and run receipts in `Mission.metadata_json["worker_run_admission"]`, then lets existing runtime semantics complete, fail, or dead-letter tasks. It does not schedule graph orchestration, enqueue new work, execute arbitrary unadmitted tasks, bypass RLS, synthesize missing queue payloads, remove or rewrite `default_handler`, promote memory, or automate outcome review.

## Capability Execution Adapter Contracts V1

Capability execution adapter contracts now define durable declarations for how registered capabilities may eventually connect to executable adapter surfaces. `POST /v1/capability-adapters`, `PATCH /v1/capability-adapters/{adapter_id}`, `GET /v1/capability-adapters`, and `GET /v1/capability-adapters/{adapter_id}` persist and read adapter metadata through tenant-authenticated route boundaries. Tenant-scoped adapters are owned by the request tenant; global adapters are visible to tenants when seeded through repository/migration/admin-safe paths and remain read-only from tenant routes.

First-class in this block:

- adapter name and version;
- capability binding by visible `capability_id` or declared capability name/version;
- supported task types;
- input and output contracts;
- required permissions and tools;
- execution mode;
- risk level and approval requirements;
- evidence expectations;
- timeout/retry hints;
- idempotency expectations;
- side-effect classification;
- enabled/disabled state;
- tenant or global scope;
- schema version.

Capability execution adapters remain a declarative contract layer only. Persisting or updating an adapter does not execute work, register worker handlers, bind runtime dispatch, create `ExecutionTask` rows, queue work, call `MissionExecutor`, call `ExecutionCoordinator`, dispatch workers, materialize graph nodes into runtime queue entries, invoke third-party tools, or persist evidence. Runtime binding and execution remain future layers above the governed runtime foundation.

## Evidence Contract Layer V1

Evidence contracts now define durable, tenant-owned proof/provenance records that future runtime execution, capability adapters, and outcome review can reference. `POST /v1/evidence`, `GET /v1/evidence/{evidence_id}`, `GET /v1/evidence?mission_id=...`, and `PATCH /v1/evidence/{evidence_id}` persist, read, list, and update evidence status/metadata through tenant-scoped repository boundaries.

First-class in this block:

- tenant ownership;
- mission binding;
- optional task graph node key;
- optional planner-to-graph materialization reference;
- optional execution task reference;
- optional capability and capability adapter references;
- evidence type and source;
- evidence summary;
- structured payload;
- artifact references;
- provenance metadata;
- trust/confidence signal;
- collection status;
- schema version and timestamps.

Evidence records are proof/provenance contracts only. Persisting or updating evidence may validate referenced mission ownership, capability visibility, adapter visibility, and execution task ownership, but it does not score outcomes, approve or reject outcomes, promote memory, create vector memory, execute adapters, call workers, queue work, call `MissionExecutor`, call `ExecutionCoordinator`, or alter runtime dispatch. Outcome review is now the next contract layer above evidence; memory promotion remains future work.

## Outcome Review Contract Layer V1

Outcome review contracts now define durable, tenant-owned records for evaluating mission result claims against mission success criteria, task graph or materialization metadata, and evidence records. `POST /v1/outcome-reviews`, `GET /v1/outcome-reviews/{review_id}`, `GET /v1/outcome-reviews?mission_id=...`, and `PATCH /v1/outcome-reviews/{review_id}` persist, read, list, and update review status/metadata through tenant-scoped repository boundaries.

First-class in this block:

- tenant ownership;
- mission binding;
- optional materialization and task graph references;
- reviewed success criteria;
- evidence references constrained to the same tenant-owned mission;
- review status and decision;
- reviewer type and source;
- review summary and structured findings;
- confidence/trust metadata;
- unresolved gaps and recommended next actions;
- human approval requirement/status;
- schema version and timestamps.

Outcome review records are contract records only. Persisting or updating an outcome review may validate mission ownership and same-tenant/same-mission evidence ownership, but it does not perform autonomous scoring, promote memory, create memory candidates, execute adapters, create runtime task rows, queue work, call `MissionExecutor`, call `ExecutionCoordinator`, dispatch workers, alter worker dispatch, or mutate mission/task runtime state. Memory promotion remains a future layer above reviewed outcomes, and runtime execution remains governed separately by the existing runtime control plane.

## Retrieval and Recall Contract Layer V1

Retrieval and recall contracts now define durable, tenant-owned records describing how future systems request, track, govern, and validate memory retrieval. `POST /v1/retrieval-contracts`, `GET /v1/retrieval-contracts/{retrieval_id}`, `GET /v1/retrieval-contracts?mission_id=...`, and `PATCH /v1/retrieval-contracts/{retrieval_id}` persist, read, list, and update retrieval status/metadata through tenant-scoped repository boundaries.

First-class in this block:

- tenant ownership;
- mission binding;
- optional memory references and returned memory references;
- retrieval request and reason metadata;
- retrieval strategy and strategy metadata;
- retrieval filters and governance constraints;
- confidence/trust metadata;
- retrieval provenance;
- retrieval status, supersession, and revocation metadata;
- schema version and timestamps.

Retrieval remains governance-first and retrieval-engine-neutral. Persisting or updating a retrieval contract may validate mission ownership and memory-reference tenant/mission alignment, but it does not generate embeddings, execute vector search, rank semantic results, reason autonomously, create runtime task rows, queue work, call `MissionExecutor`, call `ExecutionCoordinator`, dispatch workers, alter worker dispatch, or mutate mission/task runtime state. Embeddings, vector databases, runtime reasoning, and autonomous execution remain future layers above these contracts.

## Mission Lifecycle Read Model V1

Mission lifecycle reads now provide a compact, tenant-scoped view across the product-layer contracts for one mission. `GET /v1/missions/{mission_id}/lifecycle` aggregates mission identity/status, intake metadata, plan metadata, task graph metadata, graph materialization metadata, evidence summaries, outcome review summaries, memory promotion summary state, retrieval contract summaries, deterministic completeness flags, and deterministic missing next-step indicators.

This read model is aggregation only. It does not execute graphs, admit queues, create `ExecutionTask` rows, call `MissionExecutor`, call `ExecutionCoordinator`, dispatch workers, run adapter execution, score outcomes, perform retrieval/vector search, promote memory, or mutate mission/runtime state. Existing contract endpoints remain the write/read authorities for their individual layers.


# Build Direction

Ajenda should evolve through:

1. mission intake
2. mission planning contracts
3. capability registry
4. task graph contracts
5. planner-to-graph materialization contracts
6. capability execution adapter contracts
7. evidence contract layer
8. outcome review contract layer
9. real worker skills
10. evidence-backed execution
11. memory promotion
12. retrieval and recall contracts

The runtime foundation should remain authoritative.

---

# Non-Goals

Ajenda is not:

- only a workflow builder
- only an AI assistant
- only an integration platform
- only an agent sandbox
- only a runtime validation system
- only a static business module system

Ajenda is a mission-centered governed execution platform for machine-performed business work.
