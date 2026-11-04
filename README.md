# Ajenda AI

**Governed AI work for businesses that need more than a chat transcript.**

Ajenda turns a business goal into scoped work with explicit authority, visible
execution, human review where it matters, and evidence that survives after the
work is done. It is built for teams that want useful AI assistance without
losing control of their business context, connected systems, or decisions.

> **Current product and proof boundary — November 2, 2026**
> The repository contains the current Ajenda product and governed runtime. A
> local, isolated Docker Compose proof has exercised migration, readiness,
> queue/lease execution, durable evidence, and deliverable readback. That is
> not a claim of a live cloud deployment, general public-web research success,
> or every third-party integration being configured for every customer.

## What Ajenda helps a business do

- Turn an outcome into a mission instead of a loose prompt thread.
- Keep business context, plans, approvals, connected tools, and outcomes in one
  accountable operating path.
- Run eligible work through a queue-and-lease runtime rather than silently
  invoking tools from a declarative plan.
- Preserve evidence, audit events, and outcome records so people can inspect
  what happened and why.
- Keep tenant scope, authorization, policy, and explicit side-effect controls
  attached to the work.

Ajenda is not designed to be unconstrained autonomous software. Missing
authority, credentials, or required dependencies should leave work blocked,
reviewable, or visibly incomplete—not quietly turn it into success.

## The operating path

```mermaid
flowchart LR
    A[Business goal] --> B[Mission and boundaries]
    B --> C[Policy and authority checks]
    C --> D[Queue-backed work]
    D --> E[Approval when required]
    E --> F[Evidence and outcome readback]
```

This is the product promise Ajenda is built around: useful work, with the
context and controls needed to trust its path.

## What exists in the current build

| Product area | Current source-backed capability |
|---|---|
| Customer workspace | Signup, verification, account, billing, mission, task, approval, records, connections, and settings routes exist in the customer frontend. |
| Mission operations | Plain-language composition, confirmation, task-graph materialization, queue admission, worker execution, and deliverable readback use the governed runtime spine. |
| Governance | Tenant-aware access, PostgreSQL RLS, policy/approval boundaries, queue/lease authority, audit events, and evidence records are implemented across the affected paths. |
| Business context | Business profiles, operating context, internal records/CRM surfaces, and product knowledge are tenant-scoped inputs to work—not independent execution authority. |
| Connections | Credential-bound provider interfaces and optional connectors are available; absent credentials fail closed by default. |
| Billing | Stripe checkout and portal require `billing:manage`; signed webhook processing deduplicates events before plan changes. |
| Deployment spine | Compose is the locally proven runtime surface. AWS ECS/Terraform is the intended hosted target with source-validated promotion controls; it still requires authorized staging proof. Kubernetes manifests are reference-only. |

For a buyer-friendly explanation of the same boundary, read
[the product overview](docs/product/PRODUCT_OVERVIEW.md). For technical
contracts, proof limits, and operating instructions, start at
[the documentation guide](docs/README.md).

## Availability and honest limits

Ajenda is intentionally precise about the difference between code, configured
capability, and observed deployment behavior.

| Statement | Current evidence |
|---|---|
| Governed mission/runtime path | Implemented and exercised in repository tests and isolated Compose proof. |
| Tenant and authorization boundaries | Implemented with layered application/repository/database controls and contract/integration coverage. |
| Customer onboarding and billing surfaces | Implemented in source; production use requires the operator's approved identity, email, Stripe, domain, and secret configuration. |
| External providers and public research | Provider/credential dependent. Missing credentials fail closed. A local fixture proof is not presented as a live-provider result. |
| Hosted AWS service | Intended target only until an authorized ECS staging deployment proves the complete target contract. |
| Kubernetes | Preserved reference manifests, not an authorized release target. |

This distinction is deliberate. A successful HTTP request is not a verified
business identity, a completed task is not a business outcome, and a local proof
is not a production deployment.

## Product principles

- **Human control where it matters.** Consequential work can wait for explicit
  approval instead of treating autonomy as all-or-nothing.
- **Tenant-private by design.** Scope is enforced through the request,
  service/repository, queue, and database layers.
- **Evidence over assertion.** Ajenda keeps provider outcomes, observations,
  inferences, verified identity, qualification, and acceptance distinct.
- **Connected without losing boundaries.** Providers extend a governed mission;
  they do not become an alternate execution path.
- **Recoverable operations.** Queue, lease, retry, and runtime evidence are
  first-class operational concerns.

## For prospective customers and operators

The public product pages in the frontend cover the customer narrative:

- `/` — the product promise and workflow
- `/product` — missions, approvals, business memory, connections, outcomes,
  and runtime control
- `/security` — Ajenda's implementation-backed governance posture
- `/pricing` — current availability language; paid pricing is not advertised
  until approved commercial terms are available

The product preview is illustrative. It is not a tenant dashboard or a claim
that the displayed missions, counts, or research results are live customer data.

## Local evaluation and engineering setup

Ajenda is a multi-service system. Use the documented Compose lifecycle rather
than improvising database state or worker entrypoints.
Local backend development requires Python 3.13 or later.

```bash
# Install the backend for local development.
python -m pip install -e '.[dev]'

# Run focused non-integration checks.
python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration"
```

For the production-like local runtime, schema roles, and the dedicated migrator,
follow [the Compose database lifecycle](deploy/compose/README.database-lifecycle.md)
and [the production environment contract](docs/deployment/production-env-contract.md).
Do not reset, stamp, rebuild, or manually alter a persistent database to hide a
schema mismatch.

## API and runtime orientation

Infrastructure probes are `/health` and `/readiness`. Business and operational
APIs are versioned below `/v1`; the following route families are a navigation
index, not a substitute for authentication or authority contracts:

- `/v1/auth/*`
- `/v1/onboarding/*`
- `/v1/account/*`
- `/v1/billing/*`
- `/v1/ability-runtime/*`
- `/v1/api-keys/*`
- `/v1/missions/*`
- `/v1/tasks/*`
- `/v1/business-profile/*`
- `/v1/business-understanding/*`
- `/v1/capabilities/*`
- `/v1/capability-adapters/*`
- `/v1/evidence/*`
- `/v1/outcome-reviews/*`
- `/v1/retrieval-contracts/*`
- `/v1/mission-brief/*`
- `/v1/crm/*`
- `/v1/review-queue/*`
- `/v1/plugins/*`
- `/v1/webhooks/*`
- `/v1/vertical-ops/*`
- `/v1/workforces/*`
- `/v1/branches/*`
- `/v1/runtime/*`
- `/v1/operations/*`
- `/v1/observability/*`
- `/v1/system/*`
- `/v1/admin/*`

The [system architecture](docs/architecture/SYSTEM_ARCHITECTURE.md),
[authority ledger](docs/contracts/authority-ledger.v1.yaml), and
[live runtime proof gate](docs/validation/live-runtime-proof-release-gate.md)
define the relevant ownership and proof boundaries.

## Documentation map

- [Product overview](docs/product/PRODUCT_OVERVIEW.md) — customer-readable
  product narrative and availability boundary.
- [Documentation guide](docs/README.md) — current technical, operational,
  proposed, and historical documents by audience.
- [System architecture](docs/architecture/SYSTEM_ARCHITECTURE.md) —
  code-aligned technical map and Mermaid flows.
- [Project specification](PROJECT_SPEC.md) — binding engineering scope and
  invariants.
- [Deployment contract](docs/deployment/production-env-contract.md) — current
  release/runtime environment contract.
- [Documentation freshness policy](docs/policies/DOCS_FRESHNESS_POLICY.md) —
  how documentation is kept honest and what CI does (and does not) enforce.

The binding freshness-policy source is
`docs/policies/DOCS_FRESHNESS_POLICY.md`.

## Engineering standards

Ajenda changes use UPG/LAP and GRAFT+ to trace ownership, blast radius,
invariants, and proof before runtime-affecting code changes. Required local
checks are defined in `AGENTS.md`; the common gate is:

```bash
ruff check backend/ tests/ scripts/validation/
ruff format --check backend/ tests/ scripts/validation/
mypy backend/
python scripts/validation/contract_drift_check.py
python scripts/validation/runtime_authority_inventory_check.py
python scripts/validation/migration_seed_contract_check.py
python scripts/validation/ability_rollout_contract_check.py
python scripts/validation/graft_plus_graft1st_reconciliation_check.py
python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration"
```

Runtime, provider, queue, lease, migration, or evidence changes need the
additional targeted integration and live-proof gates described in the relevant
contract. A green mock is not presented as a live runtime result.

## Repository status

This repository is proprietary. Copyright and use restrictions are documented
in `COPYRIGHT` and `NOTICE`; no open-source license grant is provided.
