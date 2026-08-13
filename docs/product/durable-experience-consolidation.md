# Durable Experience Consolidation

Durable Experience Consolidation is the sole production composition owner for
turning tenant-owned historical learning observations into current knowledge history:

```text
Decision Episode Materialization (#427)
        ↓
durable DecisionLearningSignal EvidenceRecord
        ↓
Durable Experience Consolidation (#428)
        ↓
Experience Intelligence
        ↓
Knowledge Qualification
        ↓
Knowledge Ledger
        ↓
Knowledge Lifecycle / Retrieval
```

The types are intentionally distinct. `EvidenceRecord` is the durable observation
substrate. `ExperiencePatternCandidate` is a derived, dependence-resolved recurrence
artifact. `KnowledgeQualificationResult` is the promotion authority's judgment. The
Knowledge Ledger is immutable durable knowledge history; Lifecycle determines its
current state.

The consolidation reader uses the active tenant session plus an explicit tenant
predicate and validates both the canonical materialization action/role and every
`DecisionLearningSignal` payload. Database predicates only discover candidates.
Experience retains all semantic partition, direction, dependence, and recurrence
authority. Signal `evaluated_at` supplies epistemic chronology; evidence persistence
`created_at` never does.

The governed `knowledge.consolidate_learning_history` action is an `INTERNAL_WRITE`
with no caller input. It includes positive, contradictory, weak, legacy, excluded, and
late-arriving history, delegates every candidate to Knowledge Qualification, and writes
only through Knowledge Ledger. Stable owner identities make unchanged-history replay
safe.

This composition does not provide Applicability, Decision Support, causal inference,
runtime execution, StrategyEngine behavior, automatic weight changes, lifecycle
mutation, an Experience database, or another Knowledge store.
