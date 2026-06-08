# Ability Rollout Contract

The Ability Rollout Contract defines the repeatable shape for adding future abilities, tools, providers, and role-guided workflows without redesigning the runtime path.

This contract is intentionally non-executing. It does not replace `TaskDispatcher`, `tool.invoke`, `ActionRegistry`, capability declarations, adapter declarations, queue authority, lease ownership, or `WorkerRuntimeService`.

## Purpose

Every new ability should be declared, validated, tested, and documented before promotion into runtime use.

A rollout-ready ability must define:

1. Capability declaration
2. Capability adapter declaration
3. `ToolInvocation` input schema
4. `ActionResult` and `EvidenceItem` output expectations
5. Action handler
6. Registry registration
7. Side-effect classification
8. Approval and idempotency rules
9. Evidence and readback expectations
10. Unit tests
11. Runtime integration proof
12. Validation matrix and documentation update

## Runtime authority boundary

Ability manifests describe rollout readiness. They do not execute work.

Runtime execution remains:

```text
ExecutionTask
→ queue-backed worker claim/start/run
→ TaskDispatcher
→ tool.invoke handler
→ ActionRegistry
→ action handler/provider
→ ActionResult
→ WorkerRuntimeService.complete/fail
→ lineage/evidence/audit/queue result
