# ADR-0006: External Platform Integration Doctrine

- **Status:** Accepted
- **Date:** 2026-06-27
- **Owner:** AJENDA-AI Architecture Team
- **Related:** `docs/product/external-provider-credential-contract.md`, `docs/product/plugin-architecture.md`, ADR-0001, ADR-0005

## Context

Ajenda's runtime spine (`tool.invoke` → `ToolRuntimeAuthority` → `CredentialRuntimeAuthority` → `NetworkEgressAuthority` → `EvidenceItem`) is production-grade for HubSpot CRM and Gmail. Before cloning the pattern to LinkedIn or Salesforce, we need explicit doctrine for:

- when PluginContract sidecars vs in-process capability adapters apply,
- OAuth token refresh boundaries,
- side-effect taxonomy for hybrid internal/external actions,
- fail-closed behavior on credentialed external paths.

## Decision

### 1. Runtime spine (mandatory for all external platforms)

All external platform work must traverse:

1. `ToolRuntimeAuthority.authorize` (ability manifest alignment + capability promotion)
2. `CredentialRuntimeAuthority.resolve_for_action` (tenant-scoped secret materialization)
3. `NetworkEgressAuthority.request` (pinned hosts, no raw secret leakage)
4. `EvidenceItem` emission with redacted payloads

No bypass via direct HTTP clients, task metadata secrets, or handler-local sockets.

### 2. Integration surfaces

| Surface | Use when |
|---|---|
| **PluginContract sidecar** (e.g. HubSpot CRM ingress) | Vendor API shape differs from Ajenda generic CRM contract; egress pinning to a controlled adapter host is required |
| **In-process provider module** (e.g. Gmail) | OAuth lifecycle, MIME construction, or provider-specific headers belong in governed Python modules behind the same runtime spine |
| **CapabilityAdapter registry record** | Declarative promotion authority only; never execution authority |

### 3. Credential contract

- Task metadata carries `credential_reference` only; secrets resolve at invoke time.
- Gmail OAuth refresh is **in scope** and implemented via `gmail_runtime_token` / `google_oauth_cli` at repository read time.
- LinkedIn and Salesforce OAuth refresh is **in scope** via `linkedin_runtime_token` / `salesforce_runtime_token` at repository read time (product OAuth connect + Credentials UI).
- Credentialed external paths **fail closed** on provider errors (no simulated success). Example: `gtm.email_check` raises on Gmail API failure when a credential is present.
- SMTP remains a scoped alternate transport for `gtm.email_send` when credential transport mode permits; HTTPS Gmail API is the default real path.

### 4. Side-effect taxonomy

Registry default side-effect classes represent the **no-credential** path (`INTERNAL_READ` / `INTERNAL_WRITE`). When `credential_reference` is present:

| Action | Resolver outcome | Handler outcome |
|---|---|---|
| `sales.research` / `crm.research` | `EXTERNAL_READ` | External egress attempted; may hybrid-fallback to Ajenda brain |
| `gtm.crm_upsert` | `EXTERNAL_WRITE` | External upsert via plugin; errors return `real=false` without brain fallback |
| `gtm.email_check` | `EXTERNAL_READ` | Live Gmail read or fail closed |
| `gtm.email_send` | `EXTERNAL_SEND` | Live send or explicit error result |
| `linkedin.profile_read` | `EXTERNAL_READ` | Live LinkedIn profile read or fail closed |
| `salesforce.soql_read` | `EXTERNAL_READ` | Live SELECT SOQL or fail closed |

`ToolRuntimeAuthority` enriches `ToolInvocation.credential_reference` from task metadata before resolver evaluation so runtime and catalog stay aligned.

### 5. Hybrid CRM research mode (explicit resilience)

`sales.research` with a credential may fall back to Ajenda brain when the external CRM adapter fails. This is **intentional hybrid mode**, not silent misclassification:

- Output includes `external_attempt_failed=true` and `hybrid_mode=true`
- `research_notes` documents the external error
- Side-effect class remains `EXTERNAL_READ` because an external attempt was authorized and egress was attempted

`gtm.crm_upsert` does **not** hybrid-fallback; credentialed failures remain external errors.

### 6. Expansion gate (LinkedIn, Salesforce)

#### Hold status

| Field | Value |
|---|---|
| **Status** | Lifted |
| **Date** | 2026-06-27 |
| **Lifted by** | Obex Blackvault |
| **Commit** | `576a6c6` |
| **Reason** | P0 requirements completed and verified (fail-closed `gtm.email_check`, side-effect resolvers, taxonomy alignment, doc/ledger refresh, integration proofs, `contract_drift_check` enforcement). |

Platform expansion is authorized under this ADR in this order:

1. **LinkedIn read-only** — `linkedin.profile_read` + `external_read_provider` / `integration=linkedin`
2. **Salesforce read-only** — `salesforce.soql_read` + `external_read_provider` / `integration=salesforce` (tenant instance host required)

P0 prerequisites (all satisfied at hold lift):

1. Fail-closed credentialed reads/sends
2. Resolver-backed side-effect taxonomy in registry + ability catalog
3. Authority ledger + product catalog alignment
4. Integration proofs without `validate_capability_action_authority` monkeypatch

## Consequences

### Positive

- Audit surface matches actual network behavior
- Hybrid CRM mode is documented and machine-detectable
- New platforms inherit a checklisted, cloneable spine

### Tradeoffs

- Hybrid CRM research can return brain data after external failure; missions must inspect `external_attempt_failed`
- External reads require capability/adapter promotion even when falling back internally

## Verification impact

- `tests/integration/credentials/test_external_invoke_authority_real.py` — cross-tenant denial, CRM/Gmail invoke without capability monkeypatch
- `tests/unit/tools/test_gtm_actions.py` — credentialed email check fail-closed
- `scripts/validation/ability_rollout_contract_check.py` — manifest/resolver alignment
- `docs/contracts/authority-ledger.v1.yaml` — Gmail egress + CRM hybrid proofs

## Rollback strategy

Revert resolver enrichment in `ToolRuntimeAuthority` and restore prior INTERNAL-only registry classes only if all dependent integration proofs and catalog entries are rolled back in the same release.