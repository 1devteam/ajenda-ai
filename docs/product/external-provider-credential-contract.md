# External Provider Credential Contract

This contract defines tenant-scoped provider runtime credentials used by governed
`tool.invoke` actions.

## Implemented (code truth)

- Encrypted storage in `provider_runtime_credentials` (migration `0024`)
- Gmail OAuth authorize URL + code exchange (`/v1/account/provider-credentials/gmail/oauth/*`)
- Gmail OAuth access-token refresh at credential resolve time (`gmail_runtime_token.py`, `google_oauth_cli.py`)
- HTTP lifecycle API:
  - `POST /v1/account/provider-credentials`
  - `GET /v1/account/provider-credentials`
  - `POST /v1/account/provider-credentials/{credential_id}/revoke`
  - `DELETE /v1/account/provider-credentials/{credential_id}`
- RBAC: `credentials:read`, `credentials:manage`
- Runtime resolution via `CredentialRuntimeAuthority` + `SQLAlchemyCredentialRuntimeRepository`
- HubSpot CRM adapter (`services/hubspot_crm_adapter`) exposing Ajenda generic CRM paths:
  - `GET /v1/search`
  - `POST /v1/upsert`

## Rules

- Credentials must be tenant-scoped (RLS + repository checks).
- Manifests and action inputs must not contain plaintext secrets.
- Task metadata carries `credential_reference` only; secrets are resolved at runtime.
- API responses never return plaintext secrets after registration.
- Audit events emit on register/revoke/delete (`category=credentials`).
- Platform master key mode is operator-controlled and emits explicit warnings.

## Credential types

| `credential_type` | Meaning |
|-------------------|---------|
| `api_key` | Tenant-supplied bearer token (e.g. HubSpot personal access key) |
| `platform_master` | Uses `AJENDA_HUBSPOT_PLATFORM_MASTER_KEY` at runtime (shared blast radius) |

## HubSpot integration defaults

When `integration=hubspot` and `provider=external_crm`:

- `allowed_actions`: `sales.research`, `crm.research`, `crm.read`, `gtm.crm_upsert`
- `allowed_side_effect_classes`: `external_read`, `external_write`
- `trusted_destination_hosts`: `AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST` (TLS ingress hostname)

## Gmail integration defaults

When `provider=external_email`:

- `allowed_actions`: `gtm.email_send`, `gtm.email_check`
- `allowed_side_effect_classes`: `external_read`, `external_send`
- `trusted_destination_hosts`: `gmail.googleapis.com`
- OAuth secrets are stored as JSON (`access_token`, `refresh_token`, `expires_at`); refresh occurs before invoke when expired
- Credentialed `gtm.email_check` fails closed on Gmail API errors (no simulated inbox fallback)

Direct HubSpot reads may alternatively use `provider=external_read_provider` with
`trusted_destination_hosts=["api.hubapi.com"]` and action `provider.external_read`.

## Supported reference kinds (runtime envelope)

- `credential_reference` in task metadata (`schema_version=1`)
- Stored DB record keyed by `(tenant_id, credential_id)`

## Initial provider targets

- HubSpot CRM (via adapter + `external_crm`)
- Gmail (`external_email`)
- Google Calendar
- GitHub
- Generic CRM HTTP
- Browser
- MCP (contract only; runtime bridge deferred)

## Fail-closed rules (credentialed external paths)

- Missing, cross-tenant, revoked, or incompatible credentials deny before provider execution.
- `gtm.email_check` with a resolved credential must not return simulated messages (`sim-1`) on API failure.
- `gtm.crm_upsert` with a credential does not silently fall back to Ajenda brain on adapter failure.
- `sales.research` may hybrid-fallback to Ajenda brain after external failure; output must set `external_attempt_failed=true` (see ADR-0006).

## Non-goals

- Returning secrets on list/get endpoints
- Bypassing `ToolRuntimeAuthority` / queue / evidence path
- Direct provider HTTP from handlers without `NetworkEgressAuthority`