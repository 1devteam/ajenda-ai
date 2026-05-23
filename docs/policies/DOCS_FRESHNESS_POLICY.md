# AJENDA-AI Documentation Freshness Policy

**Status:** Active  
**Effective date:** May 23, 2026  
**Owner:** Architecture + Runtime Governance
**Last reviewed:** May 23, 2026
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
- `docs/architecture/ADR_INDEX.md`
- `docs/validation/live-runtime-matrix.md`
- `docs/validation/live-runtime-proof-release-gate.md`

### Tier-2 architecture and policy docs

- `docs/SAAS_ARCHITECTURE.md`
- `docs/product/mission-based-ai-core.md`
- `docs/deployment/production-env-contract.md`
- `docs/policies/*.md`
- `docs/architecture/ADR-*.md`

### Tier-3 state and reporting docs

- `docs/PROJECT_STATE_REPORT.md`
- dated assessments, checkpoints, and progress reports

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

Enforcement progression:

1. **Phase A (warn mode):** detect and report drift indicators in CI output.
2. **Phase B (soft fail):** fail PRs for Tier-1 drift and stale Tier-1 review dates.
3. **Phase C (hard fail):** fail PRs for Tier-1 contradictions and D3 drift indicators.

Minimum checks expected from drift sentinel tooling:

- canonical doc presence (`PROJECT_SPEC.md`, Tier-1 files),
- route inventory parity (README/contract docs vs router registry),
- stale-date detection vs SLA thresholds,
- release-gate row references for changed runtime contracts.

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

Until then, this policy is mandatory guidance with progressive enforcement rollout.
