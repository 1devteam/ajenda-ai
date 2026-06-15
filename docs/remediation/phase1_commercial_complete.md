# Remediation Phase 1 Complete — Commercial Viability

## Summary

Stripe billing integration delivered as Phase 1 of the commercial viability remediation.

## Delivered

- `backend/services/billing_stripe_integration.py` — Production-grade Stripe service with lazy SDK init, idempotent webhook handling, and tenant-scoped checkout/portal.
- `backend/api/routes/billing.py` — Billing routes integrated with tenant isolation policy (`get_request_tenant_id` + `get_tenant_db_session`). Endpoints: `POST /billing/checkout`, `GET /billing/portal`, `POST /billing/webhook/stripe`.
- `backend/domain/tenant.py` — `stripe_customer_id` column added.
- `alembic/versions/0025_add_stripe_customer_id.py` — Migration for `stripe_customer_id`.
- `backend/repositories/tenant_repository.py` — `upgrade_plan()` method added for billing-aware plan transitions.
- `backend/app/config.py` — Stripe settings fields + production validation guards.
- `deploy/k8s/ingress.yaml` — TLS ingress template.
- `deploy/k8s/ingress-tls.yaml` — Production TLS ingress with `api.ajenda.ai` hostname and `force-ssl-redirect`.
- `.env.example` — Stripe env vars documented including `STRIPE_PRICE_ENTERPRISE`.
- `tests/unit/services/test_billing_stripe.py` — 15 unit tests covering all billing paths.

## Invariants Maintained

- Tenant isolation policy enforced on all billing routes.
- No cross-tenant operations anywhere in the billing layer.
- Runtime authority (queue, worker, lease) unaffected.
- All existing 1,284 tests continue to pass.

## Next

Phase 2 — Observability and alerting hardening.
