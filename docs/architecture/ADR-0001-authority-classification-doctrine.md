# ADR-0001: Authority Classification Doctrine

- **Status:** Accepted
- **Date:** 2026-05-23
- **Owner:** AJENDA-AI Architecture Team
- **Related:** `PROJECT_SPEC.md`, `README.md`, mission bridge/runtime contracts

## Context

AJENDA-AI contains mixed contract surfaces: declarative records, read-model projections, governed mutations, and runtime-authoritative execution. Without strict authority classification, contributors may accidentally treat metadata declarations as execution authority, causing unsafe logic coupling and runtime drift.

## Decision

Adopt and enforce a four-class authority doctrine across product and runtime layers:

1. `declarative`
2. `read_model`
3. `governed_mutation`
4. `runtime_authoritative`

Each endpoint and major metadata contract must be classifiable into one class, with explicit allowed/forbidden side effects.

### Authority class requirements

- **Declarative**
  - Allowed: validation + persistence of declared contract data.
  - Forbidden: dispatching, executing, or mutating runtime state beyond the declaration boundary.

- **Read model**
  - Allowed: deterministic aggregation/derivation of existing persisted truth.
  - Forbidden: side-effecting mutations and dispatch.

- **Governed mutation**
  - Allowed: bounded, tenant-scoped state transitions explicitly documented by contract.
  - Forbidden: collapsing multiple authority stages into implicit all-in-one execution.

- **Runtime authoritative**
  - Allowed: execution state transitions under queue + lease authority.
  - Forbidden: bypassing queue, lease, auth, policy, or recovery controls.

## Consequences

### Positive

- Reduces ambiguity and onboarding risk.
- Prevents accidental elevation of declarative contracts into execution semantics.
- Improves auditability and release-gate clarity.

### Tradeoffs

- Increases documentation and review overhead.
- Requires stricter PR discipline when touching cross-layer workflows.

## Verification impact

- Contract docs and route docs must include authority classification.
- Tests should cover forbidden outcomes where authority boundaries could be violated.
- Validation matrices should reflect runtime-authoritative invariants separately from declarative/read-model invariants.

## Rollback strategy

As a doctrine ADR, rollback means superseding this ADR with a new classification model and updating affected docs/tests before enforcement changes.
