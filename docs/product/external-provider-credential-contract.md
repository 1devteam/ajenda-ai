# External Provider Credential Contract

This contract defines tenant-scoped provider runtime credentials used by governed
`tool.invoke` actions.

## Implemented (code truth)

- Encrypted storage in `provider_runtime_credentials` (migration `0024`)
- Gmail OAuth authorize URL + code exchange (`/v1/account/provider-credentials/gmail/oauth/*`)
- Gmail OAuth access-token refresh at credential resolve time (`gmail_runtime_token.py`, `google_oauth_cli.py`)
- LinkedIn OAuth authorize URL + code exchange (`/v1/account/provider-credentials/linkedin/oauth/*`)
- LinkedIn OAuth access-token refresh at credential resolve time (`linkedin_runtime_token.py`, `linkedin_oauth_client.py`)
- Salesforce OAuth authorize URL + code exchange (`/v1/account/provider-credentials/salesforce/oauth/*`)
- Salesforce OAuth access-token refresh at credential resolve time (`salesforce_runtime_token.py`, `salesforce_oauth_client.py`)
- Google Calendar OAuth authorize URL + code exchange (`/v1/account/provider-credentials/google-calendar/oauth/*`)
- Google Calendar OAuth access-token refresh at credential resolve time (`google_calendar_runtime_token.py`, `google_oauth_cli.py`)
- GitHub OAuth authorize URL + code exchange (`/v1/account/provider-credentials/github/oauth/*`)
- GitHub OAuth access-token refresh at credential resolve time (`github_runtime_token.py`, `github_oauth_client.py`)
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

## Email providers (`external_email`)

Ajenda supports more than Gmail for **send**. Inbox **read** remains Gmail API–centric today.

| Integration | Credential type | Send (`gtm.email_send`) | Inbox (`gtm.email_check`) | Secret shape |
|---|---|---|---|---|
| `gmail` | `api_key` | Yes (Gmail API) | Yes | OAuth bearer or JSON token bundle |
| `smtp` | `smtp` | Yes (SMTP) | No | JSON: `host`, `port`, `user`/`username`, `password`, optional `from`, `use_tls` |
| platform master | `platform_master` | Yes (SMTP JSON from operator config) | No | Operator-managed `AJENDA_EMAIL_PLATFORM_*` |

### Gmail integration defaults

When `provider=external_email` and `integration=gmail` (or default Gmail path):

- `allowed_actions`: `gtm.email_send`, `gtm.email_check`
- `allowed_side_effect_classes`: `external_read`, `external_send`
- `trusted_destination_hosts`: `gmail.googleapis.com`
- OAuth secrets are stored as JSON (`access_token`, `refresh_token`, `expires_at`); refresh occurs before invoke when expired
- Credentialed `gtm.email_check` fails closed on Gmail API errors (no simulated inbox fallback)

### SMTP integration defaults

When `provider=external_email` and `integration=smtp`:

- `allowed_actions`: `gtm.email_send` (send only)
- `allowed_side_effect_classes`: `external_send`
- Credential type: `smtp`
- Secret is JSON validated at register time (`host`, user/username, `password` required)
- Runtime transport is SMTP (`credential_transport_mode` → `smtp`); durable claim-before-send applies when migration `0034` is applied
- Works with any standards-compliant SMTP host (Workspace app password, M365, SES, SendGrid, Mailgun, Postmark, etc.)

Direct HubSpot reads may alternatively use `provider=external_read_provider` with
`trusted_destination_hosts=["api.hubapi.com"]` and action `provider.external_read`.

## LinkedIn read {#linkedin-read}

When `integration=linkedin` and `provider=external_read_provider`:

- `allowed_actions`: `linkedin.profile_read`, `provider.external_read`
- `allowed_side_effect_classes`: `external_read`
- `trusted_destination_hosts`: `api.linkedin.com`
- OAuth secrets are stored as JSON (`provider_kind=linkedin`, `access_token`, `refresh_token`, `expires_at`); refresh occurs before invoke when expired
- Product OAuth redirect: `AJENDA_LINKEDIN_OAUTH_REDIRECT_URI` (default `http://localhost:5173/credentials/linkedin/callback`)
- Runtime action `linkedin.profile_read` uses LinkedIn REST headers (`LinkedIn-Version`, `X-Restli-Protocol-Version`)
- Credentialed path fails closed on LinkedIn API errors (no simulated profile fallback)

## Google Calendar read {#google-calendar-read}

When `integration=google_calendar` and `provider=external_read_provider`:

- `allowed_actions`: `google_calendar.events_read`, `provider.external_read`
- `allowed_side_effect_classes`: `external_read`
- `trusted_destination_hosts`: `www.googleapis.com`
- OAuth secrets are stored as JSON (`provider_kind=google_calendar`, `access_token`, `refresh_token`, `expires_at`); refresh occurs before invoke when expired
- Product OAuth redirects: `AJENDA_GOOGLE_CALENDAR_OAUTH_REDIRECT_URI`, `AJENDA_GOOGLE_CONTACTS_OAUTH_REDIRECT_URI`, and `AJENDA_GOOGLE_DOCS_OAUTH_REDIRECT_URI` (defaults are the matching `/credentials/.../callback` paths on `http://localhost:5173`)
- Uses connector-only Google OAuth client vars (`AJENDA_GOOGLE_CONNECTOR_CLIENT_ID` / `AJENDA_GOOGLE_CONNECTOR_CLIENT_SECRET`). CLI vars are for local CLI tooling; OIDC fallback is legacy development compatibility only.
- Runtime action `google_calendar.events_read` lists events from Calendar API v3
- Credentialed path fails closed on Google Calendar API errors (no simulated event fallback)

## GitHub read {#github-read}

When `integration=github` and `provider=external_read_provider`:

- `allowed_actions`: `github.repo_read`, `provider.external_read`
- `allowed_side_effect_classes`: `external_read`
- `trusted_destination_hosts`: `api.github.com`
- OAuth secrets are stored as JSON (`provider_kind=github`, `access_token`, `refresh_token`, `expires_at`); refresh occurs before invoke when expired (requires OAuth app with expiring user access tokens enabled)
- Product OAuth redirect: `AJENDA_GITHUB_OAUTH_REDIRECT_URI` (default `http://localhost:5173/credentials/github/callback`)
- Default OAuth scope: `read:user` (public repository metadata does not require additional scopes)
- Runtime action `github.repo_read` reads repository metadata from GitHub REST API v3
- Credentialed path fails closed on GitHub API errors (no simulated repository fallback)
- Plain personal access tokens (PAT) may be pasted directly without JSON wrapping

## Salesforce read {#salesforce-read}

When `integration=salesforce` and `provider=external_read_provider`:

- `allowed_actions`: `salesforce.soql_read`, `provider.external_read`
- `allowed_side_effect_classes`: `external_read`
- `trusted_destination_hosts`: **required** tenant instance host (e.g. `mycompany.my.salesforce.com`); OAuth connect captures host from `instance_url`
- OAuth secrets are stored as JSON (`provider_kind=salesforce`, `access_token`, `refresh_token`, `instance_url`, `expires_at`); refresh occurs before invoke when expired
- Product OAuth redirect: `AJENDA_SALESFORCE_OAUTH_REDIRECT_URI` (default `http://localhost:5173/credentials/salesforce/callback`)
- Runtime action `salesforce.soql_read` accepts read-only `SELECT` SOQL only
- Credentialed path fails closed on Salesforce API errors (no simulated query fallback)

## Supported reference kinds (runtime envelope)

- `credential_reference` in task metadata (`schema_version=1`)
- Stored DB record keyed by `(tenant_id, credential_id)`

## Initial provider targets

- HubSpot CRM (via adapter + `external_crm`)
- Gmail (`external_email` + `integration=gmail`) — send + inbox
- SMTP email (`external_email` + `integration=smtp`) — send only, multi-provider
- Platform master email (`platform_master` SMTP) — operator-managed send lane
- LinkedIn read (`external_read_provider` + `integration=linkedin`)
- Salesforce read (`external_read_provider` + `integration=salesforce`)
- Google Calendar read (`external_read_provider` + `integration=google_calendar`)
- GitHub read (`external_read_provider` + `integration=github`)
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
