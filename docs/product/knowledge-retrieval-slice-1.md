# Knowledge Retrieval — Slice 1

This read-only layer answers which tenant-owned, currently authoritative knowledge is semantically relevant to a typed query. Candidate discovery uses the immutable proposition JSONB payload, but database containment is only mechanical narrowing and must remain a superset of every match the owner comparator could accept. For a query carrying both objective and KPI semantics, objective equality **or** KPI containment earns candidacy; the ontology owner's `compare_goal_semantics` primitive still earns final goal inclusion and lifecycle resolution exclusively earns current authority.

Only `ACTIVE` propositions with non-empty authoritative knowledge IDs are eligible. Every returned ID is resolved to exactly one tenant-owned artifact and its copied ledger columns are checked against the owner payload. Missing, duplicate, corrupt, or disagreeing authority fails closed. Results are grouped by proposition and mechanically ordered; no score or recommendation is produced.

Subject matching requires the exact semantic class set. Intervention and relationship matching are exact, except that an empty intervention filter is explicitly unconstrained. Scope and invalidation conditions are preserved but never executed. Each match therefore declares `applicability_determined = false`; corresponding epistemic limits explain unevaluated conditions and partial goal equivalence.

Retrieval identity hashes canonical query semantics, proposition keys, lifecycle projection IDs, authoritative knowledge IDs, and the algorithm. It excludes tenant identity, database UUIDs, clocks, creation timestamps, randomness, and input ordering.

Semantic-set fields are canonicalized at query construction: subjects, KPIs, intervention keys, and relationship types are deduplicated and mechanically sorted without case folding, aliases, hierarchy expansion, or fuzzy interpretation. Retrieval also returns a typed inspection trace covering every candidate submitted to lifecycle, every lifecycle projection received, frontier qualification authority exposed, and every authoritative artifact row Retrieval loaded. Action evidence derives its inspected records from that trace rather than only from successful matches.

The governed `knowledge.retrieve_current` action obtains tenant authority only from `ActionRuntimeContext`, activates the tenant session, performs no commit or mutation, and emits evidence describing candidate/current/match counts, exact authorities, goal comparisons, and epistemic limits. The disabled-by-default ability is an `INTERNAL_READ` with low risk.
