# Knowledge Lifecycle Resolution — Slice 1

## Boundary and authority

Knowledge Lifecycle Resolution is a read model over one tenant-owned proposition's complete durable qualification
history. The immutable `qualification_payload` remains semantic truth; indexed ledger columns and linked artifact
rows are validated against their owner models before projection. Resolution performs no write, qualification,
retrieval, policy generation, planning, scoring, or behavior change.

The pure resolver accepts frozen `KnowledgeLifecycleHistoryItem` values and returns a frozen
`CurrentKnowledgeState`. The repository adapter activates tenant-scoped PostgreSQL access, loads only the named
proposition and its qualification-linked artifacts, fails closed on corrupt payloads or linkage, and invokes the
pure resolver.

Artifact discovery follows `qualification_record_id`, the database foreign-key relationship, rather than copied
semantic identity columns. After discovery, the adapter validates every copied qualification, proposition, source,
algorithm, and artifact identity against the linked qualification and owner payloads. Empty history must be resolved
with an explicit `proposition_key`; absence therefore retains the identity of the proposition that is absent and
produces a proposition-specific projection identity.

## Deterministic chronology

`evaluation_watermark` is the sole epistemic chronology. The maximum known watermark defines the current frontier;
all distinct assessments at that frontier participate. Database creation time, row order, persistence order, and
UUID order never establish authority. Undated records cannot supersede a known frontier. If all records are undated,
one distinct identity is projected while multiple distinct identities produce `CONTESTED` with
`temporal_authority_unresolved`.

At one frontier, equal statuses map directly: qualified to `ACTIVE`, provisional to `PROVISIONAL`, insufficient to
`ABSENT`, contested to `CONTESTED`, and invalidated to `INVALIDATED`. Invalidation is a same-frontier veto. Other
status disagreement is contested. Later evidence may weaken, invalidate, or requalify the proposition without
mutating historical rows.

Only `ACTIVE` exposes authoritative knowledge IDs. All canonical identifier, reason, limitation, and unordered-ID
collections are sorted. The projection identity hashes only the proposition, frontier, authoritative qualification
and knowledge identities, lifecycle status, and algorithm, so input and persistence order cannot affect it.

## Ability surface

`knowledge.resolve_current_state` takes only a `proposition_key`; tenant authority comes from
`ActionRuntimeContext.tenant_id`. It uses the primary session factory with tenant activation and returns
`action_result_evidence` describing the projection and its epistemic limitations. The action is a low-risk,
approval-free, disabled-by-default `INTERNAL_READ` provided by `ajenda_knowledge`.

## Compatibility, rollback, and non-goals

This additive slice changes no schema or migration and does not materialize current state. Rollback removes the read
service, action, and manifest without altering ledger history. Lifecycle persistence, search, embeddings, ranking,
decision weighting, planner integration, adaptation, TTL, deletion, cross-proposition inference, and LLM arbitration
remain explicit non-goals.
