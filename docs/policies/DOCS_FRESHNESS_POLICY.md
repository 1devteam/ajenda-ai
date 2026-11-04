# AJENDA-AI Documentation Freshness Policy

**Status:** Active  
**Effective date:** May 23, 2026  
**Owner:** Architecture + Runtime Governance
**Last reviewed:** November 2, 2026
**Source-of-truth precedence:** Implementation/tests/runtime proof > PROJECT_SPEC.md > architecture docs

---

## 1) Purpose

This policy prevents documentation drift between:

- canonical specification (`PROJECT_SPEC.md`),
- architecture guidance (README + architecture docs + ADRs),
- implementation truth (code/tests/migrations),
- runtime-proof evidence (validation matrix + artifacts).

Freshness is a release-safety control, not only a writing quality standard.

---

## 2) Scope

This policy applies to all canonical and operational docs that influence implementation or release decisions.

### Tier-1 canonical docs (strictest SLA)

- `PROJECT_SPEC.md`
- `README.md`
- `docs/README.md`
- `docs/architecture/SYSTEM_ARCHITECTURE.md`
- `docs/architecture/ADR_INDEX.md`
- `docs/deployment/production-env-contract.md`
- `docs/validation/live-runtime-matrix.md`
- `docs/validation/live-runtime-proof-release-gate.md`

### Tier-2 architecture and policy docs

- `docs/SAAS_ARCHITECTURE.md`
- `docs/product/mission-based-ai-core.md`
- `docs/deployment/production-env-contract.md`
- `docs/policies/*.md`
- `docs/architecture/ADR-*.md`

### Tier-3 state and reporting docs

- dated assessments, checkpoints, and progress reports
- audit, remediation, and planning records whose stated status is historical,
  superseded, proposed, or point-in-time

---

## 3) Freshness SLAs

### Tier-1 SLA

- Must be reviewed on every release cycle.
- Any PR that changes runtime authority, schema contracts, readiness semantics, or release-gating rules must update impacted Tier-1 docs in the same PR (or linked immediately-following PR with explicit dependency note).

### Tier-2 SLA

- Must be reviewed at least every 30 days.
- Must be updated when their normative claims change.

### Tier-3 SLA

- Must display explicit date/status banners.
- Must be reviewed at least every 60 days or marked historical/archived.

---

## 4) Ownership and accountability

## Required owners by domain

- **Runtime authority + readiness docs:** Runtime/Platform owner
- **Schema and migration docs:** Data/Platform owner
- **Policy/compliance docs:** Security/Governance owner
- **Validation and release-gating docs:** QA/Validation owner
- **Product mission docs:** Product/Architecture owner

Ownership may be shared, but every Tier-1/Tier-2 document must have at least one accountable reviewer per cycle.

---

## 5) Required document metadata

Tier-1 and Tier-2 docs should include near-header metadata:

- status (active/proposed/deprecated/superseded)
- last reviewed date
- primary owner
- source-of-truth precedence note where relevant

Tier-3 docs must include:

- publication date
- branch/context snapshot
- freshness warning if older than SLA

---

## 6) Drift classes and handling

### Drift class D1 — Terminology drift

Example: route/contract names differ across docs.

Action: patch docs in next PR.

### Drift class D2 — Behavioral drift

Example: docs describe behavior no longer true in tests/implementation.

Action: hotfix docs or code in same workstream before release.

### Drift class D3 — Release-critical drift

Example: release-gating docs contradict validation runner behavior.

Action: block promotion until reconciled.

---

## 7) CI and enforcement model

### Current automated enforcement

The repository currently runs a limited drift sentinel at
`scripts/validation/contract_drift_check.py`. It checks authority-ledger shape,
some README route-family parity, referenced proof paths, and the presence/format
of this policy's review metadata. It may emit warnings for documentation drift;
it does **not** prove every prose claim is current, does not independently
validate every review date against the SLA, and does not convert a green result
into runtime or deployment proof.

Dedicated tests also guard selected ADR/index and deployment/runbook contracts.
Those checks are intentionally narrow. Reviewers remain responsible for tracing
claims to implementation, migration, configuration, and observed proof.

### Intended enforcement progression

1. **Current baseline:** targeted contract checks plus human source review.
2. **Future soft fail:** fail Tier-1 omissions and machine-detectable stale
   metadata once a complete, reviewed document inventory exists.
3. **Future hard fail:** block promotion for machine-detectable Tier-1/D3
   contradictions with an approved exception workflow.

Do not claim either future stage is active until its CI implementation and
failure behavior are themselves proven.

---

## 8) PR requirements

For PRs affecting runtime behavior/contracts/policy:

- Include a “Docs Impact” section in PR body:
  - affected docs,
  - unchanged-but-reviewed docs,
  - deferred docs with reason and follow-up issue.

For docs-only PRs:

- state drift class addressed (D1/D2/D3),
- include links to related implementation/test truth where applicable.

---

## 9) Exception policy

Temporary exceptions are allowed only when:

- production incident response requires immediate code change,
- documentation updates are queued in a follow-up PR within 24 hours,
- release owner approves exception in PR notes.

No exception allowed for unresolved D3 drift at promotion time.

---

## 10) Compliance review cadence

- Weekly: quick Tier-1 consistency scan.
- Per release: full Tier-1 + impacted Tier-2 reconciliation.
- Monthly: Tier-2 scheduled review.
- Bi-monthly: Tier-3 archive/refresh pass.

---

## 11) Definition of done for freshness governance

Freshness governance is considered operational when:

1. Tier-1 docs have explicit owners and review metadata.
2. Drift sentinel runs in CI and surfaces SLA violations.
3. PR template includes docs-impact requirements.
4. D3 drift blocks promotion.

Until the intended stages are implemented, this policy remains binding review
conduct with deliberately limited automated enforcement.
