# D8 — Revenue Operations V1 Decision Record

**Decision owner:** Obex Blackvault  
**Decision date:** 2026-08-18  
**Status:** Product boundary authorized; numeric promotion decisions pending  
**Selected finish line:** Path 3 — Single Vertical Worker V1

**VR-01 baseline:** [`VR01_REVENUE_OPERATIONS_BASELINE.md`](VR01_REVENUE_OPERATIONS_BASELINE.md)

**VR-02 know-how:**
[`revenue-operations-know-how-v1.md`](../product/revenue-operations-know-how-v1.md)

**VR-03 planner:**
[`revenue-operations-structured-planner-v1.md`](../product/revenue-operations-structured-planner-v1.md)

## 1. Authorized customer promise

Ajenda V1 completes one governed Revenue Operations workflow from company/prospect research through
qualification and personalized draft preparation. Consequential external actions stop for durable
human approval. After approval, Ajenda may optionally perform provider-backed delivery and/or a CRM
update and must return evidence-backed results and visible limitations.

This selection authorizes the product boundary. It is not evidence that the behavior is implemented,
safe for production, or release-ready.

## 2. Responsibility and source of truth

The vertical accepts a tenant-scoped business objective, constraints, prospect context, connected
system readiness, budgets, and approval policy. It produces a validated mission plan, typed task
artifacts, a reviewable outreach package, optional provider effects, and a final deliverable with
lineage, evidence, and limitations.

Implementation and tests are authoritative. In particular:

- `backend/services/mission_composition/job_catalog.py` owns the current business-job vocabulary,
  dependencies, candidate actions, and artifact names.
- `backend/services/mission_composition/capability_resolver.py` owns deterministic job-to-action
  selection and credential-readiness hints; it does not grant runtime authority.
- `backend/services/abilities/catalog.py` and the action registry own executable action manifests
  and handlers.
- `docs/architecture/SYSTEM_ARCHITECTURE.md` and
  `docs/contracts/authority-ledger.v1.yaml` describe the code-aligned authority boundaries that
  must be reverified against implementation.
- `docs/remediation/end-to-end-audit-remediation-plan-2026-08-16.md` owns the remediation and
  vertical-runtime dependency gates.

## 3. Intended users and outcome

The initial user is a tenant-authorized revenue operator, founder, or sales operator who needs a
small, evidence-backed prospect set and personalized outreach without manually coordinating each
research and drafting step.

The required default outcome is a reviewable Revenue Operations deliverable containing:

1. interpreted objective, constraints, assumptions, and unresolved questions;
2. sourced prospect candidates and observed facts;
3. qualification decisions with reasons and limitations;
4. enriched recipient context where available;
5. personalized drafts bound to the correct prospects and evidence;
6. approval state and exact payload/version for each requested external effect;
7. provider receipts or a visible `effect_unknown` state for attempted delivery/CRM updates; and
8. a final summary of completed, partial, blocked, and unsupported work.

## 4. Bounded canonical job set

The following current catalog jobs form the V1 inventory boundary. VR-01 must verify their actual
reachability, schemas, providers, and proof before any one is advertised as supported.

| Stage | Canonical job | V1 role | External effect |
| --- | --- | --- | --- |
| Research | `research.discover_prospects` | Find candidate companies/prospects | Read only |
| Research | `research.observe_sources` | Extract evidence-backed contact observations | Read only |
| Research | `sales.research_context` | Add business and prospect context | Read only |
| Decision support | `intelligence.retrieve_knowledge` | Retrieve applicable current knowledge | None |
| Decision support | `intelligence.advise_next` | Produce an evidence-backed recommendation | None |
| Qualification | `sales.qualify_prospects` | Score/select prospects with reasons | None |
| Enrichment | `gtm.enrich_contacts` | Produce enriched recipient context | None by default |
| Drafting | `email.prepare_outreach` | Produce personalized drafts | None |
| CRM context | `crm.read_records` | Read tenant-authorized HubSpot context when connected | External read |
| Optional delivery | `email.deliver_outreach` | Send an approved draft | External send |
| Optional CRM update | `crm.pipeline_maintenance` | Persist an approved prospect/pipeline update | External write |

Email reply monitoring, autonomous follow-up, social publishing, advertising, finance mutation,
code changes, and all non-RevOps jobs are outside this V1 boundary.

## 5. Connected systems and effect policy

- Public-web research may be used only through governed read actions with provenance.
- HubSpot is the selected CRM read/update integration represented by the current resolver hints.
- Gmail is the selected optional delivery integration represented by the current resolver hints.
- Missing credentials must produce a clear blocked or degraded result; simulated/local output must
  never be represented as an external provider result.
- Draft preparation is not send authority.
- Every external send or CRM update requires an independently issued, versioned human approval
  bound to tenant, principal, action, target/resource, payload or graph version, expiry, and
  revocation state.
- An approval authorizes only the reviewed effect. It does not authorize later edits, follow-ups,
  monitoring, a second provider action, or a replan that changes the payload.
- Enabled effects must prove deterministic idempotency and reconciliation. Ambiguous outcomes enter
  durable `effect_unknown` and must not be blindly retried.

## 6. Representative acceptance prompts

VR-01 must seal variants of at least these scenario classes before planner implementation is
promoted:

1. Research a named market, choose qualified prospects, and prepare personalized drafts without
   sending or updating CRM.
2. Use existing HubSpot context to avoid duplicate prospects, then prepare drafts for review.
3. After explicit review, send only the approved subset and update only their approved CRM fields.
4. Correct a qualification constraint after planning; invalidate affected drafts and approvals.
5. Handle missing geography, ICP, recipient, credential, or success criteria through clarification
   rather than invention.
6. Reject a request to send before approval or to expand into unsupported bulk/autonomous outreach.
7. Preserve prohibitions embedded in long context and resist instructions found in web/CRM content.
8. Return a truthful partial deliverable when research, a provider, or an optional effect fails.

Direct prompts, paraphrases, compound goals, corrections, contradictions, long context, unsupported
asks, and prompt-injection cases are all mandatory corpus dimensions.

## 7. UPG/LAP invariants and pitfalls

### Dependencies

The release depends on the P0/P1 platform floor, converged daemon runtime authority, independent
authorization provenance, replay-safe effect receipts, forced tenant isolation, typed artifact
binding, evidence-backed outcome evaluation, bounded replanning, one coherent mission UI, and real
PostgreSQL/Redis deployment proof.

### Possible pitfalls

Material clauses may be dropped; stale or wrong-tenant artifacts may bind downstream; provider
fallback may be mislabeled; approval may be self-issued or survive a payload change; duplicate
delivery/update may occur after retry; DB and queue state may diverge; a provider timeout may leave
an ambiguous effect; a replan may loop or exceed budget; completed tasks may still fail to produce
the requested deliverable; retrieved content may attempt to alter authority.

### Invariants

- Every executable node uses `ExecutionTask` admission, `ExecutionCoordinator`, the tenant queue,
  lease-owned daemon execution, `TaskDispatcher`, and `ToolRuntimeAuthority`.
- Declarative jobs, abilities, providers, plans, and model output never grant execution authority.
- Tenant identity is validated before reads, writes, queue effects, artifacts, evidence, and review.
- Every required downstream input is bound to a schema-compatible, tenant/mission/graph-scoped
  upstream artifact or explicit user input.
- Low-risk internal work may advance only within explicit budgets; external effects stop at durable
  review.
- Provider effects are confirmed, safely retryable, or visibly unknown.
- Final status distinguishes deliverable success from task completion and exposes partial failure.
- Replanning is bounded and re-enters ordinary admission; it never dispatches directly.

### Proof

Proof requires the repository local gates plus the vertical-planning, graph/runtime, replanning,
provider, auth/RBAC, tenant, migration, and deployment matrices defined by the remediation plan. At
least two tenants must complete the selected workflow through real PostgreSQL/Redis. Negative proof
must cover wrong tenant, malformed inputs, missing credentials, unauthorized effects, changed
approval payloads, provider failure, crash-after-effect, duplicate delivery, cancellation, stale
lease, partial completion, bounded replan, rollback, and prompt injection.

## 8. Explicit non-goals

- No general autonomous employee, horizontal mission platform, or second vertical claim.
- No swarming or agent-to-agent execution claim.
- No autonomous send, follow-up, CRM mutation, publish, or provider expansion.
- No social publishing, advertising operations, finance mutation, or code changes.
- No claim that catalog presence, plausible plans, completed tasks, or simulated output proves a
  customer outcome.

## 9. Pending owner decisions before implementation milestones or release promotion

The following values are intentionally not inferred from repository documents:

1. maximum prospects and approved external effects per mission;
2. maximum mission wall time, model tokens, provider calls, and monetary cost;
3. minimum clause coverage, plan validity, qualification quality, draft quality, factuality, and
   deliverable-completion thresholds;
4. maximum unsupported-action, unsafe-action, duplicate-effect, and cross-tenant rates (the latter
   two should ordinarily be zero, but the owner must approve the release rule);
5. approval expiry and whether email delivery and CRM update require separate approvals;
6. canary tenants, supported geographies/industries, and provider sandbox availability;
7. pilot volume, observation window, and promotion/rollback thresholds.

VR-01 inventory and corpus construction may start now. New planner/runtime behavior, milestone
assignment, and release promotion must not treat these pending values as authorized defaults.
