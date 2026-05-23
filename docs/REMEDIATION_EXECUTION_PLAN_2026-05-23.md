# AJENDA-AI Remediation Execution Plan (Schema-Aligned, Safe-PR Bundles)

## Objective

Deliver a phased, low-regression remediation plan that resolves the identified cons/tradeoffs and P0/P1/P2 gaps while preserving existing runtime authority contracts, tenant isolation, queue/lease safety, and current schema semantics.

This plan is designed so each PR bundle is independently mergeable, testable, and reversible.

---

## Non-negotiable guardrails (applies to every PR)

1. **No authority-boundary drift**
   - Declarative contract layers must remain declarative unless a specific PR explicitly upgrades authority class and adds tests + validation proof.
2. **Schema compatibility first**
   - Prefer additive fields and backward-compatible enums.
   - No destructive migration in the same PR that introduces new behavior.
3. **Proof before promotion**
   - Each behavioral PR must add/adjust unit + contract tests and, where applicable, validation matrix rows.
4. **Tenant isolation and auth invariants must hold**
   - Every new route/service path must enforce tenant/auth envelope and fail-closed behavior.
5. **Feature flags for high-risk functionality**
   - New runtime-affecting capabilities (especially GTM automation) ship behind explicit flags.

---

## Issue-to-workstream mapping

### Workstream A — Canonical spec + drift control
Addresses:
- P0.1 missing `PROJECT_SPEC.md`
- P1.4 cross-document freshness governance
- README drift-prone alignment risks

### Workstream B — Authority clarity + operator cues
Addresses:
- P0.2 declarative contract misuse risk
- Misaligned logic risks (metadata vs execution authority)
- Onboarding tax + complexity overhead

### Workstream C — Readiness hardening
Addresses:
- P0.3 readiness semantics precision
- Runtime truth consistency with docs/validation

### Workstream D — Governance lifecycle explicitness
Addresses:
- P1.6 evidence/outcome lifecycle policy completeness
- Policy clarity for escalation and retention

### Workstream E — Explainability + reliability surfaces
Addresses:
- P2.7 mission explainability
- P2.9 tenant-facing reliability posture

### Workstream F — Economic observability
Addresses:
- P2.8 mission economics/cost governance

---

## Safe PR bundle plan (ordered)

## Bundle 0 (Docs foundation, zero runtime risk)

**Goal:** Establish canonical spec and decision records before runtime changes.

**PR 0.1 — Create canonical spec skeleton**
- Add `PROJECT_SPEC.md` at repo root.
- Include:
  - authority model by layer
  - mission contract classes
  - schema compatibility policy
  - release-gate policy
  - GTM mission scope and non-goals
- Update README “source-of-truth docs” section to include `PROJECT_SPEC.md`.

**PR 0.2 — Add ADR-style architecture index**
- Add `docs/architecture/ADR_INDEX.md`.
- Add first ADRs:
  - authority classification doctrine
  - schema evolution strategy
  - readiness semantics doctrine

**PR 0.3 — Add docs freshness policy**
- Add `docs/policies/DOCS_FRESHNESS_POLICY.md` with date thresholds and ownership.

**Why this bundle is safe:** docs-only, no runtime changes.

---

## Bundle 1 (Authority map + drift sentinel, low risk)

**Goal:** Remove ambiguity between declarative vs executable behavior.

**PR 1.1 — Contract Authority Ledger v1**
- Add `docs/contracts/authority-ledger.v1.yaml`.
- For each major endpoint/metadata contract, define:
  - authority class (`declarative`, `read_model`, `governed_mutation`, `runtime_authoritative`)
  - allowed side effects
  - forbidden side effects
  - required tests/proofs

**PR 1.2 — CI drift sentinel (read-only checker)**
- Add script `scripts/validation/contract_drift_check.py`.
- Checks:
  - Ledger entries map to real routes.
  - README route inventory matches router registry.
  - Dated docs exceed freshness threshold -> warning/fail policy.

**PR 1.3 — Operator UX contract labels (API response metadata)**
- Add non-breaking response metadata in mission bridge read endpoints:
  - `authority_class`
  - `side_effect_class`
  - `does_not_execute_runtime_work` boolean
- This is additive response shape only.

**Why this bundle is safe:** additive docs/checkers + additive response metadata; no state transition changes.

---

## Bundle 2 (Readiness hardening, medium risk)

**Goal:** Align readiness semantics with explicit dependency truth.

**PR 2.1 — Readiness service contract**
- Introduce explicit readiness evaluator service (DB + configured queue checks).
- Keep `/health` lightweight, preserve existing surface.
- Ensure sanitized failure payloads.

**PR 2.2 — Route-level readiness response normalization**
- Standardize `/readiness` and `/v1/system/readiness` payload contract.
- Include dependency states and non-sensitive failure reasons.

**PR 2.3 — Tests + validation rows**
- Add/expand:
  - unit tests for evaluator behavior
  - contract tests for readiness payload shape
  - validation matrix rows proving DB/queue dependency truth

**Why this bundle is safe:** isolated to readiness semantics, no task execution path modifications.

---

## Bundle 3 (Lifecycle governance explicitness, medium risk)

**Goal:** Make evidence/outcome lifecycle policies operationally explicit.

**PR 3.1 — Policy docs + enums (additive)**
- Add `docs/policies/EVIDENCE_LIFECYCLE_POLICY.md`.
- Add `docs/policies/OUTCOME_REVIEW_ESCALATION_POLICY.md`.
- If needed, add additive enum values with backward-compatible defaults.

**PR 3.2 — Service-level enforcement checks (non-breaking defaults)**
- Add validation guards for:
  - retention class presence
  - escalation state transitions
  - provenance confidence floor checks where policy requires
- Default to permissive when new fields absent unless feature flag is enabled.

**PR 3.3 — Test coverage**
- Unit + contract tests for policy enforcement and fallback paths.

**Why this bundle is safe:** additive policy metadata + guarded enforcement with flags.

---

## Bundle 4 (Explainability + reliability read models, medium risk)

**Goal:** Add operator value without mutating runtime authority.

**PR 4.1 — Mission timeline read model**
- Add read-only endpoint aggregating mission bridge stages + task transitions + governance events.
- Explicitly mark read-only, no mutation side effects.

**PR 4.2 — Tenant reliability summary endpoint**
- Add read-only summaries:
  - mission throughput
  - queue claim/lease health indicators
  - dead-letter rates
  - recovery success ratios

**PR 4.3 — Metrics and docs**
- Add Prometheus metrics contract docs and route docs.
- Add contract tests for response schema and auth/tenant scope.

**Why this bundle is safe:** read-model additions only.

---

## Bundle 5 (Economic observability, medium risk)

**Goal:** Add cost governance signals for mission-stage economics.

**PR 5.1 — Metrics schema additions**
- Add additive metrics labels/counters for mission-stage cost/runtime budgets.

**PR 5.2 — Budget policy scaffolding**
- Add policy config docs and feature flags.
- No hard blocking in first PR; observe-only mode first.

**PR 5.3 — Budget gates (opt-in)**
- Optional controlled enforcement for selected tenants/plans.

**Why this bundle is safe:** staged rollout (observe -> enforce), feature-flagged.

---

## Bundle 6 (GTM autopilot foundation, high risk but isolated)

**Goal:** Begin self-selling capability without breaking existing runtime.

**PR 6.1 — GTM mission contract docs + capability catalog**
- Add:
  - `docs/product/GTM_SELF_SELLING_ARCHITECTURE.md`
  - `docs/product/GTM_CAPABILITY_CATALOG.md`
  - `docs/policies/OUTBOUND_COMMUNICATION_POLICY.md`

**PR 6.2 — Declarative GTM capability records only**
- Seed capabilities/adapters as declarative entries (no execution binding yet).

**PR 6.3 — Controlled runtime binding pilot**
- Bind one low-risk path (e.g., draft-only blog content generation).
- Strict human approval gate before publish.
- Full audit/evidence capture.

**Why this bundle is safe:** progressive activation; starts declarative then one guarded runtime path.

---

## Schema-alignment strategy (how to avoid breaking existing contracts)

1. **Additive-first changes**
   - New JSON keys must be optional with deterministic defaults.
2. **Versioned contract envelopes**
   - Continue schema version tagging in metadata and fail-closed for unknown future versions.
3. **Dual-read strategy during transitions**
   - New readers accept legacy normalized shape + new shape until migration completes.
4. **No silent semantic repurposing**
   - Never change meaning of existing keys without version increment.
5. **Migration discipline**
   - One-way, reversible-safe where possible, and validated by migration contract tests.

---

## Bundling matrix (what can be safely combined)

### Can be bundled together safely
- PR 0.1 + 0.2 + 0.3 (docs-only foundation)
- PR 1.1 + 1.2 (ledger + checker)
- PR 4.1 + 4.2 + 4.3 (read-only observability package)

### Should remain separate PRs
- PR 2.x readiness hardening from PR 3.x lifecycle enforcement (different risk domains)
- PR 5.3 budget gates from PR 5.1 metrics (enforcement should follow observe-only period)
- PR 6.3 runtime binding pilot from PR 6.1/6.2 docs/declaration setup

### Never bundle together
- Destructive schema change + first runtime behavior relying on it
- New enforcement gates + unrelated large refactors
- GTM outbound publishing automation + policy engine rewrite in same PR

---

## Test and release gate per bundle

For each bundle, minimum required checks:

- `ruff check .`
- `ruff format --check .`
- `python -m pytest -m "not integration"`

Additional per risk level:

- Bundle 2+ (runtime semantics changes): targeted integration tests + validation matrix rows
- Bundle 3+ (policy enforcement): contract denial-path tests
- Bundle 6.3 (GTM runtime binding): release-gating scenarios proving forbidden outcomes do not occur

---

## Rollback strategy

1. **Config-first rollback:** disable feature flags for new gates/automation.
2. **Route-level rollback:** keep old route behavior available where compatibility is required.
3. **Data rollback posture:** additive fields can remain inert if feature is disabled.
4. **Operational rollback drills:** add runbook updates and one dry-run rollback test per medium/high-risk bundle.

---

## Definition of done (per issue cluster)

### Complexity / onboarding issues resolved when:
- Authority classes are visible in docs, CI, and API metadata.
- Contributor onboarding includes a “declarative vs executable” quickstart.

### Drift issues resolved when:
- Freshness policy exists and CI enforces claim parity.
- README/state report/validation docs pass drift sentinel checks.

### Readiness gap resolved when:
- Readiness endpoints prove DB+queue truth and tests cover degraded dependencies.

### Lifecycle policy gap resolved when:
- Evidence/outcome retention and escalation semantics are documented + validated.

### Explainability/economics/reliability gaps resolved when:
- Read-only mission timeline, tenant reliability, and mission economics metrics are live and tested.

---

## 90-day execution calendar (practical)

### Days 1–14
- Bundle 0 complete
- Bundle 1 (PR 1.1 + 1.2) complete

### Days 15–30
- Bundle 1 (PR 1.3) complete
- Bundle 2 complete

### Days 31–50
- Bundle 3 complete

### Days 51–70
- Bundle 4 complete

### Days 71–85
- Bundle 5.1 + 5.2 complete

### Days 86–90
- Bundle 6.1 + 6.2 ready
- Decide go/no-go for 6.3 pilot based on policy and validation readiness

---

## Final recommendation

Adopt this exact bundling plan and enforce “authority clarity before automation.”

That sequencing minimizes breakage risk, keeps schema continuity intact, reduces contributor confusion, and creates a controlled path from today’s strong governed runtime into self-selling GTM execution capabilities.
