# ADR-0008: Decision Episode Materialization Authority

**Status:** Accepted  
**Date:** 2026-08-12  
**Risk class:** Authority, tenant isolation, durable evidence composition

## Invariant

Decision identity, decision semantics, execution identity, outcome identity, and
learning identity are separate authorities. A learning episode may connect them
only through durable provenance; it may not recreate or assert them independently.
A caller may request materialization, but may not author the historical truth.

## UPG / LAP review

### Responsibility and source of truth

`DecisionEpisodeMaterializationService` accepts only EvidenceRecord identities,
resolves them in the active tenant, validates their owner action and mission/task
provenance, and composes the existing snapshot, outcome, feedback, and learning
signal contracts. The durable `decision.recommend_next_action` EvidenceRecord is
the decision anchor. A durable `knowledge.inform_decision` result may also be the
anchor only when its task and evidence provenance prove exact composition of the
canonical Decision action and preserve its input and output. No Decision database
is introduced.

### Dependencies

- Recommendation semantics: `decision.recommend_next_action` and the persisted
  task's validated `DecisionRecommendInput`.
- Knowledge composition: applicable, semantically aligned support becomes inferred
  `EvidenceFact` input with a distinct derived identity and durable EvidenceRecord
  UUID ancestry resolved from Qualification-owned supporting episode identities;
  criteria, weights, and caller evidence remain unchanged. Current-context
  applicability EvidenceRecords remain a separate proof surface and are never
  relabeled as the historical basis from which Knowledge was earned.
- Decision semantics: the existing canonical `decision_snapshot_builder`.
- Execution truth: durable action EvidenceRecords and their explicit event time.
- Outcome and attribution truth: a durable `analysis.evaluate_outcome` payload
  validated as the existing `OutcomeEvaluation`.
- Persistence: the existing tool `EvidenceItem` → `EvidenceBridge` →
  `EvidenceRecord` path.
- Tenant authority: tenant-filtered Evidence and ExecutionTask repositories.

### Possible pitfalls

Missing or foreign artifacts, wrong artifact roles, malformed payloads, ambiguous
executed actions, contradictory lineage, cross-mission linkage, impossible event
chronology, duplicate requests, and confusion between persistence order and event
order all fail closed. Missing execution proof remains `execution_unknown`; weak
attribution is preserved rather than rejected or upgraded.
Knowledge IDs, episode IDs, current applicability evidence, and synthetic influence
IDs are never substituted for historical durable learning-signal EvidenceRecords.
Derived or computed EvidenceRecords cannot establish fresh current applicability;
historical learning signals remain explicitly non-independent lineage inputs.

### Invariants

- Recommendation EvidenceRecord identity deterministically owns `decision_id`.
- The same ordered artifact set owns one stable episode, feedback, and signal ID.
- Different recommendation artifacts remain different decisions even with equal prose.
- Repository reads are tenant-scoped and foreign UUIDs appear inaccessible.
- Recommended and executed intervention identities are compared, never inferred
  from outcome success.
- Owner event timestamps govern chronology; `created_at` does not.
- Decision remains the only scorer; Knowledge neither selects nor executes an option.
- Qualified Knowledge adds no numeric confidence policy: derived facts use neutral
  confidence `1.0`, leaving Decision's existing `INFERRED` multiplier as the sole
  numeric authority.
- Knowledge-derived facts remain non-independent across Decision snapshot and
  learning-signal lineage, rooted in the source EvidenceRecords they cite.
- Durable-source substitution is valid only for a known `DERIVED_FACT` whose
  canonical EvidenceRecord UUIDs exactly equal its root, parent, and ancestor
  assertions. Current applicability evidence must carry explicit, identity-matched
  `SOURCE_OBSERVATION` lineage; missing lineage never implies independence.
- The output remains `DecisionLearningSignal` with `is_knowledge = false` and
  `is_policy = false`.

### Proof and non-goals

The adversarial service suite proves identity, tenant isolation, artifact role,
execution mismatch/unknown behavior, chronology, idempotency, and attribution
preservation. Registry, ability rollout, evidence bridge, ontology, and authority
ledger suites prove composition. This change does not aggregate experience,
qualify knowledge, infer causality, dispatch runtime work, or add persistence.

## Compatibility and rollback

Pure ontology helpers continue accepting typed objects for unit/internal use. The
new materialization action is the canonical production historical path. Rollback
removes the action, service, manifest, and ledger entry; there is no migration or
stored schema to reverse. Recommendation payloads gain an additive `decided_at`
field; previously persisted recommendations without owner event time fail closed
rather than using database insertion time as historical chronology.
The reconciliation adds an optional EvidenceFact ancestry field and a composed
Knowledge result envelope. Rollback removes composed-anchor acceptance and derived
fact translation; no migration or queue/runtime authority change is required.
