# Ajenda AI Product Vertical Slice Build Contract

## Purpose

This document is the implementation contract for turning Ajenda AI from a backend/runtime-heavy system into a runnable product vertical slice.

The goal is not another review-note hardening pass.

The goal is:

1. Put a frontend in the repository.
2. Expose worker abilities through a clean API.
3. Let the user launch real runtime tasks from the UI.
4. Let the user see task status, output, lineage, and evidence.
5. Wire SaaS/payment UI to the existing billing backend.
6. Use the snapshot as the source of truth for what exists and what is missing.
7. Only harden after the live vertical slice exists and runs.

## Source-of-truth rule

The repository snapshot is treated as truth.

If a surface is absent from the snapshot, it is treated as missing.

If a backend service exists but has no UI path, it is treated as backend-present and product-incomplete.

If a provider is local/proof-only, it is treated as proof-capable but not production-provider-complete.

## Confirmed current state

### Repository state

Snapshot state:

- Repository: `ajenda-ai`
- Branch: `main`
- Head: `883077a`
- Origin main: `883077a`
- Working tree: clean
- Python: `3.12.3`
- Files scanned: `646`
- Static routes detected: `921`
- Python errors: `0`
- Frontend inventory: empty / absent from snapshot

### Backend routes already present

The API router mounts business routes under `/v1`.

Known mounted areas:

- `/v1/auth/*`
- `/v1/api-keys/*`
- `/v1/capabilities/*`
- `/v1/capability-adapters/*`
- `/v1/business-profile/*`
- `/v1/evidence/*`
- `/v1/outcome-reviews/*`
- `/v1/retrieval-contracts/*`
- `/v1/mission-brief/*`
- `/v1/missions/*`
- `/v1/tasks/*`
- `/v1/workforce/*`
- `/v1/branches/*`
- `/v1/runtime/*`
- `/v1/operations/*`
- `/v1/system/*`
- `/v1/observability/*`
- `/v1/webhooks/*`
- `/v1/billing/*`
- `/v1/admin/*`

### Runtime proof already passed locally

The runtime proof demonstrated:

- Docker Compose stack starts.
- Database is reachable.
- Redis is reachable.
- API readiness passes.
- Worker starts.
- Worker receives Redis queue config.
- Worker claims a task.
- Worker completes a task.
- Lease is released.
- Audit is written.
- Lineage is written.
- Metrics endpoint works.
- Prometheus scrape target health works.
- Redis lease cleanup is checked.

This proves runtime plumbing.

It does not prove product completeness.

## Missing product surfaces

### Missing frontend

The snapshot has no frontend app.

Required frontend path:

```text
frontend/
  package.json
  index.html
  vite.config.ts
  tsconfig.json
  src/
    main.tsx
    App.tsx
    api/client.ts
    types.ts
    styles.css
