# Knowledge Applicability Resolution — Slice 1

## Boundary

Semantic relevance is not applicability. This read-only layer starts with canonical Knowledge Retrieval and earns a current-context judgment only from typed condition assertions. Retrieval remains the owner of lifecycle-current semantic matches and continues to preserve conditions with `applicability_determined=false`; Applicability is the separate owner of `APPLICABLE`, `PARTIALLY_APPLICABLE`, `NOT_APPLICABLE`, `INSUFFICIENT_CONTEXT`, and contextual `INVALIDATED` results.

The production `knowledge.evaluate_applicability` action accepts a Retrieval query plus a typed context, activates the runtime tenant, invokes canonical Retrieval once, and evaluates all matches in memory. It never trusts caller-authored `RetrievedKnowledgeMatch` JSON.

## Deterministic semantics

Condition keys are opaque canonical tokens compared by exact identity. Scope ACTIVE is satisfied, scope INACTIVE is not applicable, and scope UNKNOWN or absent is insufficient context. Invalidation ACTIVE is contextually invalidated, INACTIVE is cleared, and UNKNOWN or absent is insufficient context. Precedence is contextual invalidation, scope mismatch, insufficient context, partial applicability, then full applicability. Partial owner Goal equivalence cannot be upgraded beyond partial applicability.

The current context separates exact `BusinessObjectRef` instances from owner-produced semantic classes and rejects incoherence or duplicate condition keys. Assertion evidence, observation time, and `ObservationVerificationBasis` remain visible. Caller-asserted and unknown bases add a limitation but do not create a second trust-ranking policy. Free-form `BusinessStateSnapshot.attributes`, prose, absence, fuzzy matching, and LLM inference cannot establish condition truth.

## Authority, evidence, and persistence

The action is a disabled-by-default, low-risk `INTERNAL_READ` that emits `action_result_evidence`. Retrieval's Knowledge/Lifecycle records are reported as inspected; opaque assertion evidence IDs are separately reported as referenced, not inspected. Deterministic IDs include the Retrieval authority, relevant assertion state/provenance/evidence/time, and evaluation time while excluding assertion ordering and unrelated assertions.

Contextual `INVALIDATED` does not mutate or redefine global Knowledge Lifecycle invalidation. No Knowledge Ledger, Lifecycle, decision, mission, scoring, queue, or runtime state is changed. There is no Applicability table or migration.

## Non-goals

Decision Support, option ranking, causal inference, StrategyEngine, policy generation, Experience, Qualification, event-stream state reconstruction, a generic rules engine, mission planning, and automatic execution are outside this slice.
