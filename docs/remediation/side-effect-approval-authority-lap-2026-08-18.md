# Side-effect approval authority UPG/LAP — 2026-08-18

## Responsibility and source of truth

Mission composition and runtime materialization may describe an external action, but may not approve it. The authenticated admin review route and `ExecutionCoordinator.approve_review_and_queue` are the authority boundary for a task-level human approval.

The coordinator locks the tenant-owned `ExecutionTask`, records the approval in the task's persisted metadata, transitions it to `queued`, publishes that same payload, and emits governance and audit evidence. A failed publish restores the prior task state and the surrounding route transaction rolls back the metadata grant.

## Dependencies

- Composition graph compiler: produces declarative `tool.invoke` inputs.
- Runtime task materialization: creates tenant-scoped planned tasks.
- `PolicyGuardian` and `ExecutionCoordinator`: force review and own approval-to-queue.
- `ToolRuntimeAuthority` and capability validation: consume the persisted grant under a running lease.
- Admin approval route: supplies the authenticated actor and commits or rolls back atomically.
- Queue payload, governance events, audit events, and tests.

## Possible pitfalls

- A graph, browser payload, template, or materializer fabricates approval.
- An operational task bypasses review even though its action has a side effect.
- Approval is applied to the wrong tenant or a task whose action is missing or malformed.
- Queue publication fails after approval, leaving durable authority on a non-queued task.
- A grant authorizes more than the exact task action.
- Read-only actions are unnecessarily blocked.

## Invariants

1. Composition and materialization never mint `side_effect_authorization`.
2. Every materialized side-effecting task has `requires_human_review=True`.
3. Any task marked as requiring human review enters `pending_review` before queue publication.
4. Only the locked, tenant-validated approval path writes a task grant.
5. The grant permits exactly the persisted tool action and names the authenticated actor.
6. Missing, malformed, client-forged, composition-issued, or materializer-issued grants fail closed.
7. Queue failure rolls back both state and approval through the route transaction.
8. Capability/adapter authority, lease ownership, running state, and evidence requirements remain independent gates.

## Proof

- Unit tests for graph compilation and materialization prove no fabricated grant.
- Policy tests prove operational side effects cannot bypass review.
- Coordinator tests prove exact-action grant issuance, tenant locking, audit/governance evidence, and enqueue payload coherence.
- Runtime authority tests prove self-issued and absent grants are rejected.
- Targeted tests run before the repository validation gates.

## Non-goals

This change does not make declarative capability records executable, bypass provider credentials, relax tenant checks, or promote optional Gmail/HubSpot delivery without operator approval.
