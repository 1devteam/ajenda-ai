# Ajenda Canonical Dependency Graph

## Purpose

The canonical dependency graph is Ajenda's repository-level architecture map and change-impact instrument. It combines generated source dependencies with semantic facts that imports cannot express, then drives blast radius, invariant selection, proof selection, completeness auditing, architecture decisions, and selective-CI shadowing.

The graph is intended to answer:

1. What does a changed component depend on?
2. What depends on the changed component?
3. Which runtime, security, data, configuration, external-service, and state-ownership boundaries are in the blast radius?
4. Which architectural invariants apply?
5. Which tests and proof obligations are required?
6. Does the current architecture contain a newly introduced semantic violation that is not part of the reviewed baseline?

## Canonical inputs

Generated inputs:

- `backend/**/*.py` — production Python modules and imports.
- `services/**/*.py` — standalone production services and imports.
- `frontend/src/**/*.ts` / `*.tsx` — frontend modules and relative imports.
- `tests/**/*.py` — direct test-to-production relationships.
- `alembic/versions/*.py` — migration/table/RLS semantics.
- production Python network-client usage — outbound HTTP/SMTP egress sinks.

Semantic input:

- `docs/contracts/dependency-graph.overlay.v1.json` — runtime, authority, security, state-ownership, external-system, reviewed exception/classification, acknowledgement, and invariant relationships that cannot be inferred safely from imports alone.

The generated JSON remains a build artifact rather than committed source. The durable source of truth is the generator, semantic inventory logic, and overlay.

## Graph model

Every node has a stable `id` and `type`. Source-backed nodes also carry a repository `source` path when one exists.

Major generated/static node classes include:

- `python_module`
- `frontend_module`
- `test_module`
- `migration`
- `database_table`
- `network_egress_sink`

Major semantic node classes include:

- `runtime`
- `security_boundary`
- `external_service`
- `state_resource`

Every edge has `from`, `to`, `type`, and `evidence`. Edge types are not interchangeable. Examples include `imports`, `tests`, `calls`, `credential_authority`, `egress_authority`, `governed_http`, `direct_network_egress`, `tenant_data_boundary`, `rls_enforced`, `claims_once`, `consumes_once`, and `reserves_capacity`.

Canonical direction is `consumer -> dependency`. Reverse traversal answers what a change can affect; forward traversal answers what the changed component relies on.

## Database and RLS semantics

The graph derives table facts from Alembic rather than treating PostgreSQL as one opaque tenant boundary.

For each migration it creates `migration:<revision-file>` nodes. For each table touched by `op.create_table()` or `op.add_column()` it creates `db:table:<table>` nodes and records:

- whether the table is tenant-associated (`tenant_id` present),
- `ENABLE ROW LEVEL SECURITY`,
- `FORCE ROW LEVEL SECURITY`,
- discovered policy names,
- tenant-isolation policy presence,
- `admin_bypass` presence,
- whether the RLS envelope is complete,
- whether the table is an explicitly reviewed cross-tenant/control-plane exception.

RLS emitted from migration loops is resolved for both named table collections and literal tuple/list/set loops. This matters because Ajenda migrations use both forms.

A tenant-associated table without the required RLS envelope becomes a `rls-missing:<table>` semantic finding unless it is explicitly classified as an exception. Historical gaps that predate the frozen graph audit may be surfaced as reviewed nonblocking gaps; they remain visible and are not treated as repaired.

The tenant-isolation invariant is therefore no longer considered globally satisfied merely because tenant-scoped DB sessions exist. Database-object coverage is part of the invariant.

## Production egress reconciliation

The graph inventories production Python modules that instantiate or invoke recognized HTTP/SMTP client libraries. Each source-backed network caller receives a `network_egress_sink` node.

Every discovered sink must be classified in the semantic overlay. Current classifications include:

- canonical governed authority,
- application identity/control-plane traffic,
- connector OAuth control-plane traffic,
- standalone adapter boundaries,
- reviewed direct lanes with their own contracts,
- known violations,
- unclassified egress.

An unclassified production sink is a blocking semantic finding. Known violations remain visible as baseline findings until repaired.

The overlay contains explicit external nodes for provider/runtime surfaces such as LLM, Resend, identity provider, OPA, SMTP, webhook destinations, and dynamically resolved egress, so production sockets do not disappear behind configuration-only relationships.

The scanner is an architecture guard for Ajenda's recognized application network-client lanes; it is not a general operating-system socket tracer. New transport libraries must extend the detector in the same change that introduces them.

## State ownership and concurrency semantics

Concurrency correctness cannot be proven by module imports alone. The graph therefore models state resources whose authority depends on exclusive ownership, atomic consumption, or reservation.

Current first-class state resources include:

- Redis task lease ownership,
- HTTP idempotency-key ownership,
- durable SMTP send claims,
- email-verification token consumption,
- bootstrap API-key promotion,
- customer refresh-token consumption,
- API-key quota capacity.

Corresponding invariants cover:

- lease-owner integrity,
- durable idempotency ownership and abandoned-claim recovery,
- atomic single-use secret consumption before successor authority is minted,
- atomic quota reservation under concurrency.

These are semantic contracts. The graph records where the resource lives and which component owns/transitions it; dedicated implementation tests or validators must prove the atomicity property itself.

## Semantic findings and ratchet

The generated graph contains `semantic_findings` in addition to nodes, edges, metrics, and invariants.

A finding can be:

- a new blocking violation,
- a reviewed nonblocking historical gap,
- a known frozen violation represented by the graph.

`acknowledged_findings` in the overlay are a detector baseline only. An acknowledgement means: "this condition is already known, so introducing the detector must not make the baseline impossible to merge." It does **not** mean fixed, accepted as desirable architecture, or closed in the remediation ledger.

The completeness audit fails when a blocking semantic finding is not acknowledged. This gives the graph a ratchet:

- existing known defects stay visible,
- new defects of the modeled class fail closed,
- acknowledgements should be removed only when implementation repair and regression proof establish that the finding no longer exists.

## Change-impact analyzer

Run:

`python scripts/validation/graph_impact_analysis.py --changed-file <path> --json`

The report includes:

- changed graph nodes,
- unmapped changed files,
- transitive upstream consumers,
- transitive downstream prerequisites,
- impacted tests,
- affected semantic nodes,
- semantic prerequisites,
- relevant invariants,
- risk domains.

Migrations, database tables, egress sinks, and state resources participate in the same traversal as runtime/security/external nodes. A migration that changes a tenant table can therefore reach the tenant DB boundary and select the tenant-isolation invariant instead of remaining an unmapped file.

## Proof selection

Run:

`python scripts/validation/graph_proof_selection.py --impact-report artifacts/graph-impact-report.json --json`

Proof selection consumes graph impact and emits required tests/gates plus manual review obligations.

Dedicated bundles now include:

- tenant-isolation proof, including semantic RLS inventory proof,
- governed-egress proof, including egress reconciliation proof,
- state-ownership proof for lease/idempotency/single-use-secret/quota invariants.

A relevant invariant with status `known_violation` requires explicit review that the change does not expand the violation. The acknowledgement should only be removed with corresponding repair proof.

## Completeness audit

Run:

`python scripts/validation/graph_completeness_audit.py --json`

The audit reports:

- directed betweenness centrality,
- direct/transitive consumer and dependency counts,
- architecture-boundary classification,
- boundary-to-boundary edge matrix,
- static cycle classification,
- static/semantic reconciliation,
- semantic finding counts,
- acknowledged findings,
- unacknowledged blocking findings,
- missing semantic edge evidence,
- missing invariant source files.

Integrity PASS requires all semantic edge evidence and invariant source files to exist **and** no blocking semantic finding to remain unacknowledged.

This is intentionally stronger than the original completeness audit, which validated evidence completeness/topology but could not detect whether a tenant table lacked RLS or whether production network calls escaped the modeled egress path.

## Invariant statuses

Invariant status is explicit. Supported architecture states include enforced rules/design/doctrine/meta-invariants, `policy_drift`, and `known_violation`.

`known_violation` is not a success state. It lets the graph truthfully represent architecture that currently violates its intended invariant while preserving a ratcheted detector during remediation.

## CI lifecycle

`.github/workflows/dependency-graph.yml` runs when graph-sensitive application, frontend, Alembic, graph-contract, validator, or graph-test files change.

The job:

1. regenerates the canonical graph,
2. runs graph and semantic-inventory regression tests,
3. computes PR impact,
4. selects proof,
5. runs the completeness/semantic ratchet,
6. composes the architecture decision,
7. uploads the graph and reports as workflow artifacts.

The intended control chain remains:

`diff -> graph -> blast radius -> invariants -> proof selection -> completeness audit -> architecture decision manifest -> selective-CI shadow`

The new semantic inventory strengthens the `graph`, `invariants`, proof-selection, and completeness stages; it does not replace the rest of the chain.

## Maintenance rules

1. Generated source/test/table/egress facts must come from source rather than manual duplication.
2. Runtime/authority/state semantics and reviewed exceptions must carry repository evidence in the overlay.
3. A new tenant-owned table must either receive the required RLS envelope or an explicit, reviewed cross-tenant/control-plane classification.
4. A new production network transport/sink must be detected and classified in the same PR.
5. A new single-owner, single-use, or quota-reservation authority must be represented as a state resource with an applicable invariant and proof.
6. A new architecture zone must receive an explicit boundary classification.
7. Known findings must not be removed or marked repaired merely to make the graph green; their acknowledgement is removed only when the underlying defect and regression proof are addressed.
