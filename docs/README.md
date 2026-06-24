# Ajenda AI — Documentation Index

**Last aligned with `main`:** 2026-06-22

When docs conflict with code, **code + tests win**. Start with the canonical set below.

---

## Canonical (always current)

| Document | Purpose |
|----------|---------|
| [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md) | **Mermaid flowcharts** + code-aligned system map |
| [`../PROJECT_SPEC.md`](../PROJECT_SPEC.md) | Canonical specification |
| [`../README.md`](../README.md) | Repository entry point |
| [`PROJECT_STATE_REPORT.md`](PROJECT_STATE_REPORT.md) | Current implementation status |
| [`SAAS_ARCHITECTURE.md`](SAAS_ARCHITECTURE.md) | Tenant isolation, plans, onboarding, billing |
| [`deployment/production-env-contract.md`](deployment/production-env-contract.md) | Required production environment variables |
| [`contracts/authority-ledger.v1.yaml`](contracts/authority-ledger.v1.yaml) | Machine-readable authority map |

---

## Architecture and governance

| Document | Purpose |
|----------|---------|
| [`architecture/ADR_INDEX.md`](architecture/ADR_INDEX.md) | Architecture decision records |
| [`architecture/ADR-0001-authority-classification-doctrine.md`](architecture/ADR-0001-authority-classification-doctrine.md) | Authority classes |
| [`architecture/ADR-0002-schema-evolution-strategy.md`](architecture/ADR-0002-schema-evolution-strategy.md) | Schema evolution |
| [`architecture/ADR-0003-readiness-semantics-doctrine.md`](architecture/ADR-0003-readiness-semantics-doctrine.md) | Health/readiness |
| [`architecture/ADR-0005-informed-autonomy-gate-policy.md`](architecture/ADR-0005-informed-autonomy-gate-policy.md) | Informed autonomy vs approval theater |
| [`policies/DOCS_FRESHNESS_POLICY.md`](policies/DOCS_FRESHNESS_POLICY.md) | Documentation SLA |
| [`policies/TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY.md`](policies/TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY.md) | Tenant DB session policy |

---

## Runtime validation and deployment

| Document | Purpose |
|----------|---------|
| [`validation/live-runtime-matrix.md`](validation/live-runtime-matrix.md) | Release-gating scenarios |
| [`validation/live-runtime-proof-release-gate.md`](validation/live-runtime-proof-release-gate.md) | Live runtime proof |
| [`deployment/RUNTIME_LIMITS.md`](deployment/RUNTIME_LIMITS.md) | Runtime limits |
| [`deployment/STAGING_PROOF.md`](deployment/STAGING_PROOF.md) | Staging runtime proof contract |
| [`../ops/runbooks/paid-customer-loop-staging.md`](../ops/runbooks/paid-customer-loop-staging.md) | Paid customer loop staging runbook |
| [`../deploy/scripts/paid-customer-loop-staging-proof.sh`](../deploy/scripts/paid-customer-loop-staging-proof.sh) | HTTP proof script (signup → account reads) |
| [`../deploy/compose/.env.prod.example`](../deploy/compose/.env.prod.example) | Compose production env template |
| [`../deploy/compose/.env.staging.example`](../deploy/compose/.env.staging.example) | Compose staging env template (noop email, exposed token for local proof) |
| [`../infra/README.md`](../infra/README.md) | Terraform/AWS infrastructure |

---

## Product contracts (domain-specific — verify against code)

These documents describe specific contract surfaces. For the full customer product map, start with [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md) §6 and the staging runbook above.

| Document | Scope |
|----------|-------|
| [`product/TOOL_AND_ABILITY_PHASE_PRIORITIES.md`](product/TOOL_AND_ABILITY_PHASE_PRIORITIES.md) | **Active roadmap** — tools/abilities, gate rollback, informed autonomy |
| [`product/mission-based-ai-core.md`](product/mission-based-ai-core.md) | Mission execution model |
| [`product/ability-rollout-contract.md`](product/ability-rollout-contract.md) | Ability rollout |
| [`product/GTM_CAPABILITY_CATALOG.md`](product/GTM_CAPABILITY_CATALOG.md) | GTM actions |
| [`product/business-profile-implementation-contract.md`](product/business-profile-implementation-contract.md) | Business profile |
| Other `docs/product/*` | Specialized contracts |

---

## Historical (do not use as current truth)

These dated documents are retained for history. They may describe plans or states that predate onboarding/billing on `main`.

| Document | Status |
|----------|--------|
| [`SYSTEM_ASSESSMENT_2026-05-23.md`](SYSTEM_ASSESSMENT_2026-05-23.md) | Historical — May 2026 |
| [`REMEDIATION_EXECUTION_PLAN_2026-05-23.md`](REMEDIATION_EXECUTION_PLAN_2026-05-23.md) | Historical — May 2026 |
| [`remediation/commercial_phase1.md`](remediation/commercial_phase1.md) | Superseded by implementation |
| [`remediation/phase1_commercial_complete.md`](remediation/phase1_commercial_complete.md) | Superseded — see SYSTEM_ARCHITECTURE |

For current commercial/onboarding status, use [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md) §3–6.