# ADR-0010: Decision Episode Materialization Authority

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
- Knowledge composition deliberately preserves two Decision input views: the
  scoring view retains deterministic synthetic derived-fact identities, while the
  materialization/audit view expands those facts over their canonical durable
  learning-signal EvidenceRecord UUID ancestry. The derived claim remains
  `INFERRED`; normalization does not claim that the source record authored it.
- Composed Decision output normalizes synthetic derived-fact references in
  top-level support, option support, and dimension evidence fields back to those
  durable UUIDs. Knowledge influence identities remain separate diagnostics and
  never masquerade as durable EvidenceRecord identities.
- Decision semantics: the existing canonical `decision_snapshot_builder`.
- Execution truth: durable action EvidenceRecords and their explicit event time.
- Outcome and attribution truth: a durable `analysis.evaluate_outcome` payload
  validated as the existing `OutcomeEvaluation`.
- Persistence: the existing tool `EvidenceItem` → `EvidenceBridge` →
  `EvidenceRecord` path.
- Episode artifact ownership: recommendation (including the outer
  `knowledge.inform_decision` composition), outcome, and each dynamically resolved
  execution action must be the unique exact EvidenceBridge projection of its
  completed task, released lease, and task-output lineage. Shape and action labels
  alone cannot become a canonical episode.
- Historical learning ownership: a claimed learning-signal EvidenceRecord is
  accepted for Decision influence only when it is the unique, exact
  EvidenceBridge projection of a completed `tool.invoke` task, released worker
  lease, and matching append-only `task_output` lineage record. Caller-authored
  action/role/materialization JSON does not establish runtime provenance.
- Experience ingestion repeats that canonical learning-signal proof before
  `DecisionLearningSignal` validation, recurrence analysis, qualification, or any
  Knowledge Ledger write; the public declarative Evidence API therefore cannot
  author learning history.
- Current-condition ownership: an applicability EvidenceRecord may affect
  Decision scoring only when it is the unique, exact EvidenceBridge projection
  of a completed runtime action whose owner emitted `SOURCE_OBSERVATION`
  lineage and typed condition semantics. Every resolved scope or invalidation
  condition must cite such evidence and exactly match the owner-emitted
  condition key, state, subject identities, observation time, and
  `source_supplied_under_contract` basis. A genuine but unrelated observation,
  caller assertion, or reserved `independently_verified` label cannot acquire
  scoring authority.
- Tenant authority: tenant-filtered Evidence and ExecutionTask repositories.

### Possible pitfalls

Missing or foreign artifacts, wrong artifact roles, malformed payloads, ambiguous
executed actions, contradictory lineage, cross-mission linkage, impossible event
chronology, duplicate requests, and confusion between persistence order and event
order all fail closed. Missing execution proof remains `execution_unknown`; weak
attribution is preserved rather than rejected or upgraded.
Knowledge IDs, episode IDs, current applicability evidence, and synthetic influence
IDs are never substituted for historical durable learning-signal EvidenceRecords.
Declarative, derived, or computed EvidenceRecords cannot establish fresh current applicability;
historical learning signals remain explicitly non-independent lineage inputs.

### Invariants

- Recommendation EvidenceRecord identity deterministically owns `decision_id`.
- The same ordered artifact set owns one stable episode, feedback, and signal ID.
- Different recommendation artifacts remain different decisions even with equal prose.
- Repository reads are tenant-scoped and foreign UUIDs appear inaccessible.
- Historical Knowledge may cross mission boundaries within its tenant, but each
  source signal must prove its own mission-scoped task, lease, lineage, and bridge
  ownership chain.
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
  `SOURCE_OBSERVATION` lineage and prove the runtime task, released lease,
  task-output lineage, action-owned EvidenceItem, and exact bridge projection.
  The action-owned EvidenceItem must also emit the exact typed condition
  semantics claimed by Applicability. Missing lineage, opaque evidence IDs, or
  caller-authored evidence-to-condition meaning never implies authority.
- The output remains `DecisionLearningSignal` with `is_knowledge = false` and
  `is_policy = false`.

### Proof and non-goals

The adversarial service suite proves identity, tenant isolation, artifact role,
execution mismatch/unknown behavior, chronology, idempotency, and attribution
preservation. The real Knowledge-to-Decision integration produces historical
signals through queue, lease, dispatcher, materialization action, and EvidenceBridge,
then proves that an otherwise valid caller-forged learning record is rejected.
The same integration produces current applicability evidence through a canonical
read action and proves that a declarative forged `SOURCE_OBSERVATION` record, a
caller-claimed `independently_verified` basis, and a canonical runtime observation
about a different condition all fail before Decision scoring.
Registry, ability rollout, evidence bridge, ontology, and authority ledger suites
prove composition. This change does not aggregate experience, qualify knowledge,
infer causality, dispatch runtime work, or add persistence.

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
