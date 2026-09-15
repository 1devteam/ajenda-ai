# Ajenda core independence and enterprise completion plan

**Status:** proposed plan. Not implementation evidence. Not a merge. Not a GRAFT overlay.  
**Authority:** implementation, tests, migrations, and runtime proof remain the source of truth.  
**SHA of record:** `6f8111306695a765d89ec1d4fdb8a1fbe25780df` (`main`, 2026-09-15).  
**Historical scan:** `e246c19` on `feat/internal-crm-composition-depth` is not HEAD. That branch's CRM work is already on `main` through PRs #520–#530.  
**Merge authorization:** not-determined until each slice PR is reviewed and proven.  
**implementsPlan:** this document. Code PRs that follow it must cite the slice number.

## What this plan is for

Take Ajenda from a governed platform that still boots and sells through HubSpot, GTM, and vertical packs, to an enterprise-grade kernel that:

- runs with no HubSpot, Salesforce, or other external CRM
- runs with no GTM feature flag
- runs with no vertical pack
- keeps Ajenda Records (`tenant_internal_records` / `/v1/crm`) as first-class product state
- keeps missions, queue, lease, worker, policy, evidence, and tenant RLS as the only runtime
- treats HubSpot, Gmail, Salesforce, LinkedIn, Calendar, GitHub as optional adapters attached by credential
- then completes production cutover (email, Stripe, CORS, honest docs)

Ajenda Records are not “another CRM product.” They are Ajenda’s own durable business state. External CRMs are adapters. GTM and verticals are later packs.

## What is already true at `6f81113`

Determined from the tree, not from product copy:

- FastAPI `/v1`, PostgreSQL with RLS, Redis queue, WorkerLoop, TaskDispatcher, evidence, outcome reviews, OIDC, tenants, billing routes, frontend SPA.
- Internal records exist: migration `0033`, `backend/services/light_crm/*`, `/v1/crm`, frontend records UI.
- Internal CRM composition work has landed: `crm.observe`, `crm.reconcile`, `crm.verify_effect`, `crm.mutate`, `record.write`, reviews routed through local records (#529), negation routing (#530).
- Composition versions at this SHA: `COMPOSITION_SCHEMA_VERSION = 7`, `JOB_CATALOG_VERSION = "11"`, `INTERPRETER_VERSION = "14"`, `CAPABILITY_RESOLVER_VERSION = "10"`.
- `StandardCrmClient` already writes internal records when no credential is present, and only then.
- ADR-0009: missing external credentials fail closed. Production ignores simulation opt-in.
- ADR-0010 (proposed): verticals are operating domains, not providers. Existing `vertical.*` code is transitional.

## What is broken relative to independence

These are code facts, not guesses.

1. **HubSpot is on the boot path.** Root `docker-compose.yml` and `deploy/compose/docker-compose.prod.yml` make `worker` (and in prod, `api`) `depends_on: hubspot-crm-ingress`. Default `AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST` is `hubspot-crm-ingress`. README first local step is generate HubSpot TLS certs. `live-runtime-proof.sh` starts HubSpot ingress. Tenant lifecycle can auto-provision `hubspot-crm` when platform master key mode is on. Config default `hubspot_platform_master_auto_provision=True`.

2. **GTM is in the kernel by name.** Internal upsert is still invoked as `gtm.crm_upsert`. `ability_runtime.py` and `vertical_ops.py` call `quota.require_feature(tenant_id, "gtm")` for any `gtm.*` action. Migration `0026` seeds `gtm` only on pro/enterprise. Free/starter tenants therefore cannot use the GTM-named write even when the write is internal records.

3. **Verticals are a default surface.** `/v1/vertical-ops` is included in the API router. Ability catalog and role pack ship `vertical.research`, `vertical.email`, `vertical.social`, `vertical.orchestrator`. Mission composition still knows `vertical.*` jobs. `crm_actions.py` imports reconciliation types from `backend.services.vertical_ops`.

4. **Docs are behind HEAD.** `docs/architecture/SYSTEM_ARCHITECTURE.md` still says alembic head `0038` and last verified an August SHA. Tree head is `0045_stripe_revenue_payload`. `docs/README.md` last aligned 2026-07-07. `docs/planning/GRAFT1ST_UNIVERSAL_CRM_CANONICAL_MAP.md` still describes GTM and vertical abilities as the workers that consume CRM. That framing is residual and is superseded by this plan.

## What the older scan inferred, and what to do with it

The `e246c19` scan inferred “finish internal CRM composition against the version contract.” That implementation is on `main`. What remains is proof that it holds with no HubSpot, no GTM feature, no vertical pack, and with tenant RLS + lease + review on mutate.

Other issues from that scan, classified:

**Do after the kernel is independent (real, not next)**

- Stripe price IDs in the local scan are placeholders. Billing routes and webhook tables exist. Production checkout is not complete.
- Budget policy exists with `ENABLED=false`, `OBSERVE_ONLY=true`, `ENFORCE=false`. Keep enforce off until Slice 4. Enforcement is a product decision, not a cleanup.
- Knowledge ledger and retrieval exist as schema and services. This tree does not prove missions consume them as the default path. Leave until Records + missions work with no adapter.
- `artifacts/wave-a` is leftover install/patch scripts. Delete after the kernel is honest.

**Still unproven — must be answered in Slice 1, not assumed**

- Does a mission with `internal_crm_source` compile and persist through `record.write` / `crm.mutate` with no HubSpot container and no `gtm` feature?
- Does every CRM mutate/review path activate tenant RLS via `get_tenant_db_session`?
- Does `crm.mutate` require lease, policy, and review the same as other side effects?
- Do composition version fields on a fresh proposal match schema 7 / catalog 11 / interpreter 14 / resolver 10?

**Ignore — scanner noise**

- Seventy-four missing `__init__` files: mostly tests, docs, alembic.
- Ninety-one “duplicates”: mostly validation artifact copies. Same filename in `routes/` vs `domain/` is layering, not copy-paste.
- `routes_static: 2903` is a scanner count, not 2903 product endpoints.

## Non-goals

- Do not add a new runtime, queue, or planner.
- Do not make HubSpot, Salesforce, or any vendor CRM the system of record.
- Do not hybrid-fallback a credentialed CRM write into Ajenda Records and call it external success.
- Do not enforce budget policy in this program.
- Do not “fix” missing `__init__` files or scanner duplicate counts as work.
- Do not expand GTM, HubSpot, or vertical templates until Slice 2 is done.
- Do not treat this plan as proof that any slice is complete.

## Target kernel

A tenant can, with Compose services `db`, `redis`, `migrate`, `api`, `worker`, `frontend` only:

1. Sign up / authenticate.
2. Create a mission from business profile + charter + composition contracts.
3. Admit work through ExecutionTask + queue + lease.
4. Observe, reconcile, verify, and mutate Ajenda Records.
5. Review drafts against local records.
6. Read evidence, lineage, and record readback.

No HubSpot process. No `gtm` plan feature. No vertical pack. Adapters attach later with a tenant credential and fail closed without one.

---

## Slice 0 — Boot without HubSpot

**Responsibility:** default local and prod-like Compose must start Ajenda without the HubSpot adapter or ingress. HubSpot remains in the tree as an optional overlay.

**Source of truth:** `docker-compose.yml`, `deploy/compose/docker-compose.prod.yml`, `backend/app/config.py`, `backend/services/tenant_lifecycle.py`, `README.md` HubSpot section, `deploy/scripts/live-runtime-proof.sh`.

**Change**

- Remove `depends_on: hubspot-crm-ingress` from `api` and `worker` in root and prod compose.
- Keep `hubspot-crm-adapter` and `hubspot-crm-ingress` services in compose files but do not start them by default. Document an overlay or profile (`compose --profile hubspot`) if profiles are used; otherwise they are started only when explicitly named.
- Default `AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST` to empty. Adapter host is required only when a HubSpot credential is registered.
- Default `AJENDA_HUBSPOT_PLATFORM_MASTER_AUTO_PROVISION` to false. Auto-provision of `hubspot-crm` on tenant create is operator-opt-in, never default.
- README: first run is `docker compose up -d db redis migrate api worker frontend`. HubSpot certs and adapter are a later “optional adapter” section.
- `live-runtime-proof.sh` must pass with HubSpot services omitted. HubSpot lanes stay behind `AJENDA_E2E_HUBSPOT_PAK` / explicit profile.
- K8s: adapter deployment remains, but api/worker must not require it to become ready.

**Invariants**

- Worker can claim and run an internal task with HubSpot containers stopped.
- Settings load with no HubSpot env set.
- Registering a HubSpot credential without a host still fails closed.
- No secret, PAK, or platform master key is required to boot.

**Proof**

- Compose config renders without HubSpot as a required dependency.
- Unit: settings default host empty; auto-provision skipped when flag false (`tests/unit/services/test_tenant_lifecycle_platform_hubspot.py` and config tests).
- Local: `docker compose up -d db redis migrate api worker frontend` then `/health` and `/readiness` 200. Process list does not include hubspot-crm-*.
- Existing HubSpot live tests remain, marked `live` / skip without token.

**Pitfalls**

- Proof scripts that assume ingress TLS certs on first run.
- Network egress still pinning `hubspot-crm-ingress` as a default trusted host.
- Frontend Connections page implying HubSpot is required to use Records.
- Prod compose `api.depends_on` still listing ingress after worker is fixed.

**Exit:** a clean clone, Python 3.12, Docker, `.env` from `.env.example` with `POSTGRES_PASSWORD`, no HubSpot env, stack healthy.

---

## Slice 1 — Prove internal CRM composition on Ajenda Records only

**Responsibility:** the landed CRM composition path works as the default product loop with no adapter, no GTM feature, no vertical pack.

**Source of truth:** `backend/services/light_crm/*`, `backend/api/routes/light_crm.py`, `backend/api/routes/review_queue.py`, `backend/services/tools/crm_actions.py`, `backend/services/tools/sales_actions.py`, `backend/services/plugins/crm_client.py`, `backend/services/mission_composition/action_inputs.py`, `capability_resolver.py`, `plan_compiler.py`, `contracts.py`, tests under `tests/unit/services/test_light_crm.py`, `tests/unit/api/test_light_crm_routes.py`, `tests/unit/api/test_review_queue_routes.py`, `tests/unit/tools/test_crm_actions.py`.

**Change**

- Add a Slice 1 proof that does not set HubSpot env, does not enable `gtm`, does not call `/v1/vertical-ops`.
- Trace and fix any path that still requires `gtm.crm_upsert` or HubSpot host for internal persistence. Internal writes must go through `complete_internal_crm_upsert` / `crm.mutate` / `record.write` without the GTM feature gate.
- Confirm `internal_crm_source` in intent context selects `crm.read_records` / `record.write` and does not select HubSpot `credential_id`.
- Confirm review-queue approve/reject calls `on_draft_approved` against local records, including negation routing from #530.
- Confirm every CRM HTTP route uses `get_tenant_db_session` (RLS), not `get_db_session`.
- Confirm `crm.mutate` remains a side-effecting action: capability/adapter authority, review when required, evidence + readback. Task completion alone is not CRM completion.
- Do not implement duplicate merge in this slice.

**Invariants**

- No credential → internal records only. Source `ajenda_brain` or equivalent internal marker. `real=true` only for an actual internal write, never for a simulated vendor write.
- Credential present for external CRM → adapter only. Write failure does not fall back to internal records.
- Tenant A cannot read or mutate tenant B records.
- Retry does not duplicate contacts, opportunities, or activities (existing idempotent workflow).
- Execution status and deliverable acceptance stay separate (`completed` vs `partially_met`).
- Composition proposal records schema 7 / catalog 11 / interpreter 14 / resolver 10 unless a version bump is in the same PR.

**Proof**

- Targeted unit tests for observe / reconcile / verify / mutate / upsert / review hooks with no HubSpot monkeypatch beyond “credential absent.”
- Contract test: free-plan tenant (no `gtm`, no `ability_runtime` if that remains a separate gate) can list and upsert records via `/v1/crm` and can run `crm.observe` as an internal read. If `ability_runtime` still gates all tool.invoke, either document that as a Slice 2 dependency or allow internal CRM reads/writes under a core feature, not `gtm`.
- Integration (Docker/testcontainers, not HubSpot): compose a mission with `internal_crm_source`, persist three contacts + accounts + opportunities + activities, read back, approve a review, negate a review, confirm local records match.
- Explicit negative test: HubSpot containers down, no `AJENDA_E2E_HUBSPOT_PAK`, proof still green.

**Pitfalls**

- `gtm.crm_upsert` name causing 402 on free tenants during internal write.
- `sales.research` hybrid fallback masking a missing adapter as success.
- Review hook writing through a path that still names HubSpot.
- Using `get_db_session` on a new CRM route and silently skipping RLS.
- Treating unit mocks of `complete_internal_crm_upsert` as runtime proof.

**Exit:** written proof in the PR that names commands, SHA, and “HubSpot not running.”

---

## Slice 2 — GTM and vertical out of the kernel

**Responsibility:** GTM and vertical become optional packs. The kernel’s action names, plan features, and default catalog do not require them.

**Source of truth:** `backend/api/routes/ability_runtime.py`, `backend/api/routes/vertical_ops.py`, `backend/api/router.py`, `backend/services/abilities/catalog.py`, `backend/services/abilities/vertical_role_catalog.py`, `backend/services/quota_enforcement.py`, alembic `0006` / `0026` / `0043`, `backend/services/tools/crm_actions.py` import of `vertical_ops`.

**Change**

- Core record actions: `crm.observe`, `crm.reconcile`, `crm.verify_effect`, `crm.mutate`, `record.write`, and a core upsert name that is not `gtm.crm_upsert`. Keep `gtm.crm_upsert` as a deprecated alias that only runs when the GTM pack is enabled and, if credentialed, talks to an adapter.
- `require_feature("gtm")` only for remaining `gtm.email_*`, `gtm.lead_enrich`, `gtm.social_*`, and the deprecated alias. Never for Ajenda Records or generic missions.
- Internal CRM side effects use `ability_runtime` only if that feature is the general paid execution gate. Prefer: internal record writes available on free; external/side-effecting adapter writes remain paid. Decide in the PR, do not leave both gates on the same internal write.
- Move vertical template launch off the default customer path. `/v1/vertical-ops` may remain for pack users; default mission composition must compile without `vertical.*` roles.
- Relocate CRM reconciliation types out of `backend/services/vertical_ops` into a records/reconciliation module so `crm_actions.py` does not import vertical_ops.
- Do not delete HubSpot adapter code. Do not delete GTM handlers. Pack them.

**Invariants**

- Free tenant, no GTM, no vertical: signup → mission → internal record write → evidence.
- Enabling GTM does not change Ajenda Record identity or lifecycle authority.
- A vertical pack cannot grant execution authority (already true for the role catalog; keep it).
- CapabilityAdapter records remain declarative.

**Proof**

- Quota tests: tenant without `gtm` in `features_enabled` can upsert a contact and run `crm.observe`; `gtm.email_send` still 402.
- Composition test: intent without vertical vocabulary produces a graph that still contains `record.write` / CRM jobs when the ask is to persist prospects.
- Router test: kernel boots if vertical_ops router is not included; or a flag documents it as pack-only. Prefer pack-only default in customer compose.
- No HubSpot, no GTM env in this proof.

**Pitfalls**

- Breaking existing missions that already stored `gtm.crm_upsert` in task metadata. Provide alias + compatibility read.
- Seed data and brain catalog still listing GTM as required for RevOps.
- Frontend action options still labeling internal mutate as GTM.
- ADR-0007 / ADR-0010 left claiming verticals are the operating model.

**Exit:** default product loop never mentions HubSpot, GTM, or vertical in logs, task action names, or required features.

---

## Slice 3 — Honest maps

**Responsibility:** docs match `6f81113+` after Slices 0–2, not August 2026.

**Change**

- `docs/architecture/SYSTEM_ARCHITECTURE.md`: alembic head `0045` (or whatever HEAD is at the rewrite). Default system inventory: api, worker, frontend, migrate, db, redis. HubSpot ingress is an optional overlay. `/v1/crm` described as Ajenda Records. GTM and vertical listed as packs.
- `docs/architecture/INTERNAL_CRM_COMPLETION_MAP.md`: remaining P1 is reviewed duplicate merge; HubSpot is not a completion item.
- `docs/planning/GRAFT1ST_UNIVERSAL_CRM_CANONICAL_MAP.md`: mark superseded for “GTM/vertical as the workers that consume CRM.” Missions consume Records. Packs may too.
- `docs/README.md`: date + pointer to this plan until Slices 0–2 are merged, then pointer to the rewritten architecture map.
- README HubSpot section stays optional-plugin only.
- Production env contract: HubSpot variables optional. Empty adapter host legal.

**Invariants**

- Docs do not claim behavior tests do not prove.
- No mermaid in this plan. Architecture rewrite may keep mermaid if the rest of the docs set uses it; it must not show HubSpot on the default path.

**Proof**

- Doc PR cites the code SHA. A reviewer can grep `hubspot-crm-ingress` in compose `depends_on` and find none on api/worker.
- `docs/README.md` aligned date matches the merge day.

**Exit:** a stranger can read SYSTEM_ARCHITECTURE and start Compose without a HubSpot key.

---

## Slice 4 — Enterprise cutover without HubSpot

**Responsibility:** production-shaped deployment of the kernel. Adapters optional.

**Source of truth:** `docs/deployment/production-env-contract.md`, `docs/deployment/STAGING_PROOF.md`, `ops/runbooks/paid-customer-loop-staging.md`, `backend/services/billing_stripe_integration.py`, onboarding/Resend settings.

**Change**

- Production email: Resend (or equivalent), `AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN=false`, real `AJENDA_SIGNUP_VERIFY_URL_BASE`.
- Live Stripe: real price IDs, webhook endpoint, no `price_starter_placeholder`. Customer checkout remains Pro-for-ability_runtime unless Slice 2 changed the SKU map. Document the SKU map from code, not from hope.
- CORS and OIDC redirect allowlists for the real origin.
- Default k8s/compose inventory still excludes HubSpot. Adapter overlay is a separate manifest.
- `AJENDA_HUBSPOT_PLATFORM_MASTER_KEY_ENABLED` remains false in production examples.
- Budget policy: leave `ENFORCE=false`. Do not turn it on in this slice. Record the decision in the PR.
- Knowledge ledger: no new consumption work in this slice.

**Invariants**

- Paid customer loop (signup → verify → promote → account → optional checkout) does not start HubSpot.
- Stripe webhook signature failure fails closed and does not upgrade a plan.
- No platform-master HubSpot key in prod examples.

**Proof**

- `paid-customer-loop-staging-proof.sh` green with HubSpot profile off.
- `tests/integration/saas/test_paid_customer_loop_real.py` and Stripe webhook tests green.
- Manual: empty `AJENDA_HUBSPOT_*`, stack still serves `/` and `/v1/health`.

**Pitfalls**

- Staging scripts that `up -d hubspot-crm-adapter` unconditionally.
- Checkout still targeting starter, which does not include `ability_runtime`.
- OIDC login confused with Google connector OAuth (README already separates them; keep it).

**Exit:** a production-like host runs Ajenda as a governed execution product. Connecting HubSpot is a customer choice.

---

## Slice 5 — Records depth and later work

Only after 0–4.

**5a. Reviewed duplicate merge (named P1).** Preserve lineage, relationships, rollback evidence. Tenant-scoped. Retry-safe. Tests for merge, reject, and rollback.

**5b. Indexed fields** only from measured query needs. JSONB remains valid until a query is slow and named.

**5c. Knowledge consumption** only if a mission actually needs retrieval. Do not wire it because the tables exist.

**5d. Delete `artifacts/wave-a`** once no install path references those scripts.

**5e. Optional adapter overlays** (HubSpot, Salesforce, Gmail, LinkedIn, Calendar, GitHub) each with: credential, pinned egress, fail-closed, evidence, live test skipped without secret. None of these may return to `depends_on` for api/worker.

---

## Localhost troubleshooting (operator)

This planning environment could not boot Compose (no Docker, Python 3.10 vs required 3.12). Proof of Slice 0 and Slice 1 must run on the WSL tree that produced the snapshot (`/home/inmoa/projects/ajenda-ai`, Python 3.12.3).

After Slice 0 merges:

```bash
cp .env.example .env
# set POSTGRES_PASSWORD; leave all AJENDA_HUBSPOT_* unset
docker compose up -d db redis migrate api worker frontend
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/readiness
docker compose ps   # hubspot-crm-* must be absent
```

If health fails, the slice is not done. Do not start HubSpot to make it pass.

Slice 1 proof is a mission + `/v1/crm` write on that same stack, then feed the GRAFT/snapshot artifact to an AI only as facts, not as a plan.

## Required gates per implementation PR

From `AGENTS.md`. Narrowest tests first, then:

```bash
ruff check backend/ tests/ scripts/validation/
ruff format --check backend/ tests/ scripts/validation/
mypy backend/
python scripts/validation/contract_drift_check.py
python scripts/validation/runtime_authority_inventory_check.py
python scripts/validation/migration_seed_contract_check.py
python scripts/validation/ability_rollout_contract_check.py
python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration"
```

Slice 0–1 that touch runtime, queue, lease, or CRM also run the relevant integration tests. Slice 4 runs the paid-customer and staging proof scripts. HubSpot live tests are never the green-bar for kernel PRs.

## PR shape

One slice per PR. Title prefix `fix(core): slice-N ...`. Body must include: files, path traced, UPG/LAP for layer changes, tenant/side-effect/evidence impact, commands run, skipped checks with reason, follow-ups as issues not assumptions.

Do not combine Slice 2 (GTM/vertical rename) with Slice 4 (Stripe/Resend). Do not put duplicate-merge into Slice 1.

## Order lock

0 → 1 → 2 → 3 → 4 → 5.

Do not start 2 until 1’s proof named HubSpot-not-running. Do not start 4 until 2’s free tenant can persist records. Do not start 5 until 4’s paid loop is green without HubSpot.

## Disposition

This file is reconstructed intent for the independence program. It is not a plan executed, not a merge, and not ranked work in the GRAFT sense. Propose implementation PRs from these facts. Honor negatives. Leave unproven overlay questions open until Slice 1 answers them. Do not treat acknowledgements as repairs.
