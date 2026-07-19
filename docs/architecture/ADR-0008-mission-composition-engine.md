# ADR-0008: Mission Composition Engine

- **Status:** Accepted
- **Date:** 2026-07-19
- **Owner:** AJENDA-AI Architecture Team
- **Related:** ADR-0001, ADR-0005, ADR-0006, ADR-0007, `docs/product/mission-runtime-architecture-map.md`, `docs/product/mission-based-ai-core.md`

## Context

Ajenda has a production mission ladder (intake → plan → task graph → materialization → runtime-queue-admission → workers → tool.invoke → evidence) and live external abilities (Gmail, HubSpot, Salesforce, Google Calendar). What it lacked was a governed front-end that turns plain language into multi-job work without:

- keyword routing (`"email"` → `gtm.email_send`),
- user checkbox graphs with linear fake dependencies,
- silent simulation when connections are missing,
- collapsing compose into queue admission.

Overlapping catalogs (BRAIN_MISSIONS, vertical roles/templates, ability manifests, ActionRegistry, plugin contracts, intake `allowed_actions`) need one composition owner.

## Decision

### Operating chain

```text
Language → MissionIntent (candidate)
  → BusinessJob routing
  → CapabilityResolver (registry + manifest + charter + connections)
  → MissionCompositionRecord (proposal)
  → Confirm → mission intake + plan + task graph
  → Existing staged runtime admission (explicit, separate)
```

### Authority boundaries

| Surface | Authority class | Must not |
|---|---|---|
| `POST /v1/missions/compose` | `read_model` | Create tasks, queue, leases, provider side effects |
| Confirm composition | `governed_mutation` | Queue, materialize runtime tasks, invoke tools |
| Runtime queue admission | `runtime_authoritative` | Remain the only canonical enqueue path |

### Rules

1. Interpreter may draft intent; deterministic validation owns acceptance.
2. Jobs sit between outcomes and actions; no direct keyword→send.
3. `allowed_actions` is produced by the composition engine with provenance (`selected_by=mission_composition_engine`).
4. Operating Charter (`may_prepare` / `may_perform` / `never_do`) is a first-class selection filter.
5. Missing connections are reported; success is never simulated.
6. Catalog-only jobs/abilities cannot enter runtime graphs.
7. Frontend linear graph authoring is superseded by backend dependency compilation.
8. Compatibility `POST /v1/missions/{id}/queue` is not the primary start path.

### Accounting

Accounting jobs may appear as `catalog_only` structural entries. No fabricated QuickBooks/Xero runtime handlers until provider proof exists.

## Consequences

### Positive

- Conversational missions become possible without weakening runtime governance.
- One composition record ties jobs, verticals, abilities, and graph preview.
- Live provider integrations remain behind credential readiness.

### Tradeoffs

- In-process proposal store is not multi-worker durable; confirm accepts full composition body.
- Intent interpreter v1 is deterministic (not free-form LLM).

## Verification

- Unit: intent, job routing, capability resolver, plan/graph compiler, roofing flagship.
- Contract: compose creates no runtime state; confirm creates intake/plan/graph only.
- Future: live e2e plain language → queue admission → worker evidence.
