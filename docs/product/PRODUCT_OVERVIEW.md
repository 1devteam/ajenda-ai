# Ajenda AI — Product Overview

**Status:** Active product narrative
**Audience:** Prospective customers, operators, and partners
**Last reconciled:** November 2, 2026
**Evidence boundary:** Implementation, tests, migrations, and runtime proof
artifacts remain authoritative. This overview does not turn a configured,
simulated, or locally proven capability into a universal availability claim.

## Work that stays accountable

Ajenda is a governed AI work platform for organizations that need business work
to remain visible, bounded, and explainable. It connects a goal to a mission,
the mission to permitted work, and completed work to evidence and outcome
readback.

The point is not to make AI look autonomous. The point is to make useful work
possible while preserving the context, authority, and record a business needs to
operate responsibly.

```text
business goal
  → scoped mission and operating context
  → policy, authorization, and plan checks
  → queue-backed execution or human review
  → evidence, deliverable, and outcome readback
```

## What customers can see in the current product build

### Missions instead of loose prompts

Ajenda accepts business work as a mission with an intended outcome, context,
constraints, and a visible lifecycle. It can compose a structured plan from
plain language, request a complete restatement when material information is
missing, and keep confirmation separate from runtime admission.

### Control before execution

Eligible runtime work enters through an authoritative queue and worker-lease
path. Policy and authorization can deny work or hold it for review. A plan,
catalog entry, preview, or screen does not itself grant execution authority.

### Business context that stays connected

Business profiles, operating preferences, internal records, and approved
knowledge help work remain relevant to a tenant's organization. These inputs are
governed context; they are not a shortcut around authorization or evidence.

### Evidence and outcomes that can be inspected

Ajenda records runtime evidence, audit/governance events, delivered artifacts,
and outcome-review surfaces. It keeps observations, verified identity,
inference, provider success, and business acceptance distinct so a plausible
result is not misrepresented as a proven outcome.

### Connections with explicit boundaries

Credential-bound provider interfaces and optional connectors can extend a
mission. A missing connection fails closed by default. Provider configuration,
tenant authorization, plan access, action policy, and evidence requirements
remain separate decisions.

## Current availability boundary

| Area | What can be stated today |
|---|---|
| Core governed runtime | Implemented in source and exercised by repository tests plus isolated Compose proof. |
| Customer workspace | Frontend routes for onboarding, account, missions, tasks, approvals, records, connections, settings, and billing are implemented. |
| Customer onboarding and billing | Implemented in source. A real deployment additionally needs approved identity/email, Stripe, domain, and secret configuration. |
| External connectors | Available only when the relevant provider, credential, tenant authority, and environment configuration are present. Missing credentials do not become simulated success in production. |
| Public research | The system preserves provider attempts, result provenance, empty results, and failure states. Local fixture behavior is not presented as evidence that a live provider found or verified real businesses. |
| Hosted AWS delivery | ECS/Terraform is the intended target and is source-validated. It is not a production or staging claim until an authorized target deployment proves migration, readiness, role, queue, browser, evidence, and operator-readback behavior. |
| Kubernetes | Reference manifests only; not an authorized release target. |

## The trust model

Ajenda's current technical design is organized around several practical
promises:

- tenant-scoped request, service/repository, queue, and database boundaries;
- explicit authorization, policy, and side-effect classification;
- queue-backed execution and worker-lease ownership;
- durable evidence and auditability;
- bounded recovery rather than silent state repair; and
- deployment promotion that requires migration and schema compatibility before
  dependent runtimes serve work.

These are implementation and verification commitments, not a substitute for a
customer's own security, legal, procurement, or deployment review.

## Where to go next

- Start with the repository [README](../../README.md) for a concise product and
  engineering entry point.
- Review the public product's **Security and governance** page for the
  customer-facing explanation, and [SaaS architecture](../SAAS_ARCHITECTURE.md)
  for the technical enforcement boundaries.
- Review [system architecture](../architecture/SYSTEM_ARCHITECTURE.md) and the
  [live runtime proof gate](../validation/live-runtime-proof-release-gate.md)
  when evaluating technical evidence.
- Review the [deployment environment contract](../deployment/production-env-contract.md)
  before treating a local build as a hosted service.

Exact paid pricing, contractual support commitments, and production service
availability are commercial decisions and should be published only with their
approved terms.
