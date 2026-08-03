# ADR-0008: Mission Composition Engine

- **Status:** Accepted
- **Date:** 2026-07-19
- **Updated:** 2026-08-03
- **Owner:** AJENDA-AI Architecture Team
- **Related:** ADR-0001, ADR-0005, ADR-0006, ADR-0007, ADR-0010, `docs/product/mission-runtime-architecture-map.md`, `docs/product/mission-based-ai-core.md`

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
Raw instruction (frontend input; backend audit only after submit)
  → local LLM interpretation (strict schema; untrusted candidate)
  → deterministic grounding/readiness validation
  → MissionIntent (canonical outcome IDs + structured fields + fingerprint)
  → BusinessJob routing (IDs only)
  → CapabilityResolver (registry + manifest + charter + connections)
  → MissionCompositionRecord (proposal; durable history when DB present)
  → User reviews only the interpreted wording and acknowledges exact fingerprint
  → Confirm → deterministic revalidation → mission intake + plan + task graph
  → Existing staged runtime admission (explicit, separate)
```

### Authority boundaries

| Surface | Authority class | Must not |
|---|---|---|
| `POST /v1/missions/compose` | `read_model` | Create tasks, queue, leases, provider side effects |
| Confirm composition | `governed_mutation` | Queue, materialize runtime tasks, invoke tools |
| Runtime queue admission | `runtime_authoritative` | Remain the only canonical enqueue path |
| Local mission LLM | candidate generation only | Select abilities/tools, grant authority, approve, queue, or execute |

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
12. **Local LLM replacement boundary:** ADR-0010 replaces the spelling/fuzzy/phrase interpreter. Structured output remains untrusted until deterministic schema, grounding, readiness, governance, and compiler checks pass.
13. **Exact semantic review:** the client confirms the server proposal ID plus interpretation fingerprint. Confirmation and compile reuse the stored intent and never call the model again.

### Structured MissionIntent (interpreter v8 local-LLM replacement)

Material fields include:

- `requested_outcomes` — canonical IDs (`research_prospects`, `prepare_outreach`, `send_outreach`, …)
- `requested_quantity` + provenance
- `send_policy` (`allow` | `forbid` | `conditional` | `unknown` + condition)
- `target_entities` (with provenance/confidence)
- `interpreted_clauses` / `unmatched_material_clauses` / `coverage_score`
- `interpretation_evidence`
- `ambiguity` — restatement requirements (field + full-mission text + reason)

### Proposal durability

- The in-process cache supports non-authoritative reads and local no-DB tests. Confirmation always bypasses it.
- API proposals are persisted to `mission_composition_proposals` (migration `0035_composition_proposals`) for audit, supersession, backend-owned restatement-loop escalation, and confirmation. Compose fails closed if the durable write fails.
- Confirmation locks the tenant-scoped proposal row until its receipt is committed, making confirmation proposal-idempotent across workers and retry keys.
- History rows are declarative only and **never** grant execution authority.
- Original wording remains only in the tenant-scoped proposal audit row; browser-visible mission intake stores the confirmed interpretation and sanitized intent.
- Confirm distrusts client ability selections / ready flags and reruns only deterministic governance from the stored, fingerprinted intent. It never reinterprets the instruction.

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

- Confirm accepts only proposal identity, the displayed interpretation fingerprint, explicit acknowledgement, and an idempotency key; full client composition bodies are rejected.
- New compose requests require the configured local interpreter endpoint; failure is visible and fail-closed with no legacy parser fallback.
- Full auto-queue on confirm remains deferred — queue admission stays the runtime authority.

## Verification

- Unit: strict model schema/transport/grounding, canonical intent, send policy, restatement, coverage, job routing, capability resolver, and plan/graph compiler.
- Contract: compose creates no runtime state and does not return raw instruction/full proposal state; fingerprinted confirmation creates intake/plan/graph only and does not rerun the model.
- Migration: head includes `0035_composition_proposals`; round-trip green.
- Frontend: Missions review echoes only interpreted wording plus every execution-relevant derived detail, requires explicit acknowledgement or cancel/retry, and exposes no ability selectors.
- Live runtime proof: CI / staging proof on the composition + credentials path as configured for the release gate.
