# AJENDA-AI Evidence Lifecycle Policy

**Status:** Active  
**Effective date:** May 25, 2026  
**Owner:** Security/Governance + Runtime Validation  
**Last reviewed:** May 25, 2026  
**Source-of-truth precedence:** Implementation/tests/runtime proof > PROJECT_SPEC.md > architecture docs

---

## 1) Purpose

This policy defines the explicit lifecycle contract for tenant-owned evidence records. It standardizes how evidence is collected, validated, retained, superseded, and dispositioned while preserving tenant isolation and fail-closed governance.

---

## 2) Scope

This policy applies to:

- `EvidenceRecord` contract records and API payloads.
- mission-scoped evidence used by outcome review and release validation.
- retention and disposition behavior metadata used by governance checks.

This policy does **not** grant runtime dispatch authority; evidence remains declarative contract data.

---

## 3) Lifecycle states

Baseline states:

- `draft`: record created but not yet considered collected.
- `collected`: evidence captured and linked to a mission/task context.
- `verified`: evidence meets validation expectations for declared use.
- `rejected`: evidence is present but invalid/untrusted for decisions.
- `superseded`: newer evidence replaces this record for active decisions.

Additive governance states (backward-compatible):

- `retention_hold`: deletion/disposition prohibited pending legal or policy hold.
- `archived`: immutable historical record retained outside active review flows.
- `purged`: lifecycle disposition completed according to retention policy.

---

## 4) Retention classes and minimum expectations

Every production evidence stream should define a retention class in policy metadata:

- `ephemeral`: short-lived operational artifacts.
- `standard`: default tenant evidence retention.
- `regulated`: compliance/legal critical evidence with strict controls.

Minimum posture:

- purge decisions must be auditable.
- retention extensions must be explicit.
- legal/compliance holds must map to `retention_hold`.

---

## 5) Provenance and confidence posture

Evidence intended for policy, review, or release gates should include:

- provenance metadata (collector/source/path/time).
- confidence score where available.
- trust signal metadata when confidence alone is insufficient.

When provenance is missing or confidence is below policy floor, systems should fail closed for high-risk gates and route to review.

---

## 6) Invariants

- tenant isolation is mandatory for all evidence access/mutation.
- evidence lifecycle mutation must be explicit and auditable.
- no evidence record may imply runtime execution authority.
- `purged` records must not be treated as active decision inputs.

---

## 7) Rollout and compatibility

- additive-first: new lifecycle statuses are optional and non-breaking.
- existing clients remain valid when using baseline statuses.
- enforcement hardening should be feature-flagged before mandatory mode.
