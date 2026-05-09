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
- handler mapping
- enabled tenants/plans if applicable

This allows new modules and capabilities to be added without restructuring the platform.

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

- mission intake
- mission planning
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
- task graph/DAG persistence;
- capability registry enforcement;
- runtime dispatch changes;
- worker handler changes;
- outcome review;
- memory promotion.

Mission intake does not queue work. Runtime admission remains explicit through the existing mission/task queue routes, and queue-backed execution, leases, recovery, and compliance review behavior remain governed by the current runtime layer. Tenant ownership is taken from the validated tenant/auth context, not from request body input.

# Build Direction

Ajenda should evolve through:

1. mission intake
2. mission planning
3. capability registry
4. task graph generation
5. real worker skills
6. evidence-backed execution
7. outcome review
8. memory promotion

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
