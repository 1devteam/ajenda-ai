# V1 Path 3 implementation status — 2026-08-18

## Outcome

The code-first Revenue Operations baseline is implemented and remains non-promoted. It can interpret and deterministically validate the authorized research → qualification → outreach-draft workflow, pin a versioned know-how contract, accept only strict structured planner proposals, and require independent human approval before a materialized external effect is queued.

This artifact does not declare production V1 release complete. Provider-backed runtime proof, a sealed held-out evaluation, and owner-approved numeric promotion rules do not yet exist.

## Implemented

- Path 3 and the D8 product boundary are recorded.
- VR-01 has a versioned 10-case development corpus and a non-executing evaluator.
- The development corpus passes 10/10 declared expectations, including ambiguity, contradiction, unsupported-action, prompt-injection, missing-provider, and long-context fail-closed cases.
- RevOps know-how `revops.research-to-approved-outreach@1.0.0` is declarative, version-pinned, graph-validated, and blocked from promotion without an owner budget.
- The optional planner accepts strict JSON only, cannot grant authority, and is bounded by the pinned know-how vocabulary, material clauses, dependencies, connectors, review points, artifact bindings, and budget.
- Composition and runtime materialization no longer fabricate side-effect approval.
- Queue admission detects unapproved side effects and moves them to `pending_review`.
- The tenant-locked authenticated approval path issues an exact-action grant, emits audit/governance evidence, and queues that same payload with rollback on enqueue failure.

## Validation evidence

- Targeted V1, approval, retry, daemon-boundary, and authority suites pass.
- VR-01 evaluator: 10/10 cases passed; executable authority remains false.
- Ruff check and format check: passed across `backend/`, `tests/`, and `scripts/validation/`.
- Contract drift, runtime authority inventory, migration seed contract, and ability rollout contract checks: passed.
- Full non-integration repository gate: 2,500 passed, 1 deselected (Docker-backed execution available in the approved validation environment).
- Docker-backed runtime integration proof: 14 tests passed across graph admission, tool execution,
  audit evidence, recovery, reconciliation, concurrency isolation, dead-letter retry, and the
  tenant-scoped HubSpot credential/adapter path. The HubSpot test uses a controlled egress spy;
  it is not production-provider effect proof.
- `git diff --check`: passed.

## Known gate limitations

- The complete non-integration gate now completes successfully with Docker-backed dependencies available.
- `mypy backend/` reaches one pre-existing error at `backend/services/billing_stripe_integration.py:313` (`stripe.Webhook.construct_event` is untyped). All V1-introduced mypy errors were resolved.
- The runtime authority inventory now reports 11 canonical-boundary and four daemon-spine sinks,
  with zero competing HTTP spines and zero exception bypasses.

## Required before promotion

1. Owner-approved budgets and acceptance/rollback thresholds from D8 section 9.
2. A sealed held-out corpus and provider-backed planner benchmark.
3. Real Gmail and HubSpot sandbox credentials/connections for optional-effect proof.
4. Canonical queue/lease/runtime integration proof with database and queue services available.
5. Provider fault, retry, idempotency, duplicate-effect, tenant-isolation, and evidence-readback proof.
6. Provider-backed canonical runtime proof, including fault/retry/idempotency and evidence read-back.

Until these exist, the honest release state is **implemented code-first baseline; promotion blocked**.
