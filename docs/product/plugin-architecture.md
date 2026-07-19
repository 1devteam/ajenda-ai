# Ajenda Plugin Architecture

Ajenda is the **central brain**. External CRM, email, and social systems are **optional plugins**
that extend the brain through governed credentials and standard HTTP contracts.

## Design principles

1. **Standalone first** — tenants can run missions with durable internal contacts, web research,
   local sales intelligence, and calendar scheduling without any external plugin.
2. **Plugins are adapters** — declarative DB capability/adapter records govern promotion;
   executable plugins are HTTP sidecars or credential-backed providers discovered via `/v1/plugins`.
3. **Fail-closed external effects** — outbound email, CRM writes, and social publish require
   credentials and side-effect authorization; simulated outcomes never masquerade as success.
4. **Standard CRM contract** — external CRM plugins implement:
   - `GET /v1/search?company=&domain=`
   - `POST /v1/upsert` with `{record_type, data}`

## Ajenda central brain

Plugin id: `ajenda-brain`

| Capability | Actions | Storage |
|------------|---------|---------|
| Internal CRM | `record.search`, `record.read`, `record.write` | `tenant_internal_records` (Postgres) or in-memory fallback |
| Sales intelligence | `sales.qualify`, `sales.score_lead`, `sales.recommend_next_action`, `sales.draft_followup` | Heuristic runtime |
| Hybrid research | `sales.research`, `web.research` | Brain + optional CRM plugin |
| Internal upsert | `gtm.crm_upsert` (no credential) | Writes to `tenant_internal_records` |

### Durable internal records

When a worker session is available, record actions persist to `tenant_internal_records` with
tenant RLS. Without a DB session (unit tests), the in-memory `LocalRecordProvider` is used.

## Plugin discovery API

```
GET /v1/plugins
GET /v1/plugins/{plugin_id}
GET /v1/plugins/actions/{action_name}/plugins
```

Returns plugin metadata: category, mode (`standalone` | `plugin` | `hybrid`), credential
requirements, standard CRM paths, and supported actions.

## HubSpot CRM plugin

Plugin id: `hubspot-crm`

Register credentials via `POST /v1/account/provider-credentials` with
`provider=external_crm`, `integration=hubspot`. Runtime resolves the adapter host from
`trusted_destination_hosts` (default: `AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST`).

Brain actions (`sales.research`, `gtm.crm_upsert`) accept `external_crm` credentials through
the plugin credential bridge even though their canonical provider is `ajenda_brain`.

## Email plugins (multi-provider)

### Gmail plugin

Plugin id: `gmail-email`

Register with `provider=external_email`, `integration=gmail`, `credential_type=api_key`.
Secret is an OAuth bearer token or JSON token bundle. Actions: `gtm.email_send`, `gtm.email_check`.

Product UI: **Connections → Gmail (Google)**.

### SMTP plugin (any mail host)

Plugin id: `smtp-email`

Register with `provider=external_email`, `integration=smtp`, `credential_type=smtp`.
Secret is JSON:

```json
{
  "host": "smtp.example.com",
  "port": 587,
  "user": "sender@example.com",
  "password": "app-password",
  "use_tls": true,
  "from": "sender@example.com"
}
```

Action: `gtm.email_send` only (not inbox read). Compatible with Google app passwords, Microsoft 365,
Amazon SES, SendGrid, Mailgun, Postmark, and other SMTP endpoints.

Product UI: **Connections → Email (SMTP)** builds this JSON from form fields.

### Platform master email

Operator-managed `platform_master` credential (`ajenda-email`) also routes send through SMTP JSON.
Tenants may use it without connecting their own mailbox; blast radius is shared.

## Governed HTTP

Plugin id: `governed-http`

`http.request` and `web.research` use SSRF-hardened egress. `web.research` combines internal
record search with optional public page fetch (when `fetch_public_page=true` and `domain` set).

## Extension checklist

1. Add `PluginContract` entry in `backend/services/plugins/contracts.py`
2. Implement handler or sidecar adapter
3. Register action in `action_registry.py` + `catalog.py` manifest
4. Add credential defaults in `management_service.py` if credential-backed
5. Add tests under `tests/unit/plugins/` and `tests/contract/api/`
6. Run `python scripts/validation/ability_rollout_contract_check.py`