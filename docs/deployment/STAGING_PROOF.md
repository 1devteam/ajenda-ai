# Staging Runtime Proof (Compose)

This document defines the staging proof contract for the Docker Compose runtime path. It records required behavior and proof checks, not exploratory terminal history.

## Required Conditions

A staging Compose deployment is considered booted only when all of the following are true:

- API container is running and healthy.
- Worker container is running.
- Postgres container is running and healthy.
- Redis container is running.
- Prometheus container is running.
- OpenTelemetry collector container is running when enabled by Compose.
- Prometheus target for the API is up.

## Required Endpoints

| Endpoint | Expected result |
| --- | --- |
| `GET /health` | liveness response with `status=ok` |
| `GET /readiness` | `status=ready`, `database=ready`, `queue=ready` |
| `GET /v1/observability/metrics` | Prometheus metric output containing readiness and runtime invariant metrics |

## Required Metrics

The metrics endpoint must expose these runtime signals:

- `ajenda_readiness_dependency_status{dependency="database"}`
- `ajenda_readiness_dependency_status{dependency="queue"}`
- `ajenda_queue_depth`
- `ajenda_dead_letter_count`
- `ajenda_active_leases`
- `ajenda_worker_utilization`

Healthy idle staging state is expected to report:

- readiness dependency metrics at `1` for database and queue after readiness has been evaluated;
- queue depth at `0` when no tasks are pending;
- dead-letter count at `0` when no tasks have terminal queue failures;
- active leases at `0` when no task is in flight.

## Prometheus Proof

Prometheus must prove all of the following:

- Server readiness endpoint `/-/ready` returns ready.
- API target is up.
- API scrape URL remains `/v1/observability/metrics`.
- Alert rules are loaded from the configured Compose rule file.

Required alert rules:

- `AjendaDatabaseReadinessUnavailable`
- `AjendaQueueReadinessUnavailable`
- `AjendaQueueBacklogDetected`
- `AjendaDeadLettersPresent`

Under a healthy idle staging deployment, these alerts should be loaded and inactive.

## Queue Execution Proof

Given:

- a tenant matching the worker tenant scope;
- a mission owned by that tenant;
- a planned execution task with supported task metadata;
- queue admission through `ExecutionCoordinator.queue_task`;

then the runtime must prove:

- the task enters Redis pending queue;
- the worker claims the task;
- the worker executes the task;
- the task reaches `completed` state;
- a `worker_lease_id` is recorded in task metadata;
- Redis pending and processing queues drain back to `0`.

Expected state flow:

```text
planned -> queued -> claimed/running -> completed
```

The exact intermediate states may move quickly because the worker can claim and complete the task before manual observation.

## Done Condition

A staging Compose deployment is considered proof-passing when all of the following are true:

- Compose config resolves with the explicit Compose env file.
- Full stack starts without API or worker restart loops.
- `/health` returns liveness success.
- `/readiness` reports database and queue ready.
- `/v1/observability/metrics` exposes readiness and runtime invariant metrics.
- Prometheus target is up.
- Alert rules are loaded and inactive under healthy idle conditions.
- A worker-tenant task can be queued and completed by the worker.
- Redis pending and processing queues drain after task completion.

## Paid customer loop proof (Compose)

In addition to runtime proof above, the **customer product path** can be validated on the same Compose stack.

### Prerequisites

- Copy `deploy/compose/.env.staging.example` → `deploy/compose/.env.staging`, edit secrets, then sync to `deploy/compose/.env.prod` (API/worker/migrate load `.env.prod`).
- Start stack: `docker compose --env-file deploy/compose/.env.prod -f deploy/compose/docker-compose.prod.yml up -d --build`
- Customer UI on **http://localhost:8080** (nginx proxies `/v1` to API)

### Automated HTTP proof

```bash
bash deploy/scripts/paid-customer-loop-staging-proof.sh
```

Exit code `0` when all of the following hold:

| Step | Check |
| --- | --- |
| Frontend SPA | `GET /` serves React mount (`id="root"`) |
| Readiness proxy | `GET /readiness` via frontend returns ready |
| Signup | `POST /v1/onboarding/signup` via frontend proxy → `201` |
| Verify | `POST /v1/onboarding/verify-email` → bootstrap API key |
| Billing RBAC | Bootstrap key `GET /v1/account/billing` → `403` |
| Promote | `POST /v1/onboarding/promote-bootstrap-key` → operational key |
| Account reads | `GET /v1/account/me`, `/usage`, `/billing` → `200` |

Full walkthrough (Stripe CLI, manual UI): [`ops/runbooks/paid-customer-loop-staging.md`](../../ops/runbooks/paid-customer-loop-staging.md).

### CI integration proof

`tests/integration/saas/test_paid_customer_loop_real.py` covers signup → verify → promote → account reads → mocked Stripe webhook → `calendar-read` task launch over HTTP (Testcontainers Postgres/Redis).
