# Ajenda AI — v1.1.0

Enterprise-grade AI agent orchestration platform. Multi-tenant, compliance-aware, production-hardened.

## What's in this repository

| Layer | Components |
|-------|-----------|
| **Runtime** | `ExecutionCoordinator`, `RuntimeGovernor`, `RuntimeMaintainer`, `WorkerRuntimeService` |
| **Compliance** | `PolicyGuardian` — EU AI Act, Colorado SB24-205, NYC LL144, FTC CAN-SPAM enforcement |
| **Queue** | Redis adapter with atomic lease recovery; local adapter for development |
| **Webhooks** | Tenant-scoped outbound webhooks with Fernet-encrypted secrets and HMAC-SHA256 delivery signing |
| **SaaS** | Multi-tenant lifecycle (create, suspend, delete), quota enforcement, feature gating |
| **Observability** | Prometheus metrics at `/v1/observability/metrics`, governance event audit trail |
| **Auth** | OIDC JWT + API key authentication, fail-closed middleware |
| **Isolation** | Row-Level Security via `SET LOCAL app.current_tenant_id`, per-route rate limiting |
| **IaC** | Terraform modules for ECS, RDS, ElastiCache, Secrets Manager, VPC |
| **K8s** | Deployment manifests, ServiceMonitor, migration Job |

## Architecture decisions

- **Middleware order**: Tenant context runs before Auth so API key lookups are scoped to the correct tenant.
- **Lease recovery**: `release_lease()` atomically returns the payload to the pending queue before deleting the lease key, preventing silent task stranding.
- **Retry tracking**: `ExecutionTask.retry_count` is a typed DB column (migration 0008), incremented by `RuntimeMaintainer` on each recovery. Tasks are dead-lettered after `max_retries` (default: 3).
- **Compliance gating**: `PolicyGuardian.evaluate_task()` reads typed domain columns (`compliance_category`, `jurisdiction`, `requires_human_review`) — not `metadata_json`. Non-compliant tasks transition to `PENDING_REVIEW` for human approval.
- **Webhook secrets**: Stored as Fernet-encrypted ciphertext (`secret_ciphertext`, migration 0009). Decrypted at delivery time so tenants can verify HMAC-SHA256 signatures using their plaintext secret.

## Local development

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start infrastructure (Postgres + Redis)
docker compose up -d

# 3. Run migrations
alembic upgrade head

# 4. Start the API
uvicorn backend.main:app --reload

# 5. Run tests
pytest -m "not integration"          # unit tests only (no infra needed)
pytest -m integration                # integration tests (requires Postgres + Redis)
pytest                               # all tests
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `AJENDA_QUEUE_URL` | Production | Redis URL for the queue adapter |
| `AJENDA_OIDC_JWKS_URI` | Production | OIDC provider JWKS endpoint |
| `AJENDA_OIDC_ISSUER` | Production | OIDC token issuer |
| `AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY` | Production | Fernet key for webhook secret encryption |
| `AJENDA_ENV` | No | `development` (default) or `production` |

## Test suite

```
Unit tests:   269 passing
Integration:  Postgres + Redis via testcontainers (marked @pytest.mark.integration)
```

## Migrations

| ID | Description |
|----|-------------|
| 0001 | Initial schema |
| 0002 | Execution branches |
| 0003 | Row-Level Security policies |
| 0004 | Recovering state + worker leases |
| 0005 | Compliance columns on execution_tasks |
| 0006 | SaaS tenant lifecycle |
| 0007 | Webhook endpoints and deliveries |
| 0008 | retry_count + pending_review state |
| 0009 | Webhook secret_ciphertext |
