# Tool & Ability Phase Priorities — Informed Autonomy Over Approval Theater

**Status:** Active policy (documentation-first; implementation in upcoming tool/ability phases)  
**Last updated:** 2026-06-23  
**Owner:** Product + Runtime architecture  
**Precedence:** Implementation/tests/runtime proof > `PROJECT_SPEC.md` > this document

---

## 1) Purpose

Ajenda-AI has a strong governed runtime (queue, lease, `tool.invoke`, evidence, tenant isolation). The **next product phases are tools and abilities** — real work strangers will pay for.

This document records a deliberate **priority shift**:

1. Ship **true tools and abilities** (non-simulated outcomes where credentials exist).
2. **Roll back gates and human-in-the-loop checks that sit in the wrong places** — bureaucracy on low-risk or read-only work, fake approval metadata, and role gates that block the actual tenant owner.
3. Replace removed gates with **recorded user disclaimers (informed autonomy)** on higher-risk paths, not silent waiver of safety.

SaaS onboarding, OIDC, billing, and account APIs are **infrastructure**, not the finish line. They stay required; they are no longer the primary roadmap.

---

## 2) Current problem (code-aligned)

| Symptom | Why it blocks product |
|--------|------------------------|
| Most registered actions use **local/simulated proof providers** | Customers can launch tasks but do not get durable external value |
| **Guardian / `tenant_admin` role** required for some GTM launches | OIDC tenant owners are the principal; org-style approval is misplaced for solo workspaces |
| **`approved_by: "ability-runtime-ui"`** auto-filled on launch | Approval theater — no real human decision |
| **`requires_human_review` / `pending_review`** on ability-runtime high-risk pilot | Blocks autonomy without a meaningful review UX (no draft preview → confirm send) |
| **Plan gates** (`ability_runtime`, `gtm`) before read/draft value | Paywall before proof of usefulness |
| **Per-launch ephemeral capability/adapter rows** for low-risk proofs | Ceremony without proportional safety benefit |

**What is not the problem:** tenant isolation, idempotency on external mutations, credential scoping, evidence on every action, simulated fail-closed when credentials are absent. Those stay.

---

## 3) Architectural decision (summary)

**Informed autonomy replaces misplaced gates.**

- **Gate** = hard block until a role, policy state, or admin path approves.
- **Disclaimer** = explicit, logged user acknowledgment of risk and responsibility before execution proceeds.

Disclaimers promote autonomy **only when**:

- acknowledgment is **per-action or per-tier**, not buried in generic ToS;
- `principal_id`, `disclaimer_id`, `disclaimer_text_hash`, and `accepted_at` are persisted in **audit + evidence provenance**;
- technical controls (tenant scope, quotas, idempotency, credentials) remain enforced.

See [`ADR-0005-informed-autonomy-gate-policy.md`](../architecture/ADR-0005-informed-autonomy-gate-policy.md).

---

## 4) Tiered autonomy model (target)

Actions are classified by **effective side effect**, not by manifest paperwork alone.

| Tier | Examples | Autonomy policy | Human involvement |
|------|----------|-----------------|-------------------|
| **0 — Local / read** | `sales.qualify`, `calendar.read`, `record.search`, `gtm.lead_enrich` | No disclaimer; no guardian gate; free tier OK for pilot | None required |
| **1 — Draft / generate** | `gtm.email_draft`, `sales.draft_followup` | Light session disclaimer: AI output must be reviewed | User reviews output in UI; no `pending_review` block |
| **2 — Credentialed external read** | `gtm.email_check`, `sales.research` with credential | Action disclaimer + credential connect | User connects account + accepts read scope |
| **3 — External write / send / publish** | `gtm.email_send`, `gtm.crm_upsert`, `webhook.dispatch` | Strong per-action disclaimer; **idempotency_key required** | User confirms after seeing draft (UI confirm = human loop); no guardian role for tenant owner |

### Roll back (upcoming phases)

- Guardian role requirement for **tenant owner** principals on Tier 2–3 when valid `autonomy_acknowledgment` is present.
- `requires_human_review` → `pending_review` **blocking** on ability-runtime launches when UI has already shown disclaimer + confirm.
- Plan paywall on **Tier 0–1** (keep monetization on Tier 3 volume/features if desired).
- Ephemeral capability/adapter generation for **Tier 0–1** pilot actions (use stable pilot records).
- Fake `approved_by: "ability-runtime-ui"` as the sole authority story — replace with `autonomy:{principal_id}` in `side_effect_authorization`.

### Never roll back

- Tenant isolation and RLS.
- `execution_constraints.side_effect_authorization` lane for side-effecting actions (repurpose `approved_by`, do not delete envelope).
- Idempotency on external write/send/publish.
- Credential reference + runtime credential scoping.
- Evidence on every successful action.
- Simulated fail-closed when credentials are missing (do not fake external success).
- Rate limits and quota enforcement (tighten on Tier 3 if autonomy widens).

---

## 5) Upcoming implementation phases

Phases are ordered by **customer value**, not remediation bundle number.

### Phase 1 — Real tool outcomes (highest priority)

**Goal:** At least one non-simulated external or LLM-backed outcome on the governed runtime path.

- Credential connect for one provider (e.g. Gmail read or send).
- Real network egress path with evidence showing `real: true` (not `status: simulated`).
- Integration test proving launch → worker → evidence with acknowledgment + idempotency where required.

**Exit criteria:** Stranger completes OIDC session, runs one Tier 1 or Tier 2 action, sees inspectable evidence of real work.

### Phase 2 — Customer ability surface

**Goal:** `/tasks` (and dashboard CTA) match dev-console depth for allowed tiers.

- List actions, launch with input, poll status/lineage/evidence.
- Disclaimer modal before Tier 2–3 launch.
- OIDC bearer auth on ability-runtime (integration test).

**Exit criteria:** No `/dev` API key required for core ability proofs.

### Phase 3 — Informed autonomy enforcement (this policy in code)

**Goal:** Implement disclaimer catalog + `autonomy_acknowledgment` envelope.

- Feature flag: `AJENDA_AUTONOMY_DISCLAIMER_MODE` (`off` | `pilot` | `enforce`).
- `AbilityTaskCreate.autonomy_acknowledgment` (or equivalent) with `disclaimer_id`, hash, timestamp.
- Route changes in `backend/api/routes/ability_runtime.py`: skip guardian gate when flag + valid acknowledgment.
- Audit event: `autonomy_disclaimer_accepted`.
- Update `docs/contracts/authority-ledger.v1.yaml` and validation matrix rows.

**Exit criteria:** Without acknowledgment → 400 on Tier 3; with acknowledgment + idempotency + credential → 202 queued; audit row exists.

### Phase 4 — Mission bridge for customers (later)

**Goal:** Mission intake → plan → queue → tools in customer UI.

- Defer until Phase 1–3 prove single-action value.
- Do not let mission graph UX delay first real tool.

---

## 6) Disclaimer catalog (planned contract)

Stable IDs, versioned text, mapped to tiers and actions. Stored under repo control for hash verification.

| `disclaimer_id` | Tier | Actions | Intent |
|-----------------|------|---------|--------|
| `autonomy.session.ai_review.v1` | 1 | draft family | User responsible for reviewing AI output |
| `autonomy.external_read.v1` | 2 | credentialed reads | User authorizes read via connected credential |
| `autonomy.external_send.v1` | 3 | `gtm.email_send`, etc. | User accepts responsibility for send/content/recipients |
| `autonomy.external_write.v1` | 3 | `gtm.crm_upsert`, `record.write`, … | User accepts responsibility for external mutation |

Implementation file (planned): `docs/product/autonomy-disclaimer-catalog.v1.yaml`.

---

## 7) Runtime metadata shape (planned)

Additive to existing `execution_constraints`; does not bypass `ToolRuntimeAuthority`.

```json
{
  "execution_constraints": {
    "autonomy_acknowledgment": {
      "schema_version": 1,
      "disclaimer_id": "autonomy.external_send.v1",
      "disclaimer_text_hash": "sha256:…",
      "accepted_at": "2026-06-23T12:00:00Z",
      "principal_id": "member-uuid",
      "action": "gtm.email_send",
      "side_effect_class": "external_send"
    },
    "side_effect_authorization": {
      "schema_version": 1,
      "allowed_actions": ["gtm.email_send"],
      "approved_by": "autonomy:member-uuid",
      "reason": "User accepted disclaimer autonomy.external_send.v1"
    }
  }
}
```

---

## 8) Relationship to existing docs

| Document | Relationship |
|----------|--------------|
| [`ability-rollout-contract.md`](ability-rollout-contract.md) | Still governs how new actions are registered; tier policy decides **which approval rules apply at launch** |
| [`GTM_SELF_SELLING_ARCHITECTURE.md`](GTM_SELF_SELLING_ARCHITECTURE.md) | Outbound families unchanged; **approval checkpoint** may be UI confirm + disclaimer instead of guardian role for tenant owners |
| [`OUTBOUND_COMMUNICATION_POLICY.md`](../policies/OUTBOUND_COMMUNICATION_POLICY.md) | Still applies; disclaimers do not replace compliance obligations |
| [`authority-ledger.v1.yaml`](../contracts/authority-ledger.v1.yaml) | **Must be updated** when Phase 3 ships — ledger currently describes guardian pilot as mandatory |
| [`REMEDIATION_EXECUTION_PLAN_2026-05-23.md`](../REMEDIATION_EXECUTION_PLAN_2026-05-23.md) | Historical; Bundle 6.3 intent (one real guarded path) **superseded in priority** by Phases 1–3 here |

---

## 9) Non-goals (this policy does not authorize)

- Autonomous send/publish **without** user acknowledgment on Tier 3.
- Removing idempotency or tenant isolation for velocity.
- Declaring simulated actions as successful external outcomes.
- Bypassing `TaskDispatcher` / `WorkerRuntimeService` / `tool.invoke`.
- Legal immunity via disclaimer text (operational consent ≠ regulatory compliance).

---

## 10) Verification impact (when implemented)

Each phase must add or update:

- Unit tests for acknowledgment validation and gate skip logic under feature flag.
- Contract tests on `/v1/ability-runtime/tasks` denial/accept paths.
- Integration test: OIDC tenant owner launches Tier 3 with disclaimer + idempotency + credential.
- Authority ledger + live-runtime-matrix row updates.
- Frontend test or manual proof checklist for disclaimer modal.

Until Phase 3 code exists, this document is **policy only** — existing guardian and `pending_review` behavior remains in force.

---

## 11) Decision log

| Date | Decision |
|------|----------|
| 2026-06-23 | Product roadmap priority shifts to tools/abilities; misplaced gates to be replaced by tiered informed autonomy; SaaS path treated as foundation complete for staging |