# Knowledge Qualification Slice 1

Knowledge Qualification deterministically assesses an `ExperiencePatternCandidate` as insufficient, provisional, qualified, contested, or invalidated. It is a pure epistemic boundary: it performs no persistence, retrieval, policy creation, causal inference, planning, or behavior modification.

## Authority and data flow

Experience remains the owner of recurrence and pattern semantics. It emits a frozen `ExperiencePatternSemanticContext` containing typed business-object classes, Decision-owned or legacy intervention authority, explicit/KPI/inherited/exact-instance Goal authority, exact Goal provenance, common scope, and invalidation conditions. Knowledge Qualification consumes this context directly and never parses compatibility fields such as `goal_id`, `partition_key`, recommendation prose, objective dimensions, or explanation codes.

The path is:

`DecisionLearningSignal → ExperienceContextSignature → ExperiencePatternSemanticContext → ExperiencePatternCandidate → qualify_pattern_knowledge()`.

Legacy candidates without the typed context remain deserializable but fail closed as insufficient.

## Deterministic gates

The result exposes fixed semantic identity, intervention authority, Goal authority, recurrence, independent support, contradiction, scope, and temporal-provenance gates. A supported Experience recurrence is necessary but insufficient. Qualification additionally requires three Experience-earned independent strong support units, owner-explicit Goal semantics, exclusively Decision-owned intervention semantics, bounded common scope, a consistent contradiction contract, and valid evaluation-time ordering.

KPI-only or inherited Goal meaning, legacy intervention fallback, emerging recurrence, and missing scope cap a stateable proposition at provisional. Exact Goal instance fallback, missing typed meaning, conflicting scope, weak recurrence, or malformed supported recurrence fail qualification. Contested and invalidated recurrence retain their upstream status precedence. Limited/dependent counterevidence remains visible and does not erase three valid independent support units.

## Identity and artifact boundary

`proposition_key` hashes only canonical proposition meaning: typed subjects, intervention, objective/KPI semantics, the non-causal `associated_with_favorable_outcome` relationship, scope, and invalidation conditions. `qualification_id` separately hashes the complete canonical candidate plus `knowledge_qualification_v1`, so new evidence changes the assessment identity without changing the proposition identity. A qualified artifact receives a third deterministic `knowledge_id`.

Only `QUALIFIED` emits `QualifiedKnowledgeArtifact(is_knowledge=True)`. Every result and artifact has `is_policy=False`; the artifact also has `is_persisted=False`.

Qualified artifacts may subsequently be recorded by the Durable Knowledge Ledger. Qualification itself remains pure,
and its immutable artifact retains `is_persisted=False`; the ledger creates separate durable record references.

## Ability surface

`analysis.qualify_pattern_knowledge` accepts an explicitly supplied serialized candidate and returns the serialized qualification result with `action_result_evidence`. The `ajenda_analysis` action is `SideEffectClass.NONE`, low risk, approval-free, readback-free, and disabled by default. Experience and Knowledge abilities are not automatically composed.
