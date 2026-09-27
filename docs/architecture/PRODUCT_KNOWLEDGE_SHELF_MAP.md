# Product Knowledge Shelf Map

This is the GRAFT+ map for Ajenda's product-knowledge expansion. It projects
one canonical, declarative product catalog through existing shelves; it does
not introduce a parallel lattice runtime or a new execution path.

| Shelf | Existing source of truth | Product-knowledge projection |
| --- | --- | --- |
| Library / ontology | `backend/services/ontology/` | `product_knowledge.py` owns typed capability facts, versions, aliases, provenance, and limitations. |
| CRM / tenant context | Business Profile and tenant internal records | Approved `product_catalog` facts are normalized into the profile brief and account projection. |
| Interpreter | `read_business_profile` outcome and existing ability vocabulary | Product questions continue to resolve to the governed profile/retrieval job; no new authority-bearing outcome is added. |
| Storage / evidence | Business Profile JSONB, retrieval evidence, knowledge ledger | Tenant facts remain explicitly approved and tenant-scoped; retrieval emits product-catalog provenance. |
| Algorithms / intelligence | `backend/services/ontology/algorithms.py` and `IntelligenceEnvelope` | Versioned deterministic results evaluate completeness, source confidence, identity duplicates, and service-area fit; results are read-model signals only. |
| GTM | Existing canonical outcomes and BusinessJob catalog | Catalog entries reference existing outcomes/jobs only; they do not dispatch actions. |
| Vertical | Existing vertical know-how contracts | Applicability is declarative metadata, leaving vertical composition and runtime resolution authoritative. |

## GRAFT+ invariants

- Product knowledge is a read model and cannot register handlers, invoke tools,
  resolve credentials, approve work, or grant runtime authority.
- Unknown or malformed tenant product entries are ignored (fail closed) rather
  than becoming executable claims. Duplicate canonical IDs reject the complete
  tenant catalog projection instead of preserving ambiguous definitions.
- Historical `know_how_id` and `know_how_version` provenance remains unchanged.
- CRM projection and retrieval are tenant-scoped and use existing governed
  repositories/actions.
- Existing canonical outcomes, BusinessJobs, ActionRegistry, browser runtime,
  evidence, and side-effect policy remain the execution boundary.
- Algorithm results carry an input hash, evidence references, confidence,
  provenance, and an explicit read-model authority class. They may refine
  composition or evaluation but cannot create jobs, credentials, approvals, or
  runtime actions.
- Every non-empty persisted algorithm tuple is deterministically recomputed by
  `IntelligenceEnvelope` validation on deserialization. Unknown algorithms,
  provenance drift, hash drift, authority flags, or output drift fail closed;
  legacy envelopes with no algorithm tuple remain readable. This makes each
  proposal/lifecycle read a recurring integrity check rather than a one-time
  composition assertion.
- The Command Center success rate uses tenant-wide `total_count` and
  `completed_count` aggregates, not only the newest page of missions. While
  active work exists, the dashboard refreshes that read model every 15 seconds
  so completion changes the displayed percentage without a manual reload.

## Blast radius

The additive changes are limited to the ontology product contract, profile
fact normalization/projection, and the existing retrieval read action. No
database migration, queue, worker, provider adapter, or runtime admission path
is changed. Existing profile and mission composition contracts remain
backward-compatible.

## Runtime proof

The adversarial expansion block uses the public onboarding, profile-fact,
mission-composition, launch, worker, and runtime-evidence paths with two
independent tenants. Persisted retrieval evidence proves that tenant-specific
catalog entries remain isolated, duplicate catalogs are absent from the typed
`profile_brief` projection, malformed entries do not project, provenance and
version fields survive valid projection, and every catalog entry remains
`grants_execution_authority: false`. Both missions completed with no runtime
contradictions or first divergence.

The ten-mission expansion campaign also persisted `gtm.evidence_completeness.v1`
and `gtm.source_confidence.v1` in every composition record. All results were
evaluated with zero blocking gaps, reproducible input hashes, and
`grants_execution_authority: false`.

The live post-change proof created a tenant through the public API, ran a
worker-backed mission, and observed the list transition from
`total_count=0, completed_count=0` to `total_count=1, completed_count=1` with
the mission `completed`. Runtime evidence had no contradictions or first
divergence and retained `grants_execution_authority: false`. The same proof
also exposed an existing profile-deliverable projection gap: the mission
completed and its evidence persisted, but that specific read-only profile
deliverable endpoint returned no projection. That gap is recorded rather than
treated as a successful artifact.
