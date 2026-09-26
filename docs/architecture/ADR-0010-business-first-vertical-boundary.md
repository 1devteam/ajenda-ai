# ADR-0010: Business-first vertical boundary

**Status:** Proposed  
**Date:** 2026-09-10

## Decision

Ajenda verticals represent a tenant's operating domain, not a channel or
provider. A vertical begins with the business context and operating intent that
make work meaningful, then selects missions and capabilities. Channels such as
email, social networks, GitHub, CRM, and calendars are provider adapters used by
those missions.

The vertical boundary is composed of five tenant-scoped contracts:

1. **Business context** — approved identity, market, offer, customer, and
   operating facts from `BusinessProfile`.
2. **Operating authority** — preparation, performance, prohibition, approval,
   and escalation rules from `OperatingCharter`.
3. **Outcome intent** — canonical business outcomes and deliverables from the
   mission composition contracts and job catalog.
4. **Work graph** — mission, dependencies, planned tasks, evidence, and
   outcome review records on the existing runtime spine.
5. **Provider adapters** — tenant-authorized read or side-effect capabilities
   resolved through credentials, policy, idempotency, queue admission, leases,
   and evidence.

Vertical templates are projections of these contracts for a user workflow.
They do not define provider authority, create a second runtime, or replace the
business profile and operating charter.

## Consequences

- A new vertical must identify its business purpose, outcomes, authority rules,
  work graph, and evidence contract before adding provider actions.
- A provider may serve multiple verticals without becoming a vertical itself.
- Social, GitHub, email, and CRM integrations remain adapters or capabilities;
  they do not determine the tenant's operating model.
- Provider credentials cannot be the source of business truth. They authorize
  a bounded capability after the vertical and charter have selected the work.
- Existing `vertical.research`, `vertical.email`, and `vertical.social` code is
  transitional template infrastructure. It must be evaluated against this
  boundary before new templates or provider writes are added.

## Authority and source of truth

The implementation sources are:

- `backend/domain/business_profile.py` for approved tenant business facts;
- `backend/services/operating_charter.py` for preparation, performance, and
  prohibition policy;
- `backend/services/mission_composition/contracts.py` and the job catalog for
  canonical outcomes and readiness;
- `backend/domain/mission.py`, `ExecutionTask`, the queue, lease, worker, and
  evidence services for runtime work;
- provider credential and runtime-authority services for adapter access.

Product and architecture documents describe this contract but do not prove its
runtime behavior. Contract and integration tests remain the acceptance source.

## Required acceptance proof for a new vertical

A vertical addition must prove:

- tenant-scoped business context is read without granting runtime authority;
- charter policy can allow, require review for, or deny each capability;
- canonical outcomes compile into a dependency-aware graph;
- planned work enters through `ExecutionTask` and the existing queue and lease
  spine;
- provider failures, retries, and ambiguous external outcomes fail closed or
  become visible human-review states;
- evidence and outcome review records remain observable after completion; and
- a provider credential or adapter cannot be used outside the selected tenant,
  action, side-effect class, and approval contract.

## Rollout sequence

1. Validate business context, charter, outcomes, and graph behavior with local
   or internal capabilities.
2. Add provider-neutral artifacts and read capabilities.
3. Add provider adapters with tenant-scoped credentials and evidence.
4. Add side-effecting capabilities only after idempotency, approval,
   compensation, and runtime proofs exist.

No new G.R.A.F.T.1st design is required for this boundary. A future G.R.A.F.T.1st design is only
appropriate if the canonical business ontology, mission graph, or cross-vertical
authority model changes.
