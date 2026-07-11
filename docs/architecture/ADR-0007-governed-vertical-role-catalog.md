# ADR-0007: Governed Vertical Role Catalog on the Ability Spine

**Status:** Proposed  
**Date:** 2026-07-10  
**Owner:** Technical Lead / Architecture  
**Supersedes:** Draft “ADR-0012 Governed Vertical Agent Swarm Retrofit” (rejected numbering and shape)  
**Related:**  
`PROJECT_SPEC.md` (invariants 1–7),  
`docs/architecture/SYSTEM_ARCHITECTURE.md`,  
`docs/SAAS_ARCHITECTURE.md`,  
`docs/architecture/ADR-0001-authority-classification-doctrine.md`,  
`docs/architecture/ADR-0005-informed-autonomy-gate-policy.md`,  
`docs/product/ability-rollout-contract.md`,  
`docs/product/GTM_CAPABILITY_CATALOG.md`,  
`docs/product/mission-based-ai-core.md`

---

## 1. Context

### 1.1 Competitor pattern (Polsia)

[Polsia](https://github.com/PolsiaAI/Polsia) is an agent-first “run your business on autopilot” stack: nine (sometimes ten) scheduled agents, Celery Beat, DB task rows, and each agent invoking `claude -p ...` as a subprocess authenticated via host `~/.claude` OAuth. Auth is a single dashboard `API_KEY`. Schema is single-company (`company_config`), not multi-tenant. Safety is largely `SANDBOX_MODE` plus activity logs—not lease ownership, not OPA, not evidence contracts, not fail-closed policy per side effect.

Public snapshot observations (as of 2026-07-10): ~2 upload commits, README/layout claim `backend/app/agents/` while the published tree is incomplete relative to those claims (tests import `app.agents.*` that are not present as source paths in the public tree). Product surface is polished; governance substrate is thin or missing.

### 1.2 Ajenda position

Ajenda is **mission-based AI** with a governed runtime:

```text
Mission → plan/task graph → mission_bridge materialization/admission
→ ExecutionCoordinator (RuntimeGovernor + PolicyGuardian + queue)
→ WorkerLoop lease claim/start/run
→ TaskDispatcher → tool.invoke
→ ToolRuntimeAuthority → ActionRegistry → handler
→ EvidenceItem + lineage + audit + governance events
```

Declarative surfaces already exist and must not be reinvented:

| Existing surface | Role |
|---|---|
| `Capability` / `CapabilityAdapter` | Declarative contracts (no execution authority) |
| `AbilityManifest` + ability catalog | Rollout readiness contract |
| `ActionRegistry` + `backend/services/tools/*` | Registered handlers |
| `ExecutionCoordinator` | Queue admission with policy gates |
| `mission_bridge/*` | Plan/graph/materialize/admit/claim/start/run |
| `UserWorkforceAgent` / fleet | Mission-scoped workforce instances |
| `PolicyGuardian` + OPA PDP | Fail-closed policy |
| Evidence / outcome review / credentials | Runtime proof and external auth material |

### 1.3 Problem

Vertical business work (social, email, research, ads, finance, support, planning, code) is a legitimate product surface. Porting Polsia’s **agent swarm runtime** would re-center Ajenda on agents, duplicate admission, and invent illegal side-effect classes. We need the **product shape** of vertical roles without the **feral execution model**.

---

## 2. Decision

**Adopt a declarative Vertical Role Catalog that groups existing abilities/adapters into role bundles for mission planning. Do not introduce a parallel agent swarm runtime.**

### 2.1 Core rules (non-negotiable)

1. **Missions own outcomes.** Roles do not. Roles are catalogs and planning hints that help materialize governed task graphs.
2. **Every side-effecting action executes only on the existing authoritative path** (queue + lease + `ToolRuntimeAuthority` + handler + evidence). No Celery Beat autonomous loops. No raw subprocess LLM calls outside a governed action handler (and even then only if a future approved provider path exists—default is existing tool/provider adapters).
3. **Declarative records never grant execution authority** (PROJECT_SPEC invariant 6, ADR-0001).
4. **No second `ExecutionCoordinator`.** Admission remains `backend.services.execution_coordinator.ExecutionCoordinator` + `mission_bridge`.
5. **Side effects use only** `backend.services.tools.schemas.SideEffectClass`:  
   `none | internal_read | internal_write | external_read | external_write | external_send | external_publish`.  
   **Rejected:** `financial_mutation`, compound strings like `external_write + financial`. Financial risk is expressed via `risk_level`, `ComplianceCategory`, permissions, approval, and human review—not a new side-effect enum.
6. **No path under `backend/tools/`.** Handlers live under `backend/services/tools/` (and related ability registration), matching the codebase.
7. **ADR number is 0006**, continuing the architecture index after ADR-0005. Migration numbers are unrelated.

### 2.2 What we introduce

| Artifact | Authority class | Purpose |
|---|---|---|
| `VerticalRoleSpec` (catalog entry) | `declarative` | Stable `role_key`, display metadata, default risk, compliance hints, list of ability/action bindings |
| `VerticalRolePack` (versioned catalog) | `declarative` | Named pack (e.g. `vertical_swarm.v1`) grouping role specs |
| Pack installer (optional service) | `governed_mutation` (install only) | Seeds tenant-visible `Capability` / `CapabilityAdapter` rows and documents pack version; does not enqueue work |
| Mission / plan templates keyed by role | `declarative` → materialization via existing bridge | Produce `ExecutionTask` graphs with compliance metadata and action bindings |

### 2.3 What we explicitly reject

- New runtime package that reimplements admission (`services/agent_swarm/execution_coordinator.py`).
- Agent-first product model where nine autonomous agents “run the business” outside mission plans.
- Cross-tenant shared agent memory.
- Celery / external schedulers / Beat crons as execution authority.
- Host OAuth CLI (`~/.claude`) as multi-tenant credential model.
- Claiming “automatic EU AI Act / SB24-205 / LL144 / CAN-SPAM compliance” without per-action `compliance_category`, jurisdiction, metadata contracts, and tests.

### 2.4 Product framing

Polsia sells **agents on a schedule**.  
Ajenda sells **missions with governed work**.

Vertical roles are how operators (and later planners) **select capability bundles** for a mission—not how the runtime schedules autonomous personalities.

---

## 3. Vertical role catalog (authoritative mapping)

Pack id: `vertical_ops.v1`  
Schema: declarative only.

Side-effect column uses **canonical** classes. Primary binding lists **existing or planned action names**—not fantasy handlers.

| Role | `role_key` | Risk | Primary side effect | Permissions | Compliance default | Initial runtime binding | `enabled_by_default` |
|---|---|---|---|---|---|---|---|
| Orchestrator / planning lead | `vertical.orchestrator` | medium | `none` / plan materialization as `internal_write` via bridge | `mission:manage`, `execution:view` | `operational` | Mission plan + task graph templates only (no autonomous loop) | false |
| Business planning | `vertical.planning` | medium | `none` (recommendations); KPI persistence `internal_write` | `mission:manage` | `operational` | Draft recommendations via local/record actions first | false |
| Competitor research | `vertical.research` | low–high | `external_read` | `execution:queue` | `operational` | `provider.external_read` / research-capable GTM paths | false |
| Social media | `vertical.social` | high | draft `none`; publish `external_publish` | `execution:queue` | `consumer_interaction` when public | Existing `gtm.social_publish` + draft abilities | false |
| Email outreach | `vertical.email` | high | draft `none`; send `external_send` | `execution:queue` | `consumer_interaction` | Existing `gtm.email_draft` / `gtm.email_send` | false |
| Customer support | `vertical.support` | medium–high | read `external_read`; reply `external_send` | `execution:queue` | `consumer_interaction` | Email/check + draft reply first; send gated | false |
| Ads management | `vertical.ads` | critical | `external_write` | `execution:queue`, `billing:read` | `financial` | **Catalog only** until provider + idempotency + human review proof | false |
| Code generation | `vertical.code` | high | `external_write` | `execution:queue` | `operational` | **Catalog only** until GitHub/credential + PR evidence contract | false |
| Finance | `vertical.finance` | critical | `external_read` (sync); mutations `external_write` | `billing:manage`, `execution:queue` | `financial` | Stripe-adjacent read/sync first; mutations catalog-only + human review | false |

### 3.1 Mandatory fields per role binding (LAP contract)

Every role → action binding must declare:

- `action_name` registered or deferred with explicit non-goal
- `capability_name` / `capability_version` + `adapter_name` / `adapter_version`
- `side_effect_class` ∈ canonical enum
- `risk_level` ∈ `AbilityRiskLevel`
- `required_permissions` ⊆ `backend.auth.permissions.Permission`
- `approval_required`, `idempotency_required` (+ contract ref when true)
- `evidence_required` + non-empty `evidence_expectations` when evidence required
- `readback_required` or concrete `readback_deferred_reason`
- `compliance_category`, jurisdiction defaults, `requires_human_review` when risk ≥ high or category is employment/financial/healthcare/consumer
- `enabled_by_default=false` for high/critical and all external send/publish/write
- credential requirement when external provider material is needed

### 3.2 Compliance (honest scope)

`PolicyGuardian` already enforces supported categories/jurisdictions and selected metadata keys (e.g. EU technical doc ref, CO consequential disclosure, consumer AI disclosure). Role catalog **supplies** compliance defaults into task materialization metadata. It does **not** invent automatic multi-statute coverage. New statute profiles require PolicyGuardian tests + metadata contracts before being claimed in product language.

Informed autonomy (ADR-0005) still applies: tiered disclaimers and `side_effect_authorization` for real side effects—not approval theater.

---

## 4. Architecture placement

### 4.1 Preferred file layout (native)

```text
backend/services/abilities/
  vertical_role_catalog.py     # VerticalRoleSpec, VerticalRolePack, VERTICAL_OPS_PACK
  (existing) catalog.py        # ability manifests remain SoT for actions
  (existing) manifest.py

backend/services/vertical_ops/   # optional thin package
  pack_installer.py            # installs declarative capability/adapter seeds per tenant
  plan_templates.py            # maps role_key → mission plan / task graph fragments

backend/services/tools/          # handlers only here (extend GTM/etc.)
  # no backend/tools/agent_swarm/

# DO NOT CREATE
# backend/services/agent_swarm/execution_coordinator.py
# backend/domain/agent_role.py as a parallel execution model
# backend/domain/agent_pack.py that implies runtime authority
```

If domain Pydantic models are useful for validation, they must be **pure contracts** (like ability manifests), not SQLAlchemy execution tables, unless a later ADR adds persistence with explicit non-executing semantics.

### 4.2 Hooking points (strict)

| Stage | System of record |
|---|---|
| Mission intake | Existing mission creation |
| Role selection | Catalog lookup → plan/template choice |
| Plan / graph | Existing mission plan + task graph contracts |
| Materialization | `mission_bridge` materialization services |
| Admission | `ExecutionCoordinator.queue_task` + PolicyGuardian + RuntimeGovernor |
| Claim / start / run | `WorkerLoop` + lease + worker admission services |
| Execute | `TaskDispatcher` → `tool.invoke` → ActionRegistry |
| Evidence | Handler `ActionResult.evidence` + evidence persistence |
| Observability | Existing metrics/events; optional labels `role_key`, `pack_id`, `pack_version` on audit/governance payloads |
| Recovery | Existing lease recovery / dead-letter (invariant 4) |

### 4.3 Relationship to workforce agents

`UserWorkforceAgent` remains the **mission-scoped instance** of a role assignment (display name, status, fleet membership). The catalog’s `role_key` may appear in `metadata_json` / `role_name`. Workforce records do not execute tools.

### 4.4 PolicyGuardian extension point

Extend via **compliance profiles** referenced by role bindings (metadata keys, category, human review defaults)—not a new coordinator. Core guardian logic stays category/jurisdiction-driven; role catalog fills task fields before admission.

---

## 5. Phased delivery (Pride / UPG order)

### Phase A — Catalog + contracts (mergeable alone)

- `VerticalRoleSpec` / pack definition with full binding fields
- Contract tests for enum legality, permissions, high-risk defaults
- No new enqueue path

### Phase B — Bind first real roles (2–3)

Ship only where handlers already exist or can follow ability rollout contract:

1. Research / external read  
2. Email draft (send only with existing GTM gates + ADR-0005)  
3. Social draft / publish under existing GTM gates  

Proof: mission → admit → lease → evidence for one vertical mission template.

**Implementation (2026-07-10):**  
`backend/services/vertical_ops/plan_templates.py` + `template_service.py` provide Phase B templates (`vertical.research.v1`, `vertical.email.v1`, `vertical.social.v1`).  
`VerticalOpsTemplateService` builds plan/task-graph contracts, creates planned `ExecutionTask` rows with `tool.invoke` metadata, and queues **only** via existing `ExecutionCoordinator`. No parallel coordinator.  

**API surface:** `/v1/vertical-ops/templates`, `/v1/vertical-ops/missions`, apply/queue mission routes (`backend/api/routes/vertical_ops.py`).  

Unit/API proof: `tests/unit/services/test_vertical_ops_phase_b.py`, `tests/unit/api/test_vertical_ops_route.py`, `tests/contract/runtime/test_vertical_ops_execution_path_contract.py`.  

Runtime integration proof (research template): `tests/integration/runtime/test_vertical_ops_research_template_runtime_real.py` — apply_and_queue → claim/start → TaskDispatcher → lineage/evidence. Matrix row: **VO-01** in `docs/validation/live-runtime-matrix.md`.

### Phase C — High-risk expansion

Ads, finance mutations, code gen: catalog entries remain **disabled** until:

- provider + credentials  
- idempotency + readback  
- human review / outcome review path  
- integration + runtime matrix update  

**Implementation (2026-07-10):**  
Phase C templates `vertical.ads.v1`, `vertical.code.v1`, `vertical.finance.v1` are **plan-only** (`allows_runtime_queue=false`). They build mission plan + task graph from catalog-only role bindings, create **no** ExecutionTask rows, and **fail closed** on queue/apply_and_queue. No ads/SCM/billing handlers invented.  

Proof: `tests/unit/services/test_vertical_ops_phase_c.py`, API reject on `queue=true`. Matrix row: **VO-C1** (deferred runtime).

### Explicit non-goals for first merge

- Full nine-role handler fleet  
- Autonomous Beat-style multi-role loops  
- Parallel swarm orchestrator service  
- Port of Polsia prompt/agent classes as subprocess wrappers  

---

## 6. Consequences

### Positive

- Captures competitive product surface without importing competitor architecture debt  
- Keeps invariants 1–7 and ability rollout contract intact  
- Reuses GTM and tool spine already in tree  
- Clear multi-tenant credential model (existing credential runtime), not host CLI OAuth  

### Tradeoffs

- Less “magical 9 agents always-on” marketing; product must sell **missions and outcomes**  
- High-risk verticals stay catalog-only until real providers prove safe—slower feature checklist, safer SaaS  
- Requires discipline: pack installers must not quietly enqueue  

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| Catalog treated as execution grant | Ability rollout + ToolRuntimeAuthority fail-closed; tests |
| Parallel coordinator PR | This ADR forbids it; code review rejects name collision |
| Compliance overclaim | Product language limited to implemented PolicyGuardian profiles |
| Feature flag sprawl | Prefer pack/role `enabled` + existing adapter enablement; optional `VERTICAL_OPS_PACK_ENABLED` only for install surface |

---

## 7. Validation and proof

Before marking this ADR **Accepted** and before merge of Phase A/B code:

- `ruff check` / `ruff format --check` on touched paths  
- `mypy backend/` as applicable  
- `python scripts/validation/ability_rollout_contract_check.py` when manifests change  
- `python scripts/validation/contract_drift_check.py`  
- Unit/contract tests for pack validation (illegal side effects, permissions, default disabled high risk)  
- Phase B integration: vertical mission template → PolicyGuardian path → lease claim → evidence on complete/fail  
- Update `docs/validation/live-runtime-matrix.md` only for scenarios actually proven  

Runtime evidence overrides ADR prose for release decisions (invariant 7).

---

## 8. Rollback

- Disable pack install / tenant adapter enablement for vertical roles  
- Cancel in-flight missions via existing mission cancellation  
- No new runtime tables required for Phase A; revert is code + seed disable  
- If a later phase adds tables, migration reverse must leave no orphan execution authority  

---

## 9. Comparison note (why not copy Polsia)

| Dimension | Polsia pattern | Ajenda (this ADR) |
|---|---|---|
| Product center | Agents + schedules | Missions + outcomes |
| Execution | Celery + CLI subprocess | Queue + lease + ActionRegistry |
| Tenancy | Single company | RLS multi-tenant |
| Auth | Single API key | Principals, RBAC, credentials |
| Safety | Sandbox flag | Side-effect class + policy + evidence |
| Memory | Shared Chroma | Governed retrieval/promotion contracts |
| Proof | Activity log | Evidence, lineage, audit, runtime matrix |

Polsia is a useful **product checklist** (what verticals customers imagine). It is not a **runtime blueprint**.

---

## 10. Acceptance criteria for this ADR

This ADR is ready to flip from **Proposed** → **Accepted** when:

1. Indexed in `docs/architecture/ADR_INDEX.md`  
2. Phase A catalog lands with tests and no parallel coordinator  
3. At least one Phase B role has end-to-end runtime proof on the existing spine  
4. No doc claims automatic multi-statute compliance beyond PolicyGuardian coverage  

Until then: **Proposed**. Implementation follows UPG/LAP before any layer that admits or executes work.

---

## 11. References

- Polsia public repository: https://github.com/PolsiaAI/Polsia  
- Ajenda ability spine: `backend/services/abilities/`, `backend/services/tools/`, `backend/services/execution_coordinator.py`  
- Mission bridge: `backend/services/mission_bridge/`  
- Invariants: `PROJECT_SPEC.md` §3  
)
