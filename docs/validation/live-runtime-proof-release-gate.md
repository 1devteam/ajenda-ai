# Live Runtime Proof Release Gate

**Status:** Active  
**Last reviewed:** July 7, 2026

## Purpose

`deploy/scripts/live-runtime-proof.sh` is the prod-like runtime proof for Ajenda AI. It complements the live runtime validation matrix by exercising the deployed Docker Compose stack and proving that the API, worker, database, Redis queue, Prometheus, and observability surfaces operate together.

This document records the source-controlled release-gate expectations for that proof script. Dynamic run output belongs in operator logs and validation artifacts; this file describes the static proof contract.

---

## Scope

The live runtime proof is an operator-driven release gate for prod-like Compose environments.

It is intentionally broader than a unit, contract, or integration test. The script validates the running stack and then creates real tenant-scoped work that must be accepted, executed, audited, observed, scraped, and cleaned up.

Current script:

```text
deploy/scripts/live-runtime-proof.sh
```

Default compose file:

```text
deploy/compose/docker-compose.prod.yml
```

Default API base URL:

```text
http://localhost:8000
```

Default Prometheus base URL:

```text
http://localhost:9090
```

CI workflow (automatic on `main` push):

```text
.github/workflows/ci.yml  →  job: live-runtime-proof
```

Manual GitHub Actions workflow (operator opt-in):

```text
.github/workflows/live-runtime-proof.yml
```

---

## Subsystem-lane release-gate alignment

The release gate is a proof surface for the subsystem lanes defined in `docs/product/mission-runtime-architecture-map.md`; it is not an alternate authority registry. A successful live proof may satisfy only the specific lane contracts it exercises, such as dependency readiness, real queue-backed worker execution, lineage/audit evidence, and observability metrics. It must not be cited as proof that unrelated lanes are complete unless the script, tests, and artifacts exercise those lanes directly.

When future work changes tenant/auth, mission intake/planning, task graph, materialization, queue admission, queue adapter state, lease lifecycle, worker dispatcher execution, tool/action runtime, evidence/audit, declarative governance, or validation behavior, the release gate must either add matching proof or explicitly defer that proof to named targeted tests and validation artifacts.

## Kernel and optional integrations

The default proof starts the customer frontend, API, worker, database, Redis,
migrations, Prometheus, and OTEL collector. HubSpot is not part of the kernel
and must not block API or worker startup. The HubSpot adapter and ingress remain
available only through the explicit Compose `hubspot` profile when that optional
integration is intentionally tested.

---

## Required environment

The script expects the prod-like Compose configuration and required production-style secrets to be available before execution.

Configurable inputs:

| Variable | Default | Purpose |
|---|---|---|
| `AJENDA_PROOF_COMPOSE_FILE` | `deploy/compose/docker-compose.prod.yml` | Compose file used for the proof stack |
| `AJENDA_PROOF_API_BASE_URL` | `http://localhost:8000` | API base URL used by HTTP probes |
| `AJENDA_PROOF_PROMETHEUS_BASE_URL` | `http://localhost:9090` | Prometheus base URL used by scrape-target checks |
| `AJENDA_PROOF_PROMETHEUS_JOB_NAME` | `ajenda-api` | Prometheus scrape job expected to become healthy |
| `AJENDA_PROOF_TIMEOUT_SECONDS` | `90` | Overall polling timeout for readiness, worker completion, and Prometheus scrape checks |
| `AJENDA_PROOF_POLL_SECONDS` | `2` | Poll interval for retry loops |
| `AJENDA_PROOF_CURL_CONNECT_TIMEOUT_SECONDS` | `5` | Curl connection timeout |
| `AJENDA_PROOF_CURL_MAX_TIME_SECONDS` | `10` | Curl max request time |
| `AJENDA_OPERATOR_MISSION_PROOF` | unset (`0`) | When `1`, run the real frontend → compose → confirm → launch → worker → deliverable HVAC proof |
| `AJENDA_PROOF_FRONTEND_BASE_URL` | `http://localhost:8080` | Frontend base URL used by the operator mission proof |
| `AJENDA_PROOF_PLUGIN_LANE_ENABLED` | unset (`0`) | When `1`, run optional plugin proof after core echo/GTM proof |
| `AJENDA_PROOF_AUTONOMY_LANE` | unset (`0`) | When `1`, plugin script also runs informed-autonomy tier-3 queue proof |
| `AJENDA_E2E_HUBSPOT_PAK` | unset | HubSpot bearer/PAK for live CRM plugin lane |
| `AJENDA_E2E_GMAIL_TOKEN` | unset | Gmail bearer for live email plugin lane |
| `AJENDA_E2E_LINKEDIN_TOKEN` | unset | LinkedIn bearer or OAuth JSON for live read lane |
| `AJENDA_E2E_SALESFORCE_SECRET` | unset | Salesforce OAuth JSON for live SOQL lane |
| `AJENDA_E2E_SALESFORCE_TOKEN` + `AJENDA_E2E_SALESFORCE_INSTANCE_HOST` | unset | Alternate Salesforce live proof inputs |
| `AJENDA_E2E_ADAPTER_HOST` | `127.0.0.1:8443` | HubSpot CRM ingress host:port (script may start root `docker-compose.yml` ingress) |

Optional plugin scripts:

```text
deploy/scripts/plugin-runtime-proof.sh
deploy/scripts/staging-autonomy-plugin-proof.sh
```

When `AJENDA_PROOF_PLUGIN_LANE_ENABLED=1`, `live-runtime-proof.sh` delegates to `plugin-runtime-proof.sh` after the core worker/metrics proof succeeds. The plugin lane is **not** part of the default CI release gate unless an operator enables it and supplies live provider tokens.

When `AJENDA_OPERATOR_MISSION_PROOF=1`, the proof runs
`deploy/scripts/operator-mission-proof.py`. This is the staging operator proof:
it uses onboarding and public HTTP APIs, requires a complete HVAC composition,
confirms that confirmation does not queue work, launches once through the server
authority, waits for the deployed worker, and requires exactly ten persisted,
artifact-complete prospects. It is intentionally opt-in until a real public
search provider is configured. The public identity path preserves raw directory
hits as intermediate evidence, extracts only bounded external HTTPS links, and
promotes a company only after the linked page passes the existing host/name
verification rule. A staging proof must also expose a verification code or
provide a test mailbox delivery path; production email verification remains
private.

---

## CI workflow behavior (`main` push)

The primary release gate runs automatically in `.github/workflows/ci.yml` after `integration-tests`, `migration-safety`, and `docker-build` succeed on pushes to `main`.

| Step | Behavior |
|---|---|
| Checkout | uses merged `main` commit |
| Write prod-like Compose environment | generates `deploy/compose/.env.prod` with staging-mode settings and a fresh worker tenant UUID (not committed) |
| Run live runtime proof | executes `deploy/scripts/live-runtime-proof.sh` |
| Stop compose stack | `docker compose down -v --remove-orphans` (always, even on failure) |

This job is promotion-blocking for `main`. PR branches do not run the full Compose proof unless an operator dispatches the manual workflow below.

Default CI env overrides include `AJENDA_PROOF_TIMEOUT_SECONDS=120` and `AJENDA_PROOF_POLL_SECONDS=2`.

---

## Manual workflow behavior

The manual workflow remains available for operator-driven reruns and diagnostics.

It is triggered by `workflow_dispatch` and has two modes:

| Input | Behavior |
|---|---|
| `run_live_proof=false` | run static shell syntax validation only |
| `run_live_proof=true` | run static shell syntax validation, write a generated prod-like Compose environment, execute the full live proof, capture diagnostics, and tear down the stack |

The full workflow run writes `deploy/compose/.env.prod` inside the temporary GitHub Actions workspace with staging-mode runtime settings and a generated worker tenant UUID. It does not commit that file.

The workflow uploads diagnostics on success or failure:

```text
artifacts/live-runtime-proof/compose-ps.txt
artifacts/live-runtime-proof/compose-logs.txt
```

---

## Recent validated evidence

| Workflow | Run | Commit | Result | Notes |
|---|---|---|---|---|
| CI — Pull Request Gate | #1041 | `efe332b` | success | `main` push; Live Runtime Proof passed after HubSpot ingress cert auto-generation (#338) |
| Live Runtime Proof (manual) | #3 | `ed3c665` | success | Prometheus scrape-health check included |
| Live Runtime Proof (manual) | #2 | `051271b` | success | First full GitHub-hosted Compose proof |

CI run #1041 exercised the default proof path on `main`: echo worker proof, GTM `lead_enrich`, brain capstone slice, and skipped plugin lane (no live provider tokens). HubSpot ingress image build succeeded after `generate-certs.sh` ran inside the proof script.

---

## Proof responsibilities

The script currently proves the following release-gating responsibilities.

### 1. Compose and dependency readiness

The script validates the Compose configuration, starts the prod-like services, and verifies basic dependency readiness.

Required services include:

- Postgres
- Redis
- migration service
- API
- worker
- Prometheus

Required readiness checks:

- Compose config is valid
- Postgres accepts `pg_isready`
- Redis returns `PONG`
- Prometheus readiness endpoint returns HTTP 200

### 2. Public control-plane probes

The root infrastructure probes must return successful HTTP responses:

```text
/health
/readiness
```

### 3. Versioned system probes

The versioned system probes must return successful HTTP responses:

```text
/v1/system/health
/v1/system/readiness
```

These checks prevent drift between root infrastructure probes and versioned operational system routes.

### 4. Real queue-backed worker execution

The script creates a real tenant, mission, and echo task inside the running API container, queues the task through `ExecutionCoordinator`, and waits for the worker to complete it.

Required result:

- task reaches `completed`
- task has a `worker_lease_id`
- worker lease exists
- worker lease reaches `released`

Forbidden result:

- task remains queued, claimed, or running past the proof timeout
- task reaches failed or dead-lettered terminal state during the success-path proof
- task completes without a valid released lease

### 5. Audit and lineage evidence

After worker completion, the script verifies durable evidence in Postgres.

Required evidence:

- one `task_output` lineage record for the proof task and lease
- one `task_completed` audit event for the proof task and lease

Forbidden result:

- task completion without lineage evidence
- task completion without worker audit evidence
- mismatched task, lease, tenant, or worker actor evidence

### 6. Live observability metrics

After real worker-completed work, the script fetches:

```text
/v1/observability/metrics
```

The response body must include these Prometheus metric names:

```text
ajenda_tasks_completed
ajenda_active_leases
ajenda_worker_utilization
```

This check proves that the metrics route is live after runtime work has completed and that key runtime metric families are exposed.

### 7. Prometheus scrape health

The script starts Prometheus from the prod-like Compose stack and waits for:

```text
/-/ready
```

Then it queries the Prometheus targets API and requires the configured scrape job to report healthy:

```text
/api/v1/targets?state=active
```

Required result:

- Prometheus reports the `ajenda-api` target as `up`

Forbidden result:

- Prometheus is unavailable
- the `ajenda-api` scrape target is absent
- the `ajenda-api` scrape target remains unhealthy past the proof timeout

### 8. Redis lease cleanup

The script verifies that the Redis lease key for the proof task is absent after completion.

Expected key shape:

```text
ajenda:queue:<tenant_id>:lease:<task_id>
```

Required result:

- Redis returns no value for the proof task lease key

Forbidden result:

- stale Redis lease key remains after worker completion and lease release

### 9. GTM tool.invoke proof (`gtm.lead_enrich`)

After the core echo proof succeeds, the script queues a second real task on the same proof tenant using `task_type=tool.invoke` and action `gtm.lead_enrich`.

Required result:

- task reaches `completed` within the proof timeout

Forbidden result:

- task remains queued, claimed, or running past the proof timeout
- task reaches `failed` or `dead_lettered` during the success-path proof

This lane exercises the governed tool runtime path without live external provider tokens.

### 10. Brain capstone slice

The script runs `deploy/scripts/brain-capstone-runtime-proof.py` inside the API container for the proof tenant.

Required result:

- JSON payload reports `ok: true`
- payload includes a non-empty `artifact_id`

Optional env:

| Variable | Default | Purpose |
|---|---|---|
| `AJENDA_BRAIN_CAPSTONE_SEND` | unset | When set with email credentials, also exercises optional send lane |

Forbidden result:

- capstone script reports `ok: false` or missing `artifact_id`

### 11. Optional plugin lane (not default CI)

When `AJENDA_PROOF_PLUGIN_LANE_ENABLED=1` and live provider tokens are supplied, the script delegates to `deploy/scripts/plugin-runtime-proof.sh` after the core proof lanes succeed.

This lane is **not** part of the default `main` CI gate unless explicitly enabled and credentialed.

---

## Release-gate interpretation

A successful run ends with:

```text
live runtime proof passed
```

A passing run means the prod-like stack proved the following together:

- HubSpot ingress TLS certs exist before compose build (generated when missing)
- API probes are reachable
- versioned system probes are reachable
- Postgres is ready
- Redis is ready
- queue admission works through the runtime coordinator
- worker execution completes real queued echo work
- worker lease authority reaches released state
- task output lineage is written
- worker completion audit is written
- observability metrics are exposed at `/v1/observability/metrics`
- runtime metric families include completed tasks, active leases, and worker utilization
- Prometheus is ready
- Prometheus reports the configured `ajenda-api` scrape target as healthy
- Redis lease cleanup succeeds
- GTM `gtm.lead_enrich` tool.invoke task completes
- brain capstone slice returns `ok: true` with `artifact_id`

Any script failure is promotion-blocking for the environment being proven (including the automatic `main` CI job).

---

## Validation commands

Static shell validation:

```bash
bash -n deploy/scripts/live-runtime-proof.sh
```

Full prod-like proof:

```bash
./deploy/scripts/live-runtime-proof.sh
```

Manual GitHub Actions static validation:

```text
Live Runtime Proof workflow with run_live_proof=false
```

Manual GitHub Actions full proof:

```text
Live Runtime Proof workflow with run_live_proof=true
```

The full proof requires a valid prod-like environment and should not be treated as equivalent to a local unit or contract test.

---

## Matrix relationship

This proof overlaps multiple release-gating rows in `docs/validation/live-runtime-matrix.md`, especially:

| Matrix row | Relationship |
|---|---|
| `RG-01` | root health/readiness probes |
| `RG-02` | versioned system health/readiness probes |
| `RG-03` | metrics route exposure and Prometheus scrape health |
| `RG-04` | queue admission for tenant-scoped work |
| `RG-06` | queued task completion, released lease, audit/log evidence |

The script is not a replacement for the full matrix runner. It is an additional prod-like release proof that validates the deployed service graph end to end.

---

## Maintenance rules

When `deploy/scripts/live-runtime-proof.sh` changes, update this document if the proof contract changes.

When `.github/workflows/live-runtime-proof.yml` changes, update this document if workflow invocation or evidence behavior changes.

Do not document checks here unless the script or workflow actually performs them.

Do not mark new proof responsibilities as release-gating until the script or matrix runner provides evidence for them.
