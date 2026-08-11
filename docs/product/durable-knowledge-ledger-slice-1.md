# Durable Knowledge Ledger — Slice 1

## Boundary

The Durable Knowledge Ledger records proposition-bearing `KnowledgeQualificationResult` history and the exact
`QualifiedKnowledgeArtifact` emitted by Knowledge Qualification. Qualification remains the epistemic authority;
persistence neither requalifies a result nor establishes which historical assessment is current. The separate
[Knowledge Lifecycle Resolution](knowledge-lifecycle-resolution-slice-1.md) read model determines current authority
from complete proposition history without mutating the ledger.

The primary relational ledger contains tenant-owned, append-only qualification records and, only for qualified
results, immutable artifact records. Database row IDs, proposition keys, qualification IDs, and knowledge IDs remain
separate identities. Semantic uniqueness is tenant-scoped because upstream hashes do not encode ownership.

## Write contract

`knowledge.record_qualification` obtains tenant identity exclusively from `ActionRuntimeContext`, activates the
PostgreSQL tenant session, and commits the qualification and optional artifact in one transaction. Exact canonical
replay returns the existing row references. Reusing an identity for a different owner-model payload fails closed.
A result without a proposition is not ledger eligible and performs no database operation.

The ledger service reports writes as staged (`persistence_committed=false`) because it does not own its caller's
transaction. Only the action boundary changes that flag to true, and only after the primary-session commit succeeds.

The action is a disabled-by-default, approval-required `INTERNAL_WRITE`. Its `action_result_evidence` reports only
what persistence changed; it makes no claim about lifecycle authority, recommendation, policy, or behavior.

## Isolation and chronology

Both tables force PostgreSQL row-level security and use the established fail-closed tenant setting. The artifact's
composite foreign key prevents it from referencing another tenant's qualification row. Evaluation watermarks come
from qualification evidence; database creation time is only persistence chronology.

## Explicit non-goals

The ledger itself adds no lifecycle mutation or materialization, supersession writes, deletion, retrieval,
embeddings, TTL, policy generation, planner integration, or automatic qualification-to-persistence orchestration.
