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

Ability manifests are rollout/proof contracts only. A manifest matching a registered action proves catalog alignment, not tenant runtime permission, capability enablement, adapter authority, side-effect authorization, or queue/lease ownership. Every canonical registered action must have exactly one matching manifest, and manifest drift is checked by `scripts/validation/ability_rollout_contract_check.py`. `ToolRuntimeAuthority` fails closed when a registered action has no valid manifest, then separately validates tenant-visible capability/adapter eligibility before it delegates to `ActionRegistry`. Future network-backed providers must reuse the shared egress authority extension point instead of defining parallel SSRF, DNS, redirect, Host/SNI, response-bounding, or side-effect rules; this contract does not activate OAuth, credential refresh, CRM/GTM provider SDKs, or durable third-party SaaS clients.

## Promotion requirements

A runtime-promotable ability manifest must declare approval, idempotency, evidence, and readback expectations in executable schema fields:

- `approval_required=true` is mandatory for side-effecting and external (`external_read`, `external_write`, `external_send`, `external_publish`) abilities. Approval-required abilities cannot be enabled by default.
- `idempotency_required=true` external write/send/publish abilities must also set `idempotency_contract_ref`; broad prose is not sufficient proof.
- `evidence_required=true` abilities must declare non-empty `evidence_expectations`; action handlers still must return validated `ActionResult.evidence`.
- Internal/external write, send, and publish abilities must set `readback_required=true` or provide a concrete `readback_deferred_reason`.
- High/critical-risk and external abilities cannot be enabled by default. Tenant-visible capability/adapter records remain declarative until `ToolRuntimeAuthority` validates enabled state, tenant scope, concrete action support, exact adapter side-effect classification, and side-effect authorization where required.

### HTTP request idempotency

`http.request` uses the invocation method resolver: GET/HEAD are `external_read`, while POST/PUT/PATCH/DELETE are `external_write`. Write-method retries require an invocation-level idempotency key or provider-specific idempotency proof before durable provider activation; the current local contract keeps provider-specific readback deferred to future adapters.

### Webhook dispatch idempotency

`webhook.dispatch` requires an event id and dispatch attempt metadata so retries can be correlated without silently duplicating sends. Recipient-side readback remains deferred to provider-specific verification and this contract does not activate durable third-party webhook clients beyond the existing governed dispatch path.
