# ADR-0002: Schema Evolution Strategy

- **Status:** Accepted
- **Date:** 2026-05-23
- **Owner:** AJENDA-AI Architecture Team
- **Related:** `PROJECT_SPEC.md`, Alembic migrations, contract-schema tests

## Context

AJENDA-AI evolves across database schema, metadata envelopes, and API contracts. Unsafe changes can break tenant runtime correctness, invalidate historical evidence, or create upgrade fragility. A consistent evolution strategy is required to preserve production reliability.

## Decision

Adopt additive-first, backward-compatible schema evolution with explicit versioning and fail-closed parsing of unknown future versions.

### Core rules

1. Prefer additive changes over destructive rewrites.
2. Use explicit schema version fields for metadata envelopes.
3. Do not silently repurpose existing key semantics.
4. Use dual-read compatibility windows when transitioning formats.
5. Introduce destructive migrations only in isolated, pre-announced, safety-validated phases.

### PR requirements for schema-affecting changes

- migration rationale and impact summary,
- compatibility plan (write path + read path),
- migration contract tests,
- rollback/disable strategy,
- notes on historical data behavior.

## Consequences

### Positive

- Minimizes production breakage risk.
- Preserves historical contract interpretability.
- Supports incremental rollout and rollback safety.

### Tradeoffs

- Slower cleanup of legacy shapes.
- Temporary complexity from dual-read pathways.

## Verification impact

- Migration contract tests are mandatory for schema changes.
- Contract/API tests must verify backward compatibility during transition windows.
- Validation docs should note behavior changes when schema versions are introduced/retired.

## Rollback strategy

Rollback uses feature/config gating and compatibility reads where available; destructive rollbacks must follow dedicated operational runbooks and data-safety checks.
