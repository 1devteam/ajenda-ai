# Runtime Deployment Limits

This document captures deployment constraints that must remain true for Ajenda runtime guarantees to hold in staging or production-like deployments.

## Worker Tenant Scope

A worker consumes tasks only for the tenant configured by:

```text
AJENDA_WORKER_TENANT_ID
```

Implications:

- Tasks for other tenants can be queued but will not be processed by that worker.
- A queued task remaining idle does not automatically mean Redis or the worker loop is broken.
- Multi-tenant execution requires either multiple tenant-scoped workers or an intentional routing model.

## Known Failure Mode: Tasks Remain Queued

Symptom:

- task status remains `queued`;
- Redis pending queue is greater than `0`;
- Redis processing queue is `0`;
- worker container is running;
- worker logs show no claim or execution activity for that task.

Likely cause:

- task tenant does not match the configured worker tenant.

Resolution:

- create/queue proof tasks under the configured worker tenant;
- or run a worker configured for the task tenant;
- do not weaken queue authority or bypass WorkerLease ownership to make the task run.

## Secrets and Runtime Contract Validation

Production-mode Compose startup must fail fast when required secret values are missing, placeholders, or invalid.

Required runtime contract checks include:

- database password is configured through the Compose env file;
- webhook secret encryption key is a valid Fernet key;
- previous webhook secret encryption key is optional and should only be set during key rotation.

The local Compose env file must remain ignored by git and must not be committed.

## Metrics Constraints

Metrics must expose existing truth only.

Metrics must not:

- trigger runtime recovery;
- call readiness;
- mutate DB rows;
- mutate Redis queue state;
- create or release worker leases;
- enqueue, dequeue, retry, or dead-letter tasks.

## Alert Constraints

Alert rules must remain based on metric state, not direct API probes or exception strings.

Required Compose alert families:

- readiness dependency unavailable alerts;
- queue backlog alert;
- dead-letter presence alert.

Alert expressions must not depend on tenant IDs, worker IDs, task IDs, hostnames, URLs, credentials, exception text, or tracebacks.

## Queue and Lease Constraints

Runtime correctness depends on preserving these meanings:

- Redis queue state is the source of truth for pending and processing work.
- WorkerLease is the ownership contract for in-flight work.
- Expired DB leases are not the same as normal released queue claims.
- Dead-lettered work is terminal unless explicitly retried through the approved operations path.

Do not collapse these meanings in runtime code, tests, or docs.
