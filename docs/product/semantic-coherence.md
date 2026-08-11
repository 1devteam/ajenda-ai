# Cross-layer semantic coherence

## Invariants

**Instance identity ≠ semantic identity ≠ lineage ≠ context ≠ equivalence ≠ independence.**

Downstream intelligence may consume these distinctions; it may not recreate them from prose,
coincidental IDs, outcome labels, or guessed relationships. Unknown remains unknown: it is neither
equivalent nor independent.

## Definitions and ownership

- **Instance identity** names one artifact. Business Ontology owns business-object instance identity
  as `BusinessObjectType + object_id`; Goal owns `goal_id`; Decision owns `option_id`; Evidence owns
  its artifact ID.
- **Semantic identity** names what an artifact means across instances. Business Ontology owns object
  class, Goal/KPI own objective and measurement signatures, and Decision owns `intervention_key`.
- **Context** records the conditions under which an observation applies. Context can restrict a
  comparison but cannot manufacture semantic identity.
- **Lineage** records evidence origin, source identity, roots, parents, ancestors, and resolution.
  Evidence owns this contract and preserves derivation through summaries and aggregations.
- **Equivalence** is a deterministic comparison of owner-produced semantic signatures. An equal
  explicit objective key earns goal equivalence; identical KPI semantics without complete objective
  identity earn partial equivalence only.
- **Independence** is a conclusion from resolved evidence lineage. A distinct artifact ID is not
  proof of a distinct source observation.

## Conservative compatibility

New fields are additive to V1 contracts. A missing `objective_key` is not equal to another missing
key. Matching KPI signatures may earn partial comparison, which cannot alone produce supported
recurrence. A missing Decision `intervention_key` may use the transitional Experience
`recommendation_class`, but disagreement fails closed with `intervention_semantic_conflict`.
Unknown evidence lineage produces indeterminate independence. The historical
`source_verified` chronology value means source-supplied under contract; it does not claim that
Ajenda independently verified the source.

No database migration is required for evidence lineage: durable `EvidenceRecord` already persists
`provenance_metadata` as JSONB, and the evidence bridge serializes the typed lineage contract into
that existing field. Goal, Decision feedback, Outcome, and Experience contracts in this slice are
serialized Pydantic artifacts rather than dedicated relational columns.

## Guardrails

Same status ≠ same semantics. Same prose ≠ same intervention. Different IDs ≠ independence.
Same type ≠ same instance. Same source label ≠ same lineage. Unknown ≠ equivalent. Unknown ≠
independent. Relationship traversal and LLM/prose inference are intentionally outside this slice.
Experience consumes owner-produced signatures and lineage; it does not own substitutes for them.
