# Internal CRM capability lane — Pass 3 closure record

**Status:** closure proof in progress  
**Date:** 2026-10-07  
**Branch:** `test/pass3-internal-capability-closure`

## Pass objective

Close one real internal Ajenda customer-value lane through the existing governed runtime:

`retrieve → observe → qualify → enrich → persist/read-back → evidence → reconcile/evaluate → complete`

Pass 3 does not add external-provider credentials, relax side-effect policy, or allow machine execution to approve its own writes.

## Pre-change findings

The Pass 3 audit found three implementation defects and one proof-harness defect.

1. `crm.internal_persistence` hard-required `research.discover_prospects`. An instruction explicitly scoped to Ajenda internal CRM could therefore carry an unnecessary public-discovery branch even though `record.search` already supplied the authoritative prospect source.
2. `gtm.enrich_contacts` could be selected alongside `crm.internal_persistence` without a dependency/binding from `enriched_prospects` into `record.write`. Enrichment could succeed and then become an unconsumed side branch.
3. `gtm.lead_enrich` read `contacts` but not the governed `observed_contacts` artifact shape carried through qualification, so real observed email/phone evidence could be ignored.
4. The public operator proof authenticated only the promoted `tenant_operator` machine key. That key correctly lacks `OUTCOME_REVIEW_MANAGE`; the proof was therefore unable to exercise the already-existing independent human review boundary.

The fourth item is a proof-identity problem, not a reason to broaden machine authority. Self-serve onboarding already creates an active human `tenant_owner`, and the tenant-scoped review queue already accepts `OUTCOME_REVIEW_MANAGE` through `POST /v1/review-queue/tasks/{task_id}/approve`.

## Implemented repair

### Composition and artifact topology

- Internal CRM persistence treats public discovery as a conditional source dependency that is satisfied by an existing CRM record/prior artifact.
- Observation and qualification remain required for internal persistence.
- Enrichment is an optional catalog dependency: it is never invented for missions that did not request it, but when selected it becomes a real upstream dependency of persistence.
- `record.write` accepts `enriched_prospects` as a bound runtime input.
- Default/fallback runtime binding carries the same enrichment artifact if explicit graph metadata is absent.

The intended Pass 3 mission therefore compiles to:

`record.search → research.observe_contacts → sales.qualify → gtm.lead_enrich → record.write`

with no `web.research` / public-discovery branch.

### Enrichment and persistence semantics

- `gtm.lead_enrich` normalizes governed `observed_contacts` into enrichment contacts.
- Explicit `real=false` / `simulated=true` evidence remains non-real.
- `record.write` merges matching enrichment by stable prospect identity.
- Only contacts explicitly marked real and not simulated may be copied from enrichment into durable CRM state.
- Transient enrichment execution context is excluded from durable business data.
- Existing qualification evidence, observed-contact lineage, idempotent CRM workflow, and read-back verification remain in force.

### Independent approval

The live proof uses two authorities belonging to the same tenant but with intentionally different privileges:

- `tenant_operator` machine API key — composes/launches the mission and reads runtime evidence;
- `tenant_owner` human session — reviews and approves a pending side-effect task.

The proof requires the machine key to receive HTTP 403 when it attempts task approval before the human owner approves the same task. No new permission or role grant is introduced.

## G.R.A.F.T. pre-run prediction

Expected directly affected implementation/proof surfaces:

- `backend/services/mission_composition/job_catalog.py`
- `backend/services/mission_composition/plan_compiler.py`
- `backend/services/tools/mission_input_binding.py`
- `backend/services/tools/gtm_actions.py`
- `backend/services/tools/sales_actions.py`
- `deploy/scripts/operator-mission-proof.py`
- live-runtime proof workflow configuration
- focused composition, binding, GTM, and sales-action tests

Expected semantic dependencies include:

- jobs: `crm.read_records`, `research.observe_sources`, `sales.qualify_prospects`, `gtm.enrich_contacts`, `crm.internal_persistence`;
- actions: `record.search`, `research.observe_contacts`, `sales.qualify`, `gtm.lead_enrich`, `record.write`;
- artifacts: CRM records/prospects, observed contacts, qualified prospects, enriched prospects, internal CRM records/read-back evidence;
- runtime/API/authorization surfaces traversed by the operator proof.

Expected relevant invariants include tenant isolation, canonical queue admission, single worker spine, side-effect approval, retry readmission, capability-not-authority, and authority-class stability.

The public operator proof is now represented in the semantic overlay as a validation consumer of API, authorization, and worker runtime. Edge direction is consumer → dependency; production runtime does not depend on the proof harness.

## Closure proof requirements

Pass 3 may be marked complete only after the exact PR head proves all of the following:

- G.R.A.F.T. build/impact/proof selection is green and actual blast radius is reconciled here;
- no unexplained unmapped implementation surface;
- composition selects exactly the local five-step internal CRM lane and no public discovery;
- real observed contact evidence reaches enrichment;
- real enrichment reaches durable CRM persistence;
- CRM mutation enters independent human review;
- machine approval is denied;
- tenant-owner approval queues the exact reviewed task with invocation-bound authorization;
- worker completes the task through normal queue/lease/runtime authority;
- durable CRM read-back verifies the persisted state;
- deliverable is customer-readable and complete;
- runtime reconciliation is aligned;
- no contradiction or first divergence is reported;
- cross-tenant runtime evidence remains inaccessible;
- retry/recovery contracts remain green;
- all required CI/security/recovery/live-runtime workflows are green.

## Pending measured evidence

The following fields are intentionally left pending until the PR runs on GitHub:

- canonical graph node/edge counts;
- affected/upstream/downstream semantic counts;
- selected proof bundles/tests;
- actual unmapped changed files;
- final runtime mission/task IDs;
- final integration/unit counts;
- final merge SHA.

They must be filled from actual CI/G.R.A.F.T. output before Pass 3 is closed.
