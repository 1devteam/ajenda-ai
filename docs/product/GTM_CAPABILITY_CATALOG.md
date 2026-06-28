# AJENDA-AI GTM Capability Catalog

**Status:** Runtime binding implemented for core GTM actions (internal + high-risk external with credential requirements wired and real network_egress paths for email/CRM/social). Side-effect resolvers align registry defaults (`INTERNAL_*`) with credentialed runtime classes (`EXTERNAL_*`). Hybrid CRM research fallback is explicit and machine-flagged.  
**Effective date:** May 27, 2026  
**Owner:** Product/Architecture + Growth Operations  
**Last reviewed:** June 27, 2026

---

## 1) Purpose

This catalog defines the first-class GTM capability taxonomy for AJENDA-AI.
Catalog entries in this document are declarative product contracts, not runtime execution grants.

---

## 2) Capability contract schema (logical)

Each GTM capability should define at minimum:

- `capability_id` (stable namespaced id)
- `name`
- `mission_family` (`lead_discovery`, `outbound_sequencing`, `content_pipeline`, `attribution_conversion`)
- `channel` (`email`, `linkedin`, `blog`, `social`, `web`, `crm`, `analytics`, `internal`)
- `risk_class` (`low`, `moderate`, `high`, `critical`)
- `approval_mode` (`none`, `sample_review`, `required`, `multi_party_required`)
- `requires_human_gate` (`true/false`)
- `side_effect_class` (`none`, `external_write`, `external_send`, `external_publish`)
- `policy_profile` (reference to outbound communication policy profile)
- `evidence_requirements` (list)
- `enabled_by_default` (`false` for high-risk capability classes)
- `schema_version`

---

## 3) Capability families and baseline entries

## A) Lead discovery and qualification

| Capability ID | Name | Channel | Risk | Approval | Side effect class | Notes |
|---|---|---|---|---|---|---|
| `gtm.lead.discovery.query_builder.v1` | Lead discovery query builder | web | low | none | none | Generates search criteria and ICP-aligned query sets. |
| `gtm.lead.discovery.candidate_enrichment.v1` | Candidate enrichment | web/crm | moderate | sample_review | external_write | Adds enrichment facts with provenance tags. |
| `crm.research` / `crm.read` | Generic CRM research/read | crm | moderate | required (when credentialed) | external_read | Default Ajenda brain (`internal_read`); with `credential_reference` promotes to `external_read` via HubSpot sidecar. Hybrid fallback sets `external_attempt_failed=true` on adapter failure (ADR-0006). |
| `sales.research` | Sales lead research | crm/internal | moderate | required (when credentialed) | internal_read / external_read | Same hybrid CRM doctrine as `crm.research`; aliases: `crm.research`, `crm.read`. |
| `gtm.email_check` | Gmail inbox read | email | high | required (when credentialed) | external_read | Simulated inbox only without credential; credentialed path fails closed on Gmail API errors. |
| `gtm.crm_upsert` | CRM record upsert | crm | high | multi_party_required (credentialed) | internal_write / external_write | Internal brain write without credential; credentialed path uses plugin egress and does not hybrid-fallback. |
| `linkedin.profile_read` | LinkedIn profile lookup | linkedin | high | required (when credentialed) | external_read | Simulated profile only without credential; register via Credentials UI OAuth or paste; credentialed path fails closed on API errors. |
| `salesforce.soql_read` | Salesforce SOQL query (SELECT only) | crm | high | required (when credentialed) | external_read | Simulated rows without credential; register via Credentials UI OAuth (instance host captured) or paste with instance host; credentialed path fails closed. |
| `google_calendar.events_read` | Google Calendar event listing | calendar | high | required (when credentialed) | external_read | Simulated events without credential; register via Credentials UI Google OAuth or paste; credentialed path fails closed. |
| `gtm.lead.discovery.qualification_scoring.v1` | Qualification scoring | internal | moderate | sample_review | none | Produces explainable scoring and disqualification reasons. |

## B) Outbound sequencing and follow-up

| Capability ID | Name | Channel | Risk | Approval | Side effect class | Notes |
|---|---|---|---|---|---|---|
| `gtm.outbound.sequence_strategy.v1` | Sequence strategy planner | email/linkedin | moderate | sample_review | none | Proposes sequence timing and channel mix. |
| `gtm.outbound.message_draft.v1` | Outbound message drafting | email/linkedin | moderate | required | none | Generates drafts only; no autonomous send authority. |
| `gtm.outbound.send_dispatch.v1` | Outbound dispatch | email/linkedin | high | multi_party_required | external_send | Runtime binding forbidden until Bundle 6.3+ gates. |

## C) Social/blog content pipeline

| Capability ID | Name | Channel | Risk | Approval | Side effect class | Notes |
|---|---|---|---|---|---|---|
| `gtm.content.theme_planning.v1` | Content theme planner | social/blog | low | none | none | Selects topics and campaign themes with source prompts. |
| `gtm.content.draft_generation.v1` | Content draft generation | social/blog | moderate | required | none | Produces attributed draft artifacts and claims map. |
| `gtm.content.publish_dispatch.v1` | Content publish dispatch | social/blog | high | multi_party_required | external_publish | Runtime binding requires strict policy + approval evidence. |

## D) Attribution and conversion evidence

| Capability ID | Name | Channel | Risk | Approval | Side effect class | Notes |
|---|---|---|---|---|---|---|
| `gtm.attribution.event_mapping.v1` | Event mapping contract | analytics | low | none | none | Maps mission actions to attribution event schema. |
| `gtm.attribution.evidence_packaging.v1` | Attribution evidence packaging | analytics/internal | moderate | sample_review | external_write | Persists evidence records for outcome review. |
| `gtm.attribution.optimization_recommendation.v1` | Optimization recommendations | analytics/internal | moderate | required | none | Produces read-model recommendations only. |

---

## 4) Mandatory policy and approval rules

1. Capabilities with `external_send` or `external_publish` side effects must require explicit human approval.
2. `high` and `critical` risk capabilities default disabled unless tenant policy enables them.
3. Declarative capability records must not be treated as runtime handler bindings.
4. Policy-denied tasks must terminate before queue admission.
5. Every action must emit tenant-scoped evidence with capability and policy references.

---

## 5) Capability-to-adapter mapping constraints

- One capability may map to multiple adapters by channel, but each adapter must declare explicit side-effect class and policy profile.
- Adapters for send/publish actions must support idempotency keys and deterministic replay safety.
- Adapter onboarding requires contract tests for:
  - tenant scoping
  - auth envelope handling
  - policy deny-path behavior
  - evidence payload completeness

---

## 6) Initial pilot candidate set (Bundle 6.3 target)

Recommended first runtime-bound pilot capabilities:

1. `gtm.content.draft_generation.v1` (draft-only, no publish)
2. `gtm.outbound.message_draft.v1` (draft-only, no send)

Deferred high-risk capabilities until explicit pilot hardening:

- `gtm.outbound.send_dispatch.v1`
- `gtm.content.publish_dispatch.v1`

---

## 7) Backward compatibility and evolution rules

- Additive fields only for catalog evolution in active minor versions.
- `capability_id` and `schema_version` are immutable once published.
- Semantic meaning of existing risk or approval values must not be repurposed silently.
- Unknown future `schema_version` values must fail closed.

## 8) Cutting-edge extensions (post-pilot)

- Retrieval hybrid with governance contracts (implemented foundation, advanced evidence).
- Wasm/TEE for untrusted code execution in abilities (contract layer started; runtime deferred).
- Agentic extensions for autonomous GTM workflows (future).

