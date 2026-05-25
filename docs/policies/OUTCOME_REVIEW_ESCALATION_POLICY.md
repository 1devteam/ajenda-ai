# AJENDA-AI Outcome Review Escalation Policy

**Status:** Active  
**Effective date:** May 25, 2026  
**Owner:** Security/Governance + Product/Architecture  
**Last reviewed:** May 25, 2026  
**Source-of-truth precedence:** Implementation/tests/runtime proof > PROJECT_SPEC.md > architecture docs

---

## 1) Purpose

This policy defines explicit escalation semantics for outcome review records so incomplete or high-risk conclusions are routed deterministically for additional review.

---

## 2) Scope

Applies to:

- outcome review lifecycle/status updates.
- human-approval pathways.
- escalation-trigger conditions tied to confidence, provenance, and unresolved gaps.

Does not grant execution authority or bypass queue/lease/runtime controls.

---

## 3) Review status model

Baseline statuses:

- `draft`
- `in_review`
- `completed`
- `superseded`

Additive escalation statuses (backward-compatible):

- `escalated`: review requires explicit higher-trust actor or policy decision.
- `archived`: immutable historical record outside active workflows.

---

## 4) Human approval model

Baseline statuses:

- `not_required`
- `pending`
- `approved`
- `rejected`

Additive escalation status:

- `escalated`: approval must be resolved by elevated reviewer or governance body.

---

## 5) Escalation triggers

Escalation should be considered when one or more are true:

- review decision is `needs_human_review`.
- unresolved high-severity gaps remain.
- confidence falls below configured floor for declared risk class.
- evidence provenance is incomplete for high-risk outcomes.
- policy/compliance context requires explicit approver role.

---

## 6) Required controls

- transitions into escalation states must emit audit/governance evidence.
- escalation resolution must be explicit, not inferred.
- superseded or archived records must not silently become active.
- multi-tenant boundaries remain fail-closed.

---

## 7) Compatibility and rollout

- new statuses are additive and optional by default.
- legacy clients may continue baseline status values.
- stricter transition enforcement belongs to gated follow-up bundle work.
