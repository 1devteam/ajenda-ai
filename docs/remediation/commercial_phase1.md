# Phase 1: Commercial Viability — Stripe Billing Integration

## Status: Implemented

## What Was Delivered

### New Files
- `backend/services/billing_stripe_integration.py` — `StripeBillingService` with Stripe Customer lazy-creation, Checkout session generation, webhook event processing, and plan sync.
- `backend/api/routes/billing.py` — Three routes: `POST /v1/billing/checkout`, `GET /v1/billing/portal`, `POST /v1/billing/webhook/stripe` (public, signature-verified).
- `alembic/versions/0025_add_stripe_customer_id.py` — Migration adding `stripe_customer_id` column to `tenants`.
- `tests/unit/services/test_billing_stripe.py` — 14 unit tests covering happy paths, error paths, webhook idempotency, and quota delegation.
- `docs/remediation/commercial_phase1.md` — This document.

### Modified Files
- `backend/domain/tenant.py` — Added `stripe_customer_id: str | None` column.
- `backend/app/config.py` — Added `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_PRO` settings. Added production validation guards for `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`.
- `backend/api/router.py` — Registered `billing_router` under `/v1/billing/*`.
- `pyproject.toml` — Added `stripe>=8.0.0` dependency.
- `deploy/k8s/ingress.yaml` — Upgraded to TLS with cert-manager, nginx rate limiting, and correct port 8000.

## Architecture Decisions

**No breakage to runtime authority.** The billing layer is additive — it sits alongside the existing mission/task execution pipeline. `StripeBillingService` calls `TenantRepository.upgrade_plan()` which is the existing plan-change method. No new DB tables beyond `stripe_customer_id`.

**Tenant isolation preserved.** All billing routes use `get_tenant_db_session` + `get_request_tenant_id` per the TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY. The Stripe webhook route is public (no tenant header required) and is listed in both middleware public path prefix lists.

**Webhook idempotency.** Stripe delivers webhooks with retries. The `handle_webhook` method calls `upgrade_plan()` which is idempotent — calling it twice with the same plan is a no-op.

**Production guard.** `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are validated at startup in production mode. The app will refuse to start if they are absent or malformed.

## Next Steps (Phase 2)
- Admin route: `GET /v1/admin/tenants/{id}/billing` — view billing status per tenant.
- Usage metering: bridge `QuotaEnforcementService` counters to Stripe metered billing.
- Invoice history: `GET /v1/billing/invoices`.
- Dunning: handle `invoice.payment_failed` webhook event.
