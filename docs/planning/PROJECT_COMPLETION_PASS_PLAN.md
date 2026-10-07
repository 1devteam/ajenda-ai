# Ajenda project-completion pass plan

**Status:** established roadmap
**Owner:** Ajenda product/runtime maintainers
**Method:** UPG/LAP followed by GRAFT+ for every non-trivial pass

This plan intentionally groups work by one authoritative layer and one proof surface. It does not
merge provider integrations, onboarding/billing, presentation, or runtime-authority changes into
the intelligence-foundation pass.


## Pass 1 — Intelligence foundation

**Status: complete — 2026-10-06.** See `docs/validation/intelligence-foundation-pass-1-closure-2026-10-06.md`.

Semantic lattice coverage, epistemic provenance/freshness, coverage and capacity assessment, shadow
preview/reconciliation, contradiction handling, and adversarial mission proof. No provider,
onboarding, billing, UI, credential, or runtime-authority changes are in scope.

Exit proof:

`intent → semantic context → epistemic context → coverage → preview → governed composition`

is deterministic, tenant-safe, evidence-backed, and free of unexplained artifact contradictions.


## Pass 2 — Continuous assurance

**Status: active implementation.**

Independent recurring reconciliation, durable tenant-scoped findings, first-divergence history,
metrics/alerts, queue/lease/evidence/artifact comparisons, and operational runbooks. The monitor is
read-only and cannot create tasks, mutate business facts, or promote authority.

## Pass 3 — Internal capability lane

Complete the internal CRM path end to end: retrieval, qualification, enrichment, artifacts, evidence,
reconciliation, retry/recovery, and multi-tenant proof.

## Pass 4 — External provider lanes

Complete one provider at a time through credentials, capability, action, evidence, deliverable,
retry, rollback, and live proof. Start with HubSpot, then Gmail/email, Salesforce, Calendar, and
later providers.

## Pass 5 — SaaS/onboarding backend

Prove wizard onboarding and Stripe/account-state onboarding, profile and contact persistence, billing
lifecycle, tenant isolation, recovery, and signup-to-first-mission behavior.

## Pass 6 — Presentation layer

Expose proven read models through the profile application, contacts, goals/knowledge, mission proposal,
progress, evidence, and blocked/stale/contradictory states. The UI does not add business authority.

## Pass 7 — Production completion

Finalize real domains/secrets, monitoring ownership, backups, rollback, kill switches, load/recovery
proof, security/dependency policy, runbooks, and the complete hosted SaaS path.

## Completion rule

A pass is complete only when its implementation owner, typed inputs/outputs, tenant and authority
boundaries, evidence, freshness/contradiction behavior, recovery/rollback, live proof, GRAFT+ result,
and documentation are all present. Deferred work must be named and remain outside the pass.
