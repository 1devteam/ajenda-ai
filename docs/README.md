# Ajenda AI Documentation Guide

**Status:** Active navigation guide
**Last reconciled:** November 2, 2026
**Authority:** Code, migrations, tests, and observed runtime artifacts override
documentation when they disagree.

Ajenda's documentation is deliberately separated by audience and evidence
status. A product overview is not a deployment runbook; a historical audit is
not current runtime proof.

## Start here

| If you are… | Start with | Then use |
|---|---|---|
| Evaluating Ajenda | [Product overview](product/PRODUCT_OVERVIEW.md) | [README](../README.md) and the proof boundary below |
| Operating a runtime | [Production environment contract](deployment/production-env-contract.md) | [Compose lifecycle](../deploy/compose/README.database-lifecycle.md), [deployment](../ops/runbooks/deployment.md), and [rollback](../ops/runbooks/rollback.md) |
| Building or reviewing Ajenda | [`AGENTS.md`](../AGENTS.md) | [System architecture](architecture/SYSTEM_ARCHITECTURE.md) and [GRAFT+ workflow](development/GRAFT_PLUS_WORKFLOW.md) |
| Evaluating proof | [Live runtime proof gate](validation/live-runtime-proof-release-gate.md) | [validation matrix](validation/live-runtime-matrix.md) and [artifact guide](../artifacts/validation/README.md) |
| Researching decisions | [ADR index](architecture/ADR_INDEX.md) | Status-marked audit, remediation, planning, and validation records |

## Current reference set

These documents are maintained as current references. Their status does not
replace source inspection or runtime proof.

| Document | Audience and purpose |
|---|---|
| [`../README.md`](../README.md) | Public/repository entry point: product value, current capability boundary, and developer orientation. |
| [`product/PRODUCT_OVERVIEW.md`](product/PRODUCT_OVERVIEW.md) | Customer-readable product narrative and availability boundary. |
| [`../PROJECT_SPEC.md`](../PROJECT_SPEC.md) | Binding engineering scope, invariants, authority model, and release expectations. |
| [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md) | Code-aligned technical map and Mermaid flows. |
| [`architecture/ADR_INDEX.md`](architecture/ADR_INDEX.md) | Accepted and proposed architecture decisions with unique identifiers. |
| [`SAAS_ARCHITECTURE.md`](SAAS_ARCHITECTURE.md) | Tenant, plan, onboarding, billing, and worker-tenancy enforcement topology. |
| [`deployment/production-env-contract.md`](deployment/production-env-contract.md) | Current production configuration, migration/promotion, ECS, and Kubernetes status. |
| [`validation/live-runtime-matrix.md`](validation/live-runtime-matrix.md) | Validation scenarios and evidence semantics. |
| [`validation/live-runtime-proof-release-gate.md`](validation/live-runtime-proof-release-gate.md) | What the Compose runtime proof actually proves and what it does not. |
| [`policies/DOCS_FRESHNESS_POLICY.md`](policies/DOCS_FRESHNESS_POLICY.md) | Documentation classification, review requirements, and current CI enforcement boundary. |
| [`contracts/authority-ledger.v1.yaml`](contracts/authority-ledger.v1.yaml) | Machine-readable authority/proof map. |

## Product and capability contracts

`docs/product/` contains domain contracts and implementation maps. They do not
all have the same status:

- **Current product narrative:** `product/PRODUCT_OVERVIEW.md`.
- **Active source-linked contracts:** mission, ability, business-profile,
  internet, credential, and knowledge documents. Read their status and owning
  implementation before relying on a claim.
- **Planning or slice documents:** files named `*-slice-*`, `V2_BUILD_PLAN`,
  `TOOL_AND_ABILITY_PHASE_PRIORITIES`, and similar artifacts record
  scope/sequence; they do not establish live capability.

Important active references include:

| Document | Scope |
|---|---|
| [`product/mission-based-ai-core.md`](product/mission-based-ai-core.md) | Mission model and boundaries |
| [`product/ability-rollout-contract.md`](product/ability-rollout-contract.md) | Capability/action rollout contract |
| [`product/internet-access-phase.md`](product/internet-access-phase.md) | Governed internet access and provider boundaries |
| [`product/business-profile-implementation-contract.md`](product/business-profile-implementation-contract.md) | Business-context implementation contract |
| [`product/GTM_CAPABILITY_CATALOG.md`](product/GTM_CAPABILITY_CATALOG.md) | GTM catalog; verify action maturity against implementation and proof |

## Operations and deployment

| Document | What it controls |
|---|---|
| [`deployment/production-env-contract.md`](deployment/production-env-contract.md) | Runtime configuration, role identities, migrator-first ordering, target status. |
| [`deployment/STAGING_PROOF.md`](deployment/STAGING_PROOF.md) | Compose staging/runtime proof contract. |
| [`deployment/RUNTIME_LIMITS.md`](deployment/RUNTIME_LIMITS.md) | Runtime operational limits. |
| [`../deploy/compose/README.database-lifecycle.md`](../deploy/compose/README.database-lifecycle.md) | First provisioning versus routine persistent-database startup. |
| [`../ops/runbooks/deployment.md`](../ops/runbooks/deployment.md) | ECS controlled promotion. |
| [`../ops/runbooks/rollback.md`](../ops/runbooks/rollback.md) | Schema-aware ECS rollback/forward-fix boundary. |
| [`../infra/README.md`](../infra/README.md) | Terraform foundation and external release inputs. |
| [`deployment/CLOUD_PLATFORM_DECISION_STUDY_2026-11-01.md`](deployment/CLOUD_PLATFORM_DECISION_STUDY_2026-11-01.md) | Proposed AWS platform decision; not deployment authorization. |

Kubernetes manifests remain reference-only until their image, identity,
migration, readiness, rollback, and target-proof contract is complete. See
[`../deploy/k8s/README.md`](../deploy/k8s/README.md).

## Architecture, policy, and validation

- [`architecture/ADR_INDEX.md`](architecture/ADR_INDEX.md) lists architecture
  decisions. Accepted ADRs are doctrine; proposed ADRs are not.
- [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md)
  is the current technical map. Its diagrams are not deployment proof.
- [`policies/`](policies/) contains policy references for documentation,
  evidence, outbound communication, outcome escalation, tenant DB sessions,
  and budget policy.
- [`validation/`](validation/) contains both current proof contracts and dated
  checkpoint reports. Inspect document status/date before using a result as
  present-tense evidence.
- [`audits/public-research-rebuild/`](audits/public-research-rebuild/) is the
  public-research rebuild record, including its remaining live-proof gates.

## Preserved historical and planning records

Ajenda keeps historical records because they explain why boundaries, migrations,
and proof requirements exist. They are preserved, not rewritten into current
claims.

| Location | Interpretation |
|---|---|
| `PROJECT_STATE_REPORT.md` | **Historical snapshot:** October 3, 2026; schema `0038_knowledge_retrieval`. Do not use it as current runtime or migration proof. |
| `SYSTEM_ASSESSMENT_2026-05-23.md`, `REMEDIATION_EXECUTION_PLAN_2026-05-23.md` | Historical early assessments/plans. |
| `audits/` | Point-in-time investigations and evidence ledgers. Use current source/proof for present disposition. |
| `remediation/` | Completed, superseded, or in-progress remediation records; retain their stated date/status. |
| `planning/` | Proposals, roadmaps, acceptance plans, and thread handoffs—not implementation authority. |
| Dated files under `validation/` | Checkpoint evidence for the named source/context, not proof for a later revision. |

## Documentation status conventions

- **Active/current:** Maintained reference; still subordinate to source and
  current proof.
- **Proposed:** Under consideration; not implementation authority.
- **Historical/superseded:** Retained for provenance; not a present-tense claim.
- **Reference-only:** Example/template that must not be used as a release path.

When a document does not state its status, determine its authority from the
index, date, linked owner, and implementation before using it in a decision.
