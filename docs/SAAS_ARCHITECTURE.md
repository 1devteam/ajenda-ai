# Ajenda AI — SaaS Structural Enforcement Architecture

This document defines the production-grade SaaS enforcement boundaries for Ajenda AI and explains how those guarantees relate to the governed runtime and its validation model.

Ajenda is not only intended to enforce tenant, policy, and operational boundaries. It is intended to prove that those boundaries hold through explicit validation and evidence collection.

---

## 1. Purpose

Ajenda AI is a multi-tenant execution platform with SaaS governance requirements that include:

- strong tenant isolation
- subscription and quota enforcement
- compliance-aware task admission
- safe runtime execution and recovery
- auditability and release confidence

The goal of the SaaS architecture is not only to describe enforcement boundaries, but to ensure those boundaries can be evaluated and trusted in production-like runtime conditions.

---

## 2. Tenant isolation boundaries

### 2.1 Database layer

**Mechanism:** PostgreSQL Row-Level Security  
**Intent:** tenant-scoped row visibility and mutation boundaries

Tenant-aware session context is required for RLS to be meaningful. If tenant context is absent, the isolation posture should fail closed.

### 2.2 API layer

**Mechanism:** tenant-envelope and auth middleware

The API layer is responsible for:

- requiring tenant context where appropriate
- rejecting malformed tenant IDs
- rejecting suspended/deleted tenants
- rejecting cross-tenant principals
- preserving explicitly public routes where public access is intentional

### 2.3 Service and repository layer

**Mechanism:** tenant-aware business logic and repository access patterns

This acts as defense in depth above the HTTP and database boundaries.

### 2.4 Queue and worker layer

**Mechanism:** tenant-aware queue partitioning / tenant-scoped payload handling and worker checks

Workers must not execute out-of-scope tenant work.

---

## 3. Subscription and plan enforcement

### 3.1 Domain model posture

Ajenda’s SaaS model includes tenant plans, tenant usage, and route-level or operation-level quota enforcement.

### 3.2 Enforcement posture

Quota and feature enforcement should reject disallowed mutation paths before work enters authoritative runtime processing.

This keeps monetization and fairness controls aligned with runtime safety.

---

## 4. Tenant lifecycle management

Lifecycle states include:

- `ACTIVE`
- `SUSPENDED`
- `DELETED`

Lifecycle state affects:

- access
- mutation legality
- operational behavior
- tenant-scoped runtime expectations

---

## 5. Compliance and governance posture

Ajenda includes a compliance-aware queue admission path.

This means:

- unsafe or review-required work does not simply enter the queue unchecked
- policy evaluation can route work into `PENDING_REVIEW`
- governance and audit evidence are part of the system truth

This is important for enterprise saleability because governance cannot be a detached afterthought. It must participate in runtime authority.

---

## 6. Runtime authority and SaaS correctness

The SaaS architecture is inseparable from runtime authority.

Ajenda’s runtime correctness depends on:

- queue admission correctness
- lease ownership correctness
- completion/failure correctness
- recovery correctness
- tenant-safe recovery and mutation behavior

A SaaS system that enforces plans but cannot prove runtime safety is not enterprise-complete.

---

## 7. Runtime proof model

Ajenda now includes a live runtime validation layer intended to validate critical guarantees across:

- control plane
- auth and tenant envelope
- execution plane
- recovery plane
- integrity plane
- observability/compliance plane

That validation layer is the mechanism by which architecture intent becomes runtime evidence.

This matters because:

- tenant isolation must be proved, not assumed
- recovery safety must be proved, not assumed
- release decisions should be based on evidence, not architecture prose alone

---

## 8. Validation linkage for SaaS guarantees

The most important SaaS guarantees should be tied to validation rows and evidence surfaces.

Examples include:

- public-vs-protected route correctness
- missing tenant rejection
- cross-tenant rejection
- tenant-scoped queue admission
- tenant-safe recovery behavior
- no unauthorized cross-tenant runtime mutation
- governance hold behavior for pending-review tasks
- audit and evidence consistency

This linkage is what turns the architecture into an operational trust model.

---

## 9. Current architecture-to-validation principle

The right operating principle for Ajenda is:

- architecture documents define intended guarantees
- implementation defines actual behavior
- validation matrix and artifacts define trusted proof of behavior

All three matter, but release confidence should come from the last two, not the first alone.

---

## 10. SaaS-grade upgrade posture

Ajenda’s longer-term SaaS/enterprise leverage still includes areas such as:

- adaptive tenant-aware rate limiting
- stronger policy-as-code control plane
- tenant-facing operational/reliability visibility
- progressive delivery with stronger release controls

Those remain valuable, but they should build on a trusted runtime-proof foundation rather than substitute for it.

---

## 11. Current architectural priority

The current highest-value architectural posture is to keep the SaaS guarantees in this document tied to current runtime-proof surfaces rather than letting the architecture drift ahead of implementation truth.

That means:

- keeping architecture docs synchronized with merged runtime and validation truth
- preserving an authoritative validation matrix and artifact model
- extending proof of resilience, isolation, integrity, and forbidden outcomes where coverage is still thinner than the importance of the guarantee
- treating recovery visibility, bounded dead-letter behavior, and targeted validation workflow coverage as current repo truth rather than future intent

The next architectural moves should build on that already-merged runtime-proof foundation, not re-describe work that has already landed.

---

## 12. Summary

Ajenda’s SaaS architecture should be understood as:

- tenant enforcement boundaries
- plan and lifecycle governance
- compliance-aware runtime admission
- queue/lease/recovery safety
- and an evidence-backed runtime-proof model that validates whether those guarantees still hold

That final layer is what moves the system toward enterprise-grade operational credibility, and the current priority is to keep the architecture narrative synchronized with the runtime and validation truth already present on `main`.

---

## 13. Self-serve onboarding (implemented)

**Routes:** `/v1/onboarding/signup`, `/verify-email`, `/resend-verification`, `/promote-bootstrap-key`

**Flow:**

1. Signup creates tenant on **free** plan via `TenantLifecycleService.provision` with `ProvisionSource.SELF_SERVE`.
2. Owner email stored in `tenant_members` with hashed verification token.
3. Verify activates member and issues **bootstrap** API key (`signup_bootstrap` role, 72h TTL).
4. Promote revokes bootstrap and issues **tenant_operator** key.

**Public ingress:** signup, verify, and resend bypass tenant header and auth middleware. Promote requires tenant context + bootstrap key.

**Abuse controls:** IP and email rate limits (`SignupAbuseGuard`), `signup_attempt_log`, idempotency on signup/verify/promote in production.

**Email:** `AJENDA_EMAIL_PROVIDER=resend` required in production; `logging` forbidden. Verification token not returned in API response in production.

**Frontend:** Customer UI ships `/verify-email` when the frontend image is deployed. Set `AJENDA_SIGNUP_VERIFY_URL_BASE` to that host (for example `http://localhost:8080/verify-email` in staging, production HTTPS URL in prod). Staging runbook: [`ops/runbooks/paid-customer-loop-staging.md`](../ops/runbooks/paid-customer-loop-staging.md).

**Account APIs:** `GET /v1/account/me`, `/plan`, `/usage`, `/billing` — require `account:read`; bootstrap keys cannot read billing (`403` before promote).

See Mermaid: [`SYSTEM_ARCHITECTURE.md` §3](./architecture/SYSTEM_ARCHITECTURE.md).

---

## 14. Stripe billing (implemented)

**Routes:**

- `POST /v1/billing/checkout` — authenticated, creates Stripe Checkout session
- `GET /v1/billing/portal` — authenticated, Customer Portal session
- `POST /v1/billing/webhook/stripe` — public, signature-verified

**Authority:**

- Webhook dedup via `stripe_webhook_events`
- Plan changes through `TenantLifecycleService.upgrade_plan`
- Lazy `stripe_customer_id` creation on first checkout

**RBAC gap:** Checkout and portal do not call `require_route_permission`; any authenticated tenant API key can invoke them.

See Mermaid: [`SYSTEM_ARCHITECTURE.md` §4](./architecture/SYSTEM_ARCHITECTURE.md).

---

## 15. Plan features and ability runtime gating

| Plan slug | `ability_runtime` | `gtm` | Typical signup/checkout |
|-----------|-------------------|-------|-------------------------|
| free | no | no | Default self-serve signup |
| starter | no | no | Checkout option in dev console |
| pro | yes | yes | Checkout option; unlocks side-effect abilities |
| enterprise | yes | yes | Custom / sales |

`QuotaEnforcementService.require_feature` returns 402 when a tenant's plan lacks the feature. External and side-effect ability-runtime actions require `ability_runtime`. `gtm.*` actions require `gtm`.

**Product mismatch:** Dev console checkout offers starter, but most advertised ability-runtime proofs need **pro**.

---

## 16. Worker tenancy model (deploy constraint)

Workers start via `deploy/scripts/start-worker.sh` with a single `AJENDA_WORKER_TENANT_ID`. Each worker process claims tasks only for that tenant.

Multi-tenant SaaS requires:

1. one worker deployment per tenant, or
2. tenant-sharded worker pools, or
3. a future tenant-scanning scheduler (not implemented).

Self-serve signups create new tenant IDs; default single-tenant worker deploy will not execute their queued work.

See Mermaid: [`SYSTEM_ARCHITECTURE.md` §5](./architecture/SYSTEM_ARCHITECTURE.md).
