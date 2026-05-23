# ADR-0003: Readiness Semantics Doctrine

- **Status:** Accepted
- **Date:** 2026-05-23
- **Owner:** AJENDA-AI Architecture Team
- **Related:** `README.md`, system probes, deployment/runtime validation docs

## Context

AJENDA-AI exposes root and versioned health/readiness surfaces. Historically, readiness semantics can drift toward shallow liveness checks, which weakens operational trust. The runtime requires dependency-truth readiness while preserving safe, sanitized responses.

## Decision

Define and enforce distinct probe semantics:

1. **Health endpoints (`/health`, `/v1/system/health`)** remain lightweight liveness checks.
2. **Readiness endpoints (`/readiness`, `/v1/system/readiness`)** must represent dependency usability truth for required runtime dependencies (at minimum database and configured queue adapter).
3. Readiness failure responses must be sanitized (no secret leakage, no unsafe internals).

## Consequences

### Positive

- Improves deploy safety and rollback automation decisions.
- Aligns runtime truth with documented contracts.
- Reduces false-positive "healthy" states during dependency degradation.

### Tradeoffs

- Readiness checks may increase implementation and test complexity.
- Dependency checks require careful timeout and failure-mode handling.

## Verification impact

- Unit tests must cover degraded dependency scenarios.
- Contract tests must validate stable response shape and sanitization behavior.
- Validation matrix/release-gating rows must include readiness dependency-truth checks.

## Rollback strategy

If strict readiness behavior causes operational instability, rollback via controlled config fallback while preserving probe route surfaces; restore strict mode once dependency checks are corrected and re-validated.
