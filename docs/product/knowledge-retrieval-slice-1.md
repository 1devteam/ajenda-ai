# Knowledge Retrieval — Slice 1

This read-only layer answers which tenant-owned, currently authoritative knowledge is semantically relevant to a typed query. Candidate discovery uses the immutable proposition JSONB payload, but database containment is only mechanical narrowing. The ontology owner's `compare_goal_semantics` primitive earns goal inclusion and lifecycle resolution exclusively earns current authority.

Only `ACTIVE` propositions with non-empty authoritative knowledge IDs are eligible. Every returned ID is resolved to exactly one tenant-owned artifact and its copied ledger columns are checked against the owner payload. Missing, duplicate, corrupt, or disagreeing authority fails closed. Results are grouped by proposition and mechanically ordered; no score or recommendation is produced.

Subject matching requires the exact semantic class set. Intervention and relationship matching are exact, except that an empty intervention filter is explicitly unconstrained. Scope and invalidation conditions are preserved but never executed. Each match therefore declares `applicability_determined = false`; corresponding epistemic limits explain unevaluated conditions and partial goal equivalence.

Retrieval identity hashes canonical query semantics, proposition keys, lifecycle projection IDs, authoritative knowledge IDs, and the algorithm. It excludes tenant identity, database UUIDs, clocks, creation timestamps, randomness, and input ordering.

The governed `knowledge.retrieve_current` action obtains tenant authority only from `ActionRuntimeContext`, activates the tenant session, performs no commit or mutation, and emits evidence describing candidate/current/match counts, exact authorities, goal comparisons, and epistemic limits. The disabled-by-default ability is an `INTERNAL_READ` with low risk.
