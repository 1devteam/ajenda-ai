from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PluginCategory = Literal["brain", "crm", "email", "calendar", "social", "http", "webhook"]
PluginMode = Literal["standalone", "plugin", "hybrid"]


@dataclass(frozen=True, slots=True)
class CrmContractPaths:
    search_path: str = "/v1/search"
    upsert_path: str = "/v1/upsert"
    read_path: str | None = None


@dataclass(frozen=True, slots=True)
class PluginContract:
    plugin_id: str
    display_name: str
    category: PluginCategory
    provider: str
    mode: PluginMode
    description: str
    credential_provider: str | None = None
    credential_types: tuple[str, ...] = ()
    integration_types: tuple[str, ...] = ()
    trusted_hosts: tuple[str, ...] = ()
    crm_paths: CrmContractPaths | None = None
    supported_actions: tuple[str, ...] = ()
    standalone_actions: tuple[str, ...] = ()
    requires_external_credential: bool = False
    documentation_ref: str | None = None


STANDARD_CRM_CONTRACT = CrmContractPaths(
    search_path="/v1/search",
    upsert_path="/v1/upsert",
)

BUILTIN_PLUGIN_CONTRACTS: tuple[PluginContract, ...] = (
    PluginContract(
        plugin_id="ajenda-brain",
        display_name="Ajenda Central Brain",
        category="brain",
        provider="ajenda_brain",
        mode="standalone",
        description=(
            "Tenant-scoped durable contacts, accounts, and opportunities plus local "
            "sales intelligence. No external CRM required."
        ),
        supported_actions=(
            "record.search",
            "record.read",
            "record.write",
            "sales.research",
            "sales.qualify",
            "sales.score_lead",
            "sales.recommend_next_action",
            "sales.draft_followup",
            "sales.log_activity",
            "sales.create_followup_task",
            "web.research",
            "web.search",
            "gtm.lead_enrich",
            "gtm.email_draft",
            "retrieval.hybrid_search",
        ),
        standalone_actions=(
            "record.search",
            "record.read",
            "record.write",
            "web.research",
            "web.search",
            "sales.qualify",
            "sales.score_lead",
            "sales.recommend_next_action",
            "sales.draft_followup",
            "gtm.lead_enrich",
            "gtm.email_draft",
            "retrieval.hybrid_search",
        ),
        documentation_ref="docs/product/plugin-architecture.md#ajenda-central-brain",
    ),
    PluginContract(
        plugin_id="hubspot-crm",
        display_name="HubSpot CRM Adapter",
        category="crm",
        provider="external_crm",
        mode="plugin",
        description="HTTP CRM adapter implementing the standard /v1/search and /v1/upsert contract.",
        credential_provider="external_crm",
        credential_types=("api_key", "platform_master"),
        integration_types=("hubspot", "generic"),
        crm_paths=STANDARD_CRM_CONTRACT,
        supported_actions=("sales.research", "crm.research", "crm.read", "gtm.crm_upsert"),
        requires_external_credential=True,
        documentation_ref="docs/product/external-provider-credential-contract.md",
    ),
    PluginContract(
        plugin_id="gmail-email",
        display_name="Gmail API",
        category="email",
        provider="external_email",
        mode="plugin",
        description="Send and read email via Gmail REST API using OAuth bearer tokens.",
        credential_provider="external_email",
        credential_types=("api_key",),
        integration_types=("gmail",),
        trusted_hosts=("gmail.googleapis.com",),
        supported_actions=("gtm.email_send", "gtm.email_check"),
        requires_external_credential=True,
        documentation_ref="docs/product/plugin-architecture.md#gmail-plugin",
    ),
    PluginContract(
        plugin_id="smtp-email",
        display_name="SMTP Email",
        category="email",
        provider="external_email",
        mode="plugin",
        description="Send email via tenant SMTP credentials (host, port, user, password JSON).",
        credential_provider="external_email",
        credential_types=("smtp",),
        integration_types=("smtp",),
        supported_actions=("gtm.email_send",),
        requires_external_credential=True,
        documentation_ref="docs/product/plugin-architecture.md#smtp-plugin",
    ),
    PluginContract(
        plugin_id="linkedin-read",
        display_name="LinkedIn Read API",
        category="social",
        provider="external_read_provider",
        mode="plugin",
        description="Read-only LinkedIn profile lookups via OAuth bearer tokens to api.linkedin.com.",
        credential_provider="external_read_provider",
        credential_types=("api_key",),
        integration_types=("linkedin",),
        trusted_hosts=("api.linkedin.com",),
        supported_actions=("linkedin.profile_read", "provider.external_read"),
        requires_external_credential=True,
        documentation_ref="docs/product/external-provider-credential-contract.md#linkedin-read",
    ),
    PluginContract(
        plugin_id="salesforce-read",
        display_name="Salesforce Read API",
        category="crm",
        provider="external_read_provider",
        mode="plugin",
        description="Read-only Salesforce SOQL queries via tenant instance host and OAuth bearer token.",
        credential_provider="external_read_provider",
        credential_types=("api_key",),
        integration_types=("salesforce",),
        supported_actions=("salesforce.soql_read", "provider.external_read"),
        requires_external_credential=True,
        documentation_ref="docs/product/external-provider-credential-contract.md#salesforce-read",
    ),
    PluginContract(
        plugin_id="google-calendar-read",
        display_name="Google Calendar Read API",
        category="calendar",
        provider="external_read_provider",
        mode="plugin",
        description="Read-only Google Calendar event listings via OAuth bearer token to www.googleapis.com.",
        credential_provider="external_read_provider",
        credential_types=("api_key",),
        integration_types=("google_calendar",),
        trusted_hosts=("www.googleapis.com",),
        supported_actions=("google_calendar.events_read", "provider.external_read"),
        requires_external_credential=True,
        documentation_ref="docs/product/external-provider-credential-contract.md#google-calendar-read",
    ),
    PluginContract(
        plugin_id="github-read",
        display_name="GitHub Read API",
        category="devtools",
        provider="external_read_provider",
        mode="plugin",
        description="Read-only GitHub repository metadata via OAuth bearer token to api.github.com.",
        credential_provider="external_read_provider",
        credential_types=("api_key",),
        integration_types=("github",),
        trusted_hosts=("api.github.com",),
        supported_actions=("github.repo_read", "provider.external_read"),
        requires_external_credential=True,
        documentation_ref="docs/product/external-provider-credential-contract.md#github-read",
    ),
    PluginContract(
        plugin_id="governed-http",
        display_name="Governed HTTP Egress",
        category="http",
        provider="httpx",
        mode="standalone",
        description="SSRF-hardened HTTP client for web research and API reads.",
        supported_actions=("http.request", "web.research", "web.search"),
        standalone_actions=("http.request", "web.research", "web.search"),
        documentation_ref="docs/product/plugin-architecture.md#governed-http",
    ),
    PluginContract(
        plugin_id="tenant-webhooks",
        display_name="Tenant Webhooks",
        category="webhook",
        provider="webhook_dispatch",
        mode="standalone",
        description="Dispatch events to tenant-configured webhook endpoints.",
        supported_actions=("webhook.dispatch",),
        standalone_actions=("webhook.dispatch",),
    ),
    PluginContract(
        plugin_id="local-calendar",
        display_name="Local Calendar",
        category="calendar",
        provider="local_calendar",
        mode="standalone",
        description="In-process calendar provider for scheduling without Google Calendar.",
        supported_actions=("calendar.read", "calendar.create_event"),
        standalone_actions=("calendar.read", "calendar.create_event"),
    ),
)
