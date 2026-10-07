# Pass 3 internal CRM closure record

Date: 2026-10-07

Baseline: `main` at `1b3ae139299975686816190a70552cad2e67bf5a`.

Branch: `pass3/internal-crm-closure`.

## Scope and UPG/LAP

Responsibility: close the tenant-owned internal CRM value chain through
retrieval, observation, qualification, enrichment, governed persistence,
read-back, evaluation, reconciliation, and a customer-readable deliverable.

Authority boundaries: composition selects declarative abilities; `ExecutionTask`
and the queue-backed worker own execution; `tenant_operator` may compose and
run but cannot approve `record.write`; an independent human session with
`outcome_review:manage` approves the payload-bound side effect.

Dependencies inspected before editing: intent interpretation, capability
resolution, plan compilation, CRM actions/provider, observation artifacts,
acceptance evaluation, deliverable read model, review queue, coordinator,
worker rollup, repositories, runtime evidence, tests, and the canonical
dependency graph.

Pitfalls considered: public-discovery substitution, fixture truth leakage,
unconsumed enrichment, malformed typed artifacts, approval before bindings are
durable, persisted-ID mismatch, paused review-hold rollup, duplicate writes,
tenant crossover, and stale runtime admission evidence.

Invariants proven: tenant-scoped reads/writes, fail-closed side-effect review,
machine self-approval denial, dependency-ready human approval, typed artifacts,
durable evidence, effect read-back, idempotent CRM fixture writes, no public
search branch for the internal source, and no execution authority from a
read-only projection.

## Capability matrix

| Requirement | Existing owner | Implementation/proof | Missing? |
|---|---|---|---|
| Tenant-scoped internal CRM retrieval | CRM provider/service | `record.search` plus live public CRM fixtures | No |
| Contact/source observation | `research.observe_contacts` | Real tenant contact relationships and `tenant_internal_crm` evidence | No |
| Qualification | `sales.qualify` | Typed `qualified_prospects`, score and reasons | No |
| Enrichment | `gtm.lead_enrich` | Dependency-bound output consumed by persistence | No |
| Typed artifacts/evidence | action contracts and evidence repository | Contract tests and worker evidence | No |
| Governed persistence | `ExecutionCoordinator` / `record.write` | Pending review, payload binding, queue admission | No |
| Independent review | review queue/RBAC | Machine `403`; human owner session succeeds after `409` dependency hold | No |
| CRM read-back/effect verification | CRM provider | Three verified records and content hashes | No |
| Opportunity projection | CRM provider/action | Three durable opportunity IDs | No |
| Acceptance/evaluation | `mission_acceptance` and rollup | Acceptance `met`, mission `completed` | No |
| Deliverable projection | deliverable runtime read model | Three typed customer-readable prospects | No |
| Retry/idempotence | existing CRM write/recovery path | Repeated public fixture PUTs preserve three IDs; unit coverage | No |
| Tenant isolation | public authorization boundaries | Cross-tenant mission/review access denied in proof | No |
| Assurance/calibration history | Pass 2 | Not in Pass 3 scope | Deferred |

## GRAFT+ pre-change result

The current-main graph was generated with
`build_dependency_graph.py`: 1,631 nodes and 4,701 edges. Candidate impact
analysis predicted 40 changed nodes, 333 upstream consumers, 232 downstream
dependencies, 150 semantic nodes, 196 impacted tests, 9 invariants, 3 risk
domains, 8 proof bundles, and 198 selected tests. It identified the following
missing edges/owners before implementation:

1. Internal CRM source semantics were erased when a write was also requested.
2. Generic persistence expanded a public discovery dependency.
3. Enrichment was not consumed by persistence.
4. Local CRM contacts were not represented as tenant-owned observations.
5. Observation candidates did not satisfy their declared artifact contract.
6. Runtime rollup could not resume a mission paused by review-hold reconciliation.
7. Acceptance mixed upstream account rows with persisted contact rows.

No queue-admission mutation was predicted or implemented speculatively.

## Changes made

- Preserved explicit internal CRM source semantics through intent interpretation
  and capability resolution.
- Added CRM contact observation bindings and truthful normalized artifact fields.
- Bound enrichment output into governed CRM persistence.
- Used the existing CRM provider for persisted-ID/opportunity identity and
  idempotent opportunity projection.
- Made paused review-hold missions re-enter `running` before terminal rollup.
- Made acceptance prefer explicit persisted CRM records over upstream source
  aliases, preventing false read-back/projection failures.
- Updated the canonical `ExecutionCoordinator` approval owner to reconcile the
  exact reviewed task into the tenant-scoped runtime admission receipt only
  after queue enqueue succeeds; the update is idempotent, removes only that
  task's pending-review blocker, and preserves unrelated blockers.
- Added focused regression tests for each boundary.

## Live proof

Canonical public proof completed successfully on the deployed final runtime:

- tenant: `36968df5-052f-4314-afa6-f44686e7903c`
- mission: `d1c3b9d3-52c2-43f6-8e58-f0b5b22332f7`
- launch admitted five tasks: four queued and one pending review.
- machine approval was denied with `403 missing permission:
  outcome_review:manage`.
- owner login exposed `outcome_review:manage`; approval returned dependency-not-
  ready `409` responses until observation, qualification, and enrichment were
  durable, then returned `200 queued`.
- worker completed the governed write, verified three CRM records by read-back,
  and produced three opportunity projections.
- mission acceptance was `met`; lifecycle was `completed`.
- runtime reconciliation was `aligned`; structural and semantic layers were
  aligned; contradictions were empty; `first_divergence` was null.
- deliverable completion was true with three prospects containing company name,
  website, qualification score, and qualification evidence.
- launch evidence showed the reviewed task initially in `pending_review`; after
  approval the public queue was empty and the task completed. The first clean
  worker proof exposed the stale receipt as
  `task:<id>:runtime_state_without_queue_admission`, despite one successful
  lease/evidence record for every task. The canonical owner was
  `ExecutionCoordinator.approve_review_and_queue`, which now records the exact
  task only after successful enqueue. The final proof passed with no runtime
  contradictions and no first divergence.

The read model retains `evidence_status=blocked` with
`preview_missing_required_evidence` because the pre-runtime epistemic preview
correctly lacked runtime source observation. Runtime evidence itself is
materialized and acceptance/read-back passed; this is retained as a phase
distinction rather than treated as a contradiction or hidden.

## Post-run GRAFT+ reconciliation

Post-run reconciliation was rerun against the exact final working tree. The
final graph contains 1,632 nodes and 4,706 edges. Working-tree impact analysis
reported 18 changed files, 90 changed nodes, 291 upstream consumers, 334
downstream dependencies, 150 affected semantic nodes, 197 impacted tests, 9
invariants, 3 risk domains, and 2 unmapped files. The two unmapped files are
intentional non-production graph artifacts: the public proof entry point
(`deploy/scripts/pass3-internal-crm-proof.py`) and this validation record. All
18 files are accounted for; no implementation, schema, migration, deployment,
or runtime-authority file is unmapped. The graph predicted the composition,
CRM/action, acceptance, worker-rollup, coordinator, and queue-receipt surfaces;
the live proof additionally revealed the stale post-review admission edge,
which was then fixed at its canonical owner and covered by unit tests.

No provider, onboarding, presentation, migration, or Pass 2 assurance surface
was changed.

Deferred: recurring assurance, durable findings/history, runtime-derived
epistemic calibration, external providers, SaaS/onboarding expansion, UI, and
production hardening outside this lane.
