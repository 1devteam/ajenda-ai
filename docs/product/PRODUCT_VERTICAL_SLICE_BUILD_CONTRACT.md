# Ajenda AI Product Vertical Slice Build Contract

**Last verified:** 2026-06-21 (`main` @ `6a14e40`)  
**Architecture map:** [`docs/architecture/SYSTEM_ARCHITECTURE.md`](../architecture/SYSTEM_ARCHITECTURE.md)

## Purpose

This document tracks the product vertical slice: what exists in code vs what a paying stranger still needs.

## Source-of-truth rule

Implementation + tests win over this document. When in doubt, read `frontend/src/`, `backend/api/routes/`, and `SYSTEM_ARCHITECTURE.md`.

---

## Confirmed current state

### Repository

- Branch: `main`
- Alembic head: `0030_signup_abuse_tables`
- Frontend: **present** — Runtime Ability Console (dev tool, not customer product)

### Backend routes on `/v1`

All areas in `backend/api/router.py`, including:

- `/v1/onboarding/*` — self-serve signup, verify, resend, promote
- `/v1/billing/*` — checkout, portal, Stripe webhook
- `/v1/ability-runtime/*` — product-facing task launcher
- `/v1/auth/*`, `/v1/api-keys/*`, missions, tasks, workforce, admin, …

### Frontend (`frontend/`)

| Exists | Missing |
|--------|---------|
| React 19 + Vite app | Customer signup/dashboard |
| Manual tenant + API key config | react-router, auth session |
| Ability-runtime proof launchers | Onboarding API calls |
| Billing checkout/portal buttons | Verify-email page |
| Task status monitor | Deploy in prod manifests |

### Runtime proof

Live runtime proof validates queue-backed worker execution, leases, audit, lineage, metrics. It does **not** prove stranger-ready paid customer loop.

---

## Vertical slice checklist

| # | Requirement | Status |
|---|-------------|--------|
| 1 | Frontend in repository | **Done** — dev console only |
| 2 | Worker abilities via clean API | **Done** — `/v1/ability-runtime/*` |
| 3 | Launch runtime tasks from UI | **Done** — dev console (requires pre-configured API key) |
| 4 | Task status, lineage, evidence in UI | **Done** — dev console task monitor |
| 5 | SaaS/payment UI wired to billing backend | **Partial** — checkout/portal buttons; no post-payment UX |
| 6 | Self-serve signup without manual keys | **Not done** — API only |
| 7 | Verify-email landing page | **Not done** |
| 8 | Account/plan/usage self-service APIs | **Not done** |
| 9 | E2E paid-customer integration test | **Not done** |
| 10 | Multi-tenant worker execution | **Not done** — single `AJENDA_WORKER_TENANT_ID` |

---

## Remaining product work

1. Customer frontend replacing dev-console auth model
2. Verify page at `AJENDA_SIGNUP_VERIFY_URL_BASE`
3. `/v1/account/*` APIs (me, plan, quota, billing)
4. Guided onboarding UX (signup → verify → promote → checkout → first task)
5. Plan alignment (starter vs pro vs `ability_runtime` gates)
6. Multi-tenant worker strategy
7. Frontend static hosting in deploy
8. `test_paid_customer_loop` integration test

---

## Required frontend structure (target customer product)

Current `frontend/` satisfies the **dev console** slice. Customer product will extend or replace it with:

```text
frontend/
  package.json
  index.html
  vite.config.ts
  tsconfig.json
  src/
    main.tsx
    App.tsx              # routing: /signup, /verify-email, /dashboard, /billing
    api/client.ts        # onboarding + account + ability-runtime + billing
    pages/               # customer flows (not yet present)
    types.ts
    styles.css
```

See Mermaid target-vs-today diagram: `SYSTEM_ARCHITECTURE.md` §6.