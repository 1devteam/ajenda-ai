# ADR-0008: Mission Composition Engine

- **Status:** Accepted
- **Date:** 2026-07-19
- **Updated:** 2026-07-27
- **Owner:** AJENDA-AI Architecture Team
- **Related:** ADR-0001, ADR-0005, ADR-0006, ADR-0007, `docs/product/mission-runtime-architecture-map.md`, `docs/product/mission-based-ai-core.md`

## Context

Ajenda has a production mission ladder (intake → plan → task graph → materialization → runtime-queue-admission → workers → tool.invoke → evidence) and live external abilities (Gmail, HubSpot, Salesforce, Google Calendar, Google Contacts). What it lacked was a governed front-end that turns plain language into multi-job work without:

- keyword routing (`"email"` → `gtm.email_send`),
- user checkbox graphs with linear fake dependencies,
- silent simulation when connections are missing,
- collapsing compose into queue admission,
- fragment-style clarification that the frontend cannot merge into intent.

Overlapping catalogs (BRAIN_MISSIONS, vertical roles/templates, ability manifests, ActionRegistry, plugin contracts, intake `allowed_actions`) need one composition owner.

## Decision

### Operating chain

```text
Raw instruction (frontend display/input only)
  → normalize (optional spelling/fuzzy candidates)
  → MissionIntent (canonical outcome IDs + structured fields)
  → BusinessJob routing (IDs only)
  → CapabilityResolver (registry + manifest + charter + connections)
  → MissionCompositionRecord (proposal; durable history when DB present)
  → Confirm → mission intake + plan + task graph
  → Existing staged runtime admission (explicit, separate)
```

### Authority boundaries

| Surface | Authority class | Must not |
|---|---|---|
| `POST /v1/missions/compose` | `read_model` | Create tasks, queue, leases, provider side effects |
| Confirm composition | `governed_mutation` | Queue, materialize runtime tasks, invoke tools |
| Runtime queue admission | `runtime_authoritative` | Remain the only canonical enqueue path |
| Language-processing libraries | candidate generation only | Select abilities or grant authority |

### Rules

1. Interpreter may draft intent; deterministic validation owns acceptance.
2. Jobs sit between **canonical outcome IDs** and actions; no direct keyword→send.
3. `allowed_actions` is produced by the composition engine with provenance (`selected_by=mission_composition_engine`).
4. Operating Charter (`may_prepare` / `may_perform` / `never_do`) is a first-class selection filter.
5. Missing connections are reported; success is never simulated.
6. Catalog-only jobs/abilities cannot enter runtime graphs.
7. Frontend linear graph authoring is superseded by backend dependency compilation.
8. Compatibility `POST /v1/missions/{id}/queue` is not the primary start path.
9. **Restatement, not fragment merge:** when interpretation is incomplete, return full-mission restatement requirements; each compose submit is a standalone raw instruction. Frontend must not patch `MissionIntent`.
10. **Structured policy:** `send_policy`, `requested_quantity`, and target entities are authoritative; success-criteria prose and constraint strings are display/evidence, not data transport.
11. **Vocabulary ownership:** interpreter owns NL aliases; job catalog owns outcome IDs + completion contracts + candidate actions; ability manifests stay governance-only.
12. **Optional NLP** (spelling/fuzzy) may propose candidates behind flags; identical governance must hold when libraries are disabled. Active components are recorded on the intent/proposal.

### Structured MissionIntent (interpreter v3+)

Material fields include:

- `requested_outcomes` — canonical IDs (`research_prospects`, `prepare_outreach`, `send_outreach`, …)
- `requested_quantity` + provenance
- `send_policy` (`allow` | `forbid` | `conditional` | `unknown` + condition)
- `target_entities` (with provenance/confidence)
- `interpreted_clauses` / `unmatched_material_clauses` / `coverage_score`
- `interpretation_evidence`
- `ambiguity` — restatement requirements (field + full-mission text + reason)

### Proposal durability

- In-process cache remains for single-process compose→confirm.
- When a DB session is present, proposals are also persisted to `mission_composition_proposals` (migration `0035_composition_proposals`) for audit, supersession, and backend-owned restatement loop escalation.
- History rows are declarative only and **never** grant execution authority.
- Confirm still re-composes server-side from the instruction and distrusts client ability selections / ready flags.

### Accounting

Accounting jobs may appear as `catalog_only` structural entries. No fabricated QuickBooks/Xero runtime handlers until provider proof exists.

## Product shell (phase complete)

Everyday **Missions** UI stands on this engine:

1. **Few templates** — starters that only fill the query box (never lock skills).
2. **Executable-mission tip** — outcome, scope, hard limits, optional connections.
3. **Query box** — plain-language request; compose classifies and plans.
4. **Plan review** — outcome steps only; no skill/ability pickers.
5. **Start mission** — confirm creates intake + plan + task graph; execution continues on the mission execution page.
6. **Restatement UX** — when not ready, UI asks the user to restate the **complete** mission (not answer fragments).

Doctrine: **all governed skills remain available to Ajenda** for classification and planning. Users never assemble a toolkit. Charter, missing connections, and catalog-only maturity still fail closed at selection/execution time.

Task-graph capability references use the same `bridge_*` naming as runtime authority provisioning so confirm → execute does not rename nodes.

**Connections** (`/connections`, `/credentials`) stay separate from identity OIDC: Google sign-in uses `openid email profile` only; Gmail / Calendar / Contacts use dedicated OAuth connector scopes and redirects.

## Consequences

### Positive

- Conversational / mission-based product is possible without weakening runtime governance.
- One composition record ties jobs, verticals, abilities, and graph preview.
- Live provider integrations remain behind credential readiness.
- Skill checkboxes are removed from the mission path (legacy Tasks remains advanced-only).
- Clarification loops from fragment answers are closed via restatement + structured fields.
- Multi-worker proposal history is durable when DB is available.

### Tradeoffs

- Confirm still accepts a full composition body for multi-process compatibility; server re-compose remains authoritative.
- Intent interpreter remains deterministic (not free-form LLM); optional fuzzy/spelling only propose candidates.
- Full auto-queue on confirm remains deferred — queue admission stays the runtime authority.

## Verification

- Unit: intent (canonical IDs, send policy, restatement, coverage), job routing, capability resolver, plan/graph compiler, roofing flagship, linguistic helpers disabled path.
- Contract: compose creates no runtime state; confirm creates intake/plan/graph only.
- Migration: head includes `0035_composition_proposals`; round-trip green.
- Frontend: Missions page = templates + tip + query + restatement copy; Connections OAuth-first for Google connectors; no ability selectors.
- Live runtime proof: CI / staging proof on the composition + credentials path as configured for the release gate.
