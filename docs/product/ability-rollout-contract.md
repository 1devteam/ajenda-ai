# Ability Rollout Contract

The Ability Rollout Contract defines the repeatable shape for adding future abilities, tools, providers, and role-guided workflows without redesigning the runtime path.

This contract is intentionally non-executing. It does not replace `TaskDispatcher`, `tool.invoke`, `ActionRegistry`, capability declarations, adapter declarations, queue authority, lease ownership, or `WorkerRuntimeService`.

## Purpose

Every new ability should be declared, validated, tested, and documented before promotion into runtime use.

A rollout-ready ability must define:

1. Capability declaration
2. Capability adapter declaration
3. `ToolInvocation` input schema
4. `ActionResult` and `EvidenceItem` output expectations
5. Action handler
6. Registry registration
7. Side-effect classification
8. Approval and idempotency rules
9. Evidence and readback expectations
10. Unit tests
11. Runtime integration proof
12. Validation matrix and documentation update

## Runtime authority boundary

Ability manifests describe rollout readiness. They do not execute work.

Runtime execution remains:

```text
ExecutionTask
→ queue-backed worker claim/start/run
→ TaskDispatcher
→ tool.invoke handler
→ ToolRuntimeAuthority
→ ActionRegistry
→ concrete action authority validation
→ action handler/provider
→ shared NetworkEgressAuthority for outbound HTTP/webhook/provider HTTP I/O where applicable
→ validated ActionResult and EvidenceItem
→ WorkerRuntimeService.complete/fail
→ lineage/evidence/audit/queue result
```

Ability manifests are rollout/proof contracts only. A manifest matching a registered action proves catalog alignment, not tenant runtime permission, capability enablement, adapter authority, side-effect authorization, or queue/lease ownership. Every canonical registered action must have exactly one matching manifest, and manifest drift is checked by `scripts/validation/ability_rollout_contract_check.py`. `ToolRuntimeAuthority` fails closed when a registered action has no valid manifest, then separately validates tenant-visible capability/adapter eligibility before it delegates to `ActionRegistry`. Future network-backed providers must reuse the shared egress authority extension point instead of defining parallel SSRF, DNS, redirect, Host/SNI, response-bounding, or side-effect rules. Credential-aware actions must declare a credential requirement and receive only runtime-injected credential material after ToolRuntimeAuthority and tenant-visible capability/adapter promotion pass; a credential record or reference does not grant runtime permission. This contract activates one canonical read-only provider action, `provider.external_read`, for HTTPS GET/HEAD only through the existing runtime spine. It does not activate OAuth, credential refresh, writes, sends, publishes, CRM/GTM provider SDKs, or durable third-party SaaS clients.

## Promotion requirements

A runtime-promotable ability manifest must declare approval, idempotency, evidence, and readback expectations in executable schema fields:

- `approval_required=true` is mandatory for side-effecting and external (`external_read`, `external_write`, `external_send`, `external_publish`) abilities. Approval-required abilities cannot be enabled by default.
- `idempotency_required=true` external write/send/publish abilities must also set `idempotency_contract_ref`; broad prose is not sufficient proof.
- `evidence_required=true` abilities must declare non-empty `evidence_expectations`; action handlers still must return validated `ActionResult.evidence`.
- Internal/external write, send, and publish abilities must set `readback_required=true` or provide a concrete `readback_deferred_reason`.
- High/critical-risk and external abilities cannot be enabled by default. Tenant-visible capability/adapter records remain declarative until `ToolRuntimeAuthority` validates enabled state, tenant scope, concrete action support, exact adapter side-effect classification, and side-effect authorization where required.

### Credential references

Ability rollout may require a non-secret `credential_reference`, but the reference is proof input only. Raw secret fields such as `api_key`, `token`, `authorization`, `bearer`, `password`, `secret`, `private_key`, `client_secret`, and `webhook_secret` are rejected from runtime task metadata/tool input. `CredentialRuntimeAuthority` validates tenant visibility, enabled/non-revoked/non-deleted state, provider/type compatibility, action compatibility, and side-effect-class compatibility after promotion passes and before a handler receives runtime-only credential material. Credentialed provider egress must additionally bind Authorization injection to trusted destination hosts from credential/provider metadata, not invocation-provided `allowed_hosts`. `ActionRegistry` redacts handler output and evidence recursively so secret material cannot become ability proof.

### HTTP request idempotency

`provider.external_read` is the canonical credentialed read-only provider activation path. It requires `external_read_provider`/`api_key` `credential_reference` resolution through `CredentialRuntimeAuthority`, exact `external_read` adapter classification, raw-secret input rejection, trusted credential destination host validation before Authorization injection, a strict safe read-only invocation header allowlist that rejects Cookie/custom credential-bearing headers and credential-like header values, shared `NetworkEgressAuthority` HTTPS GET/HEAD egress, disabled redirects, bounded response output, and redacted `ActionResult`/`EvidenceItem` fields. Invocation-provided `allowed_hosts` cannot expand trusted credential destinations. It does not support POST/PUT/PATCH/DELETE, OAuth refresh, background sync, CRM/GTM mutations, provider SDK fleets, sends, or publishes.

`http.request` uses the invocation method resolver: GET/HEAD are `external_read`, while POST/PUT/PATCH/DELETE are `external_write`. Write-method retries require an invocation-level idempotency key or provider-specific idempotency proof before durable provider activation; the current local contract keeps provider-specific readback deferred to future adapters.

### Webhook dispatch idempotency

`webhook.dispatch` requires an event id and dispatch attempt metadata so retries can be correlated without silently duplicating sends. Recipient-side readback remains deferred to provider-specific verification and this contract does not activate durable third-party webhook clients beyond the existing governed dispatch path.
