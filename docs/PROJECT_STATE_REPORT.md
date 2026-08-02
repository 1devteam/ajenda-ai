# Ajenda AI — Project State Report

**Date:** July 31, 2026
**Branch:** `main`  
**Alembic head:** `0035_composition_proposals`
**Architecture map:** [`docs/architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md)

This report reflects implementation-backed truth on `main`. For visual flows, see the Mermaid diagrams in `SYSTEM_ARCHITECTURE.md`.

---

## 1. Executive summary

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Backend platform | Strong | Runtime, isolation, queue/lease, recovery, governance |
| SaaS APIs | Strong | Onboarding, account self-service, Stripe billing with RBAC |
| Customer product | Staging-ready | Frontend + verify page + E2E proof on Compose |
| Deploy | Compose + K8s | API, worker, **frontend**, HubSpot ingress (optional); GHCR images |
| Live runtime proof | Green on `main` CI | Compose proof on every `main` push; HubSpot cert auto-generation |
| Production launch | Ready to configure | Startup guards + hostname contract; operator replaces `ajenda.example.com` and live secrets |

**Overall launch readiness for strangers:** staging-proofable locally; production cutover checklist in [`ops/runbooks/paid-customer-loop-staging.md`](../ops/runbooks/paid-customer-loop-staging.md) §5.

---

## 2. What is implemented

### 2.1 Runtime and execution

- Queue-backed `ExecutionCoordinator` with Redis adapter
- `WorkerLoop` + `TaskDispatcher` with lease ownership
- Bounded recovery, dead-letter, operations surfaces
- Ability runtime API (`/v1/ability-runtime/*`) with plan feature gates
- GTM actions behind `gtm` feature (pro/enterprise)
- Multi-tenant workers (`AJENDA_WORKER_TENANT_MODE=multi`, ADR-0004)
- Live runtime proof on `main`: echo task, `gtm.lead_enrich`, brain capstone slice

### 2.2 Tenant isolation and auth

- `TenantContextMiddleware` + `AuthContextMiddleware`
- PostgreSQL RLS with tenant session activation
- OIDC/JWT and API-key auth; cross-tenant rejection
- Customer auth sessions + OIDC login intents (migration `0032`)
- Public routes: health/readiness probes, Stripe webhook, onboarding signup/verify/resend; recovery (`POST /v1/operations/recovery`) requires tenant auth + `RUNTIME_OPERATE`

### 2.3 SaaS and commercial

- Tenant lifecycle (provision, suspend, upgrade_plan)
- Quota and feature enforcement (`QuotaEnforcementService`)
- Self-serve onboarding: signup → verify → bootstrap key → promote
- Account APIs: `/v1/account/me`, `/plan`, `/usage`, `/billing`
- Provider credentials: `/v1/account/provider-credentials` (+ OAuth flows per provider; Google Contacts/Calendar/Gmail separate from identity OIDC)
- Mission composition: structured interpreter + restatement; durable proposals (`0035_composition_proposals`)
- Governed vertical operations: Phase B templates can materialize and queue through `ExecutionCoordinator`; Phase C templates are plan-only and fail closed on queue requests
- Billing RBAC: checkout/portal require `billing:manage`; account reads use `account:read`
- Stripe: checkout, portal, webhook with `stripe_webhook_events` dedup
- Plans: free, starter, pro, enterprise (`0006` seed; `0026` ability_runtime on pro+)

### 2.4 Ajenda central brain + optional plugins

- Standalone mode: `tenant_internal_records` (migration `0033`) for internal CRM/contact storage
- Plugin discovery: `GET /v1/plugins`
- HubSpot CRM optional plugin with TLS ingress in Compose/K8s prod stack
- Gmail/SMTP email plugins; credential resolver + fail-closed simulated paths when creds absent

### 2.5 Customer frontend

- React 19 + Vite + `react-router` 8.3.0 (client-only SPA)
- Routes: `/signup`, `/signin`, `/verify-email`, `/promote`, `/dashboard`, `/missions`, `/billing`, `/tasks`, `/connections` (`/credentials`), `/dev`
- Session storage for bootstrap vs operational API keys
- Compose: customer UI on **:8080** (nginx proxies `/v1` to API)
- K8s: `ajenda-frontend` deployment + ingress paths; image `ghcr.io/<org>/<repo>-frontend:<version>`

### 2.6 Data model (recent)

- `tenant_members` — owner email, verification state
- `api_key_records` — purpose, expires_at, roles_json (bootstrap support)
- `signup_attempt_log` — abuse tracking
- `stripe_customer_id` on tenants
- `mission_plans` — canonical plan storage; `0031` backfill from legacy metadata
- `customer_auth_sessions`, OIDC login intents — migration `0032`
- `tenant_internal_records` — migration `0033`
- `email_send_idempotency_receipts` — migration `0034`
- `mission_composition_proposals` — migration `0035` (declarative history only)

### 2.7 Tests and proof

- ~1600+ non-integration tests passing
- SaaS integration: onboarding, Stripe webhook, lifecycle, tenant members
- **Paid customer E2E:** `tests/integration/saas/test_paid_customer_loop_real.py`
- Staging HTTP proof: `deploy/scripts/paid-customer-loop-staging-proof.sh`
- **CI Live Runtime Proof:** `.github/workflows/ci.yml` on `main` push (run #1041 @ `efe332b` passed)

---

## 3. What is not implemented / remaining gaps

| Gap | Impact |
|-----|--------|
| Operator replaces placeholder domain | `ajenda.example.com` in manifests must become the real production host |
| Live secrets in K8s/Compose prod | Resend + Stripe live keys are template placeholders until deploy |
| Stranger-ready on prod hostnames | Staging proof uses localhost + exposed verification token |
| Plugin lane in default CI | Live HubSpot/Gmail/Salesforce proof requires opt-in env + tokens |

---

## 4. Deployment surfaces

| Target | Present in repo | Notes |
|--------|-----------------|-------|
| Docker Compose prod | yes | api, worker, **frontend**, db, redis, migrate, prometheus, otel, hubspot ingress |
| Kubernetes | yes | api, worker, **frontend**, ingress (`/v1` → API, `/` → frontend) |
| GHCR release CI | yes | api, worker, migrate, **frontend** images on merge to `main` |
| Terraform/AWS (`infra/`) | yes | VPC, RDS, Redis, ECS + **frontend** ALB path routing |

Production env contract: `docs/deployment/production-env-contract.md`  
Compose templates: `deploy/compose/.env.prod.example`, `deploy/compose/.env.staging.example`

---

## 5. Prioritized next work

1. Replace `ajenda.example.com` with production domain (ingress, ConfigMap, `.env.prod`)
2. Populate live Resend + Stripe secrets; register Stripe webhook on the public API path
3. Run paid-customer staging proof against production-like hostnames before launch

---

## 6. Documentation canonical set

| Doc | Role |
|-----|------|
| `docs/architecture/SYSTEM_ARCHITECTURE.md` | Code-aligned Mermaid architecture |
| `PROJECT_SPEC.md` | Canonical specification |
| `README.md` | Repository entry point |
| `docs/SAAS_ARCHITECTURE.md` | SaaS enforcement detail |
| `docs/validation/live-runtime-proof-release-gate.md` | Live proof + CI release gate |
| `ops/runbooks/paid-customer-loop-staging.md` | Staging customer-loop runbook |
| `docs/deployment/STAGING_PROOF.md` | Runtime + customer-loop staging proof |
| `docs/deployment/production-env-contract.md` | Required production variables |
