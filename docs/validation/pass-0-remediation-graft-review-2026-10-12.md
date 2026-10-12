# Pass 0 Remediation GRAFT+ Review

**Date:** 2026-10-12  
**Campaign base:** `origin/main` at `ec446fb5`  
**Current main after PR #586:** `9d705f97`  
**Status:** implementation complete; PR #586 merged, remaining stacked review pending

## Review outcome

The Pass 0 remediation is split into six dependency-ordered branches. Runtime durability changes
land first, graph accuracy follows the implementation, and this final branch reconciles the
architecture contract only after code and regression proof agree.

| Order | Branch | Head before this branch | GitHub review | Remediation outcome |
| --- | --- | --- | --- | --- |
| 1 | `fix/runtime-state-queue-atomicity` | `ac512938` | merged in #586 | R01-R04: durable queue admission and visible compensation prevent silent DB/queue divergence. |
| 2 | `fix/redis-task-index` | `61ffcbdd` | merged in #586 | R18: Redis task transitions maintain the task index used by recovery and inspection. |
| 3 | `fix/durable-billing-metering` | `acc73355` | #586 merged | R05: Stripe metering uses a tenant-scoped durable outbox, stable idempotency, and retry-safe dispatch. |
| 4 | `fix/graft-action-selection-semantics` | `e54cb78f` | #588 | Registered actions are no longer falsely reported as missing mission job selection. |
| 5 | `fix/graft-static-cycles` | `9d99b339` | #587, based on #588 | Six static dependency cycles are removed through registration and collaborator contracts. |
| 6 | `fix/remediation-contract-reconciliation` | this branch | #589, based on #587 | Repaired RLS and governed-egress findings are removed from the detector baseline and both invariants return to `enforced`. |

## UPG/LAP reconciliation

- **Responsibility:** runtime services own state transitions and effects; repositories own durable
  persistence; queue adapters own queue indexes and lease state; the graph reports those facts but
  grants no execution authority.
- **Dependencies:** `ExecutionTask` admission, `WorkerRuntimeService`, Redis queue state, the Stripe
  metering outbox, action/handler registration contracts, migrations `0041` and `0044`,
  `NetworkEgressAuthority`, graph generation, and graph semantic tests.
- **Pitfalls reviewed:** partial enqueue, queue/DB visibility races, duplicate Stripe delivery,
  tenant mismatch, stale task indexes, false action-selection findings, import cycles hidden by lazy
  imports, and acknowledgements surviving after their underlying defects were repaired.
- **Invariants:** tenant isolation, canonical queue admission, lease ownership, governed egress,
  explicit side-effect authority, retry-safe external effects, and evidence-backed failure remain
  fail closed.
- **Proof:** targeted unit and integration tests, migration/RLS checks, frontend tests and build for
  the cycle repair, required repository validators, full non-integration suites, explicit
  changed-file impact analysis, and per-commit GRAFT+ gates.

## Canonical graph result

After the six-branch stack:

- nodes: 2,087
- edges: 5,774
- static cycles: 0
- semantic findings: 0
- unmapped implementation/contract files in the final explicit changed-file analysis: 0 (this
  review-only Markdown artifact is manually classified as non-runtime documentation)
- tenant-isolation invariant: `enforced`
- governed-egress invariant: `enforced`
- acknowledged findings: none

The RLS closure is backed by migrations `0041_restore_tenant_rls_boundaries` and
`0044_restore_composition_onboarding_rls`. The egress closure is backed by the LLM and Resend
delivery implementations delegating HTTP transport to `NetworkEgressAuthority`. The semantic graph
tests assert both repaired states, so removing the historical acknowledgements does not suppress a
live finding.

## Review and merge order

PR #586 squash-merged the first three implementation branches together. Review and merge the
remaining chain as #588, then #587, then #589. Merging those out of order obscures the intended diff
and can separate a contract reconciliation from its implementation proof. Generated local GRAFT+
impact, proof-selection, completeness, and gate reports are stored under `artifacts/remediation/`
with `pr1-` through `pr6-` prefixes.

No live external side effect is required by the final graph-contract reconciliation. Provider
runtime behavior was proved in the implementation branches; this branch changes reporting and
regression assertions only.
