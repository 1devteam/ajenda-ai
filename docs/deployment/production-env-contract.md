# Production Environment Contract

Ajenda AI production deployments must not rely on development defaults.

## Required production values

| Variable | Required | Secret | Purpose |
|---|---:|---:|---|
| `POSTGRES_PASSWORD` | yes | yes | Database password. |
| `AJENDA_DATABASE_URL` | yes | yes | SQLAlchemy database URL. |
| `AJENDA_ENV=production` | yes | no | Enables production runtime validation. |
| `AJENDA_QUEUE_ADAPTER=redis` | yes | no | Production queue backend. |
| `AJENDA_QUEUE_URL` | yes | maybe | Redis URL. Secret if it includes a password. |
| `AJENDA_WORKER_TENANT_ID` | yes | no | Tenant queue processed by this worker group. |
| `AJENDA_OIDC_ISSUER` | yes | no | OIDC issuer. Must not be localhost in production. |
| `AJENDA_OIDC_JWKS_URI` | yes | no | OIDC JWKS endpoint. Must not be localhost in production. |
| `AJENDA_OIDC_AUDIENCE` | yes | no | Expected JWT audience. |
| `AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY` | yes | yes | Fernet key for webhook signing-secret encryption. |
| `AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV` | no | yes | Previous Fernet key during key-rotation migration windows. |
| `AJENDA_AUTHZ_POLICY_MODE` | yes | no | rbac, shadow_opa, or enforce_opa. |
| `AJENDA_AUTHZ_OPA_URL` | conditional | no | Required when policy mode is shadow_opa or enforce_opa. |
| `AJENDA_AUTHZ_OPA_TIMEOUT_SECONDS` | yes | no | OPA request timeout. |

## Generate webhook encryption key

Run:

python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

Store this value in a secrets manager and expose it as:

AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY

Do not use the deterministic development/test key in production.

## Worker tenant assignment

The current worker model is tenant-specific. AJENDA_WORKER_TENANT_ID must match the tenant queue this worker group is expected to process.

For multi-tenant production, use one of these patterns:

1. one worker deployment per tenant,
2. tenant-sharded worker pools,
3. future tenant-scanning worker scheduler.

Do not leave the worker tenant as default in production.

## Production startup guardrails

Settings.validate_runtime_contract() rejects production deployments that use:

- local queue adapter,
- Redis adapter without AJENDA_QUEUE_URL,
- localhost OIDC issuer/JWKS,
- missing or invalid webhook secret encryption key,
- deterministic development/test webhook key,
- default or blank worker tenant id,
- invalid rate-limit settings,
- OPA modes without OPA URL.
