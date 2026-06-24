# ADR-0005: Informed Autonomy Gate Policy

**Status:** Accepted (policy); implementation pending tool/ability phases  
**Date:** 2026-06-23  
**Supersedes:** None (narrows interpretation of ADR-0001 for product-phase gates)

---

## Context

Ajenda-AI enforces runtime authority through queue-backed `tool.invoke`, side-effect classification, capability validation, and human review paths (`requires_human_review`, guardian roles, `pending_review`).

That discipline is correct for a governed agent platform. However, as of 2026-06-23:

- Many exposed actions still execute against **local or simulated providers**, so heavy approval gates protect little real-world risk.
- **Tenant owners authenticating via OIDC** are blocked by **guardian/org-style roles** designed for multi-operator tenants.
- Ability-runtime launches auto-fill `approved_by: "ability-runtime-ui"`, which is **approval theater** — metadata without a human decision.
- **`pending_review`** without a draft-preview UX blocks autonomy without providing meaningful oversight.

Upcoming roadmap priority is **tools and abilities** (real outcomes), not additional SaaS or governance scaffolding.

---

## Decision

Adopt a **tiered informed-autonomy policy**:

1. **Classify actions by effective side effect** (Tiers 0–3). See [`TOOL_AND_ABILITY_PHASE_PRIORITIES.md`](../product/TOOL_AND_ABILITY_PHASE_PRIORITIES.md).

2. **Roll back misplaced gates** in implementation phases:
   - Guardian role requirements for tenant-owner principals when a valid `autonomy_acknowledgment` is recorded.
   - `pending_review` blocking on ability-runtime when the customer UI has already presented disclaimer + explicit confirm for that launch.
   - Plan/feature gates on Tier 0–1 read and draft actions during product pilot.
   - Per-launch ephemeral capability/adapter ceremony for Tier 0–1 pilot actions.

3. **Replace rolled-back gates with recorded disclaimers** on Tier 2–3:
   - Versioned `disclaimer_id` + `disclaimer_text_hash` + `accepted_at` + `principal_id`.
   - Persisted in audit and evidence provenance.
   - `side_effect_authorization.approved_by` set to `autonomy:{principal_id}` with reason referencing disclaimer id.

4. **Keep non-negotiable controls** unchanged:
   - Tenant isolation, credential scoping, idempotency on external mutations, evidence requirements, quota/rate limits, simulated fail-closed without credentials, canonical `tool.invoke` runtime path.

5. **Feature-flag rollout:** `AJENDA_AUTONOMY_DISCLAIMER_MODE` (`off` | `pilot` | `enforce`). Default `off` until Phase 3 tests pass.

---

## Consequences

### Positive

- Tenant owners gain **real autonomy** on their workspace without fake UI approval strings.
- Engineering focus shifts to **real providers and customer ability UX**.
- Human involvement moves to **high-signal moments** (review draft → confirm send) instead of policy states that users never see.
- Audit trail remains defensible: explicit consent per risky action.

### Negative / risks

- Disclaimers do not eliminate regulatory or platform abuse liability; quotas and content policy remain necessary.
- Widening autonomy without shipping real tools first would expose users to **simulated-success confusion** — Phase 1 (real outcomes) must precede or accompany gate rollback.
- Authority ledger and GTM pilot contracts must be updated when code ships; until then, code and ledger may temporarily diverge (documented in phase plan).

---

## Verification impact

When implemented:

- Unit: acknowledgment validator, feature-flag gate skip, denial without acknowledgment on Tier 3.
- Contract: `/v1/ability-runtime/tasks` request/response for autonomy paths.
- Integration: OIDC owner launch with disclaimer + idempotency + credential; audit row present.
- Docs: update `authority-ledger.v1.yaml`, `live-runtime-matrix.md`, and ability-rollout notes.

---

## Rollback strategy

1. Set `AJENDA_AUTONOMY_DISCLAIMER_MODE=off` — restores guardian and `pending_review` behavior.
2. No schema destruction; `autonomy_acknowledgment` keys are additive and inert when flag is off.
3. Re-enable plan gates via existing quota feature flags.

---

## References

- [`docs/product/TOOL_AND_ABILITY_PHASE_PRIORITIES.md`](../product/TOOL_AND_ABILITY_PHASE_PRIORITIES.md)
- [ADR-0001: Authority Classification Doctrine](./ADR-0001-authority-classification-doctrine.md)
- [`docs/product/ability-rollout-contract.md`](../product/ability-rollout-contract.md)
- [`backend/api/routes/ability_runtime.py`](../../backend/api/routes/ability_runtime.py)