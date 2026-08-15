# ADR-0011: Bounded Temporal Intelligence Advancement

**Status:** Accepted
**Date:** 2026-08-15
**Risk class:** Runtime admission, durable provenance, tenant isolation

## Context and decision

Canonical intelligence owners already implement Decision Episode materialization,
Experience evaluation, Knowledge Qualification, and Knowledge Ledger persistence.
The missing production responsibility is when a newly durable artifact may be
offered to its next owner.

`TemporalIntelligenceAdvancementService` owns exactly two transitions:

1. canonical Outcome → `analysis.materialize_decision_learning_signal`; and
2. canonical DecisionLearningSignal → `knowledge.consolidate_learning_history`.

Temporal Composition coordinates existing intelligence authorities and determines
transition eligibility. It does not own Decision, Outcome, Experience, Knowledge,
mission planning, or execution semantics.

The trigger runs from `WorkerRuntimeService.complete()` only after the upstream
task, lease release, lineage, EvidenceBridge records, and audit are committed.
The coordinator preflights the existing canonical owner, then persists a
deterministically identified `ExecutionTask` and admits it through
`ExecutionCoordinator`. It never invokes an action handler directly.

## UPG / LAP review

### Responsibility and dependencies

Input is one tenant-owned durable EvidenceRecord identity. Output is an explicit
state (`NOT_ELIGIBLE`, `ELIGIBLE`, `ALREADY_ADVANCED`, `ADVANCED`, `BLOCKED`, or
`FAILED`) and, when admitted, a canonical downstream task identity. Sources of
truth are EvidenceBridge runtime provenance, tenant/mission relationships, owner
event chronology, `DecisionEpisodeMaterializationService`,
`DurableExperienceConsolidationService`, Knowledge Qualification/Ledger, and the
existing runtime coordinator/queue/worker path.

### Pitfalls and failure behavior

Missing or duplicated recommendations, absent execution ancestry, forged labels,
foreign-tenant UUIDs, ambiguous chronology, conflicting episode identity,
concurrent replay, policy denial, queue failure, and downstream action failure all
fail closed. An upstream commit is never rolled back to simulate cross-stage
atomicity. A durable planned successor remains recoverable if queue admission
fails. No external side effect is introduced.

### Invariants and proof

- Only exact canonical runtime projections can trigger advancement.
- Owner services retain all semantic decisions and chronology validation.
- Deterministic tenant/source/transition task IDs make scheduling replay safe;
  stable episode identities and Knowledge Ledger identities prevent duplicate
  learning and Knowledge history.
- Every downstream action still requires queue admission, lease ownership,
  dispatcher execution, action validation, and EvidenceBridge persistence.
- No mission plan or task graph is extended, and Knowledge activation queues no
  business execution.

Focused unit tests cover state classification, missing state, provenance rejection,
owner delegation, and stable identity. PostgreSQL intelligence integration uses
the real queue/lease/dispatcher/EvidenceBridge path and the existing end-to-end
Knowledge-informed Decision proof.

## Compatibility, migration, and rollback

The change is additive and needs no database migration. Existing action schemas,
intelligence tables, and Knowledge identities are unchanged. Rollback removes the
post-commit hook, coordinator, tests, and this contract entry. Already-created
internal successor tasks remain ordinary auditable runtime records; upstream and
downstream canonical intelligence artifacts remain valid.
