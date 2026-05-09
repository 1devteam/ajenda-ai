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

Mission planning contracts now define structured execution intent between mission intake and future task graph generation. `PUT /v1/missions/{mission_id}/plan` creates or replaces a tenant-scoped mission plan, and `GET /v1/missions/{mission_id}/plan` reads it back through the same tenant-scoped mission repository boundary. The plan is persisted additively in `Mission.metadata_json["mission_plan"]` with `schema_version = 1`.

First-class in this block:

- phases and stages;
- planning notes;
- desired outputs;
- capability requirements;
- execution strategy hints;
- approval gates;
- operator overrides;
- estimated scope;
- risk annotations;
- planning status.

Mission planning remains a contract layer only. Persisting a plan does not queue work, create execution tasks, generate a task graph, enforce a capability registry, promote memory, run outcome review, or modify worker/runtime orchestration. Runtime authority remains with the governed queue, lease, policy, recovery, and validation layers.

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

Task graph contracts now define durable, tenant-scoped planned work structure between mission planning and future materialization/execution. `PUT /v1/missions/{mission_id}/task-graph` creates or replaces a graph contract, and `GET /v1/missions/{mission_id}/task-graph` reads it back through the same tenant-scoped mission repository boundary. The graph is persisted additively in `Mission.metadata_json["mission_task_graph"]` with `schema_version = 1`.

First-class in this block:

- graph status and schema version;
- mission identifier binding;
- graph nodes;
- graph edges/dependencies;
- node capability references;
- node intended task type;
- node input and expected output contracts;
- node risk level and approval requirement;
- node execution constraints;
- operator notes;
- graph validation metadata;
- graph version and immutable graph fingerprint for downstream materialization references.

Task graph contracts remain a product-layer contract only. Persisting a graph validates shape, rejects duplicate node keys, rejects edges pointing to missing nodes, and rejects cycles, but it does not create `ExecutionTask` rows, queue work, call `MissionExecutor`, call `ExecutionCoordinator`, dispatch workers, enforce capability runtime behavior, or materialize the graph into runtime tasks. Runtime materialization and execution remain future layers above the governed runtime foundation.

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

# Build Direction

Ajenda should evolve through:

1. mission intake
2. mission planning contracts
3. capability registry
4. task graph contracts
5. planner-to-graph materialization contracts
6. real worker skills
7. evidence-backed execution
8. outcome review
9. memory promotion

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
