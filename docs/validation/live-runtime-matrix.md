# Ajenda AI Live Runtime Validation Matrix

## Purpose

This matrix is the **single point of truth** for runtime validation in Ajenda AI. It converts the repo/runtime contract into executable validation scenarios.

- **Release-gating set:** 12 scenarios (RG-01..RG-12) must pass before any release.
- **Broader runtime set:** 28 total scenarios grouped by control/auth/execution/failure/dead-letter/integrity/observability/compliance planes.
- **Evidence contract:** every scenario defines API result + DB + queue + audit (+ worker logs when applicable).

## Safety classes

- `SAFE_READ_ONLY`: no mutation.
- `TENANT_SCOPED_MUTATION`: mutation scoped to one tenant.
- `GLOBAL_MUTATION`: cross-tenant mutation (isolated environment only).

## Validation method legend

- `contract-test`: under `tests/contract/`
- `integration-test`: under `tests/integration/`
- `runner`: scripted in `scripts/validation/live_runtime_matrix.sh`

---

## Release-gating scenarios (12 required)

| ID | Route/method | Owner (file::function) | Auth + tenant | Side effect | Expected API | Expected DB | Expected queue | Expected audit/log evidence | Validation method | Implementation |
|---|---|---|---|---|---|---|---|---|---|---|
| RG-01 (Health) | `GET /health`, `GET /readiness` | `backend/api/routes/health.py::health, readiness` | Public (no auth, no tenant) | `SAFE_READ_ONLY` | 200 + `{"status":"ok|ready"}` | none | none | none | contract-test | `tests/contract/api/test_release_gating_routes.py::test_rg_health_root_probes_public` |
| RG-02 (System status) | `GET /v1/system/health`, `GET /v1/system/readiness`, `GET /v1/system/status` | `backend/api/routes/system.py::{system_health,system_readiness,system_status}` | health/readiness public; status requires valid auth + tenant | `SAFE_READ_ONLY` | 200 on public probes; `/status` rejects invalid envelope | `/status` returns tenant-scoped aggregates | none | none | contract-test | `tests/contract/api/test_release_gating_routes.py::test_rg_system_status_envelope` |
| RG-03 (Metrics) | `GET /v1/observability/metrics` | `backend/api/routes/observability.py::metrics` | Public | `SAFE_READ_ONLY` | 200 text/plain Prometheus exposition | read counts only | none | none | contract-test | `tests/contract/metrics/test_metrics_route_access.py::test_rg_metrics_route_public_and_prometheus_text` |
| RG-04 (Queue admission) | `POST /v1/tasks/{task_id}/queue` | `backend/api/routes/task.py::queue_task`, `backend/services/execution_coordinator.py::queue_task` | valid auth + tenant | `TENANT_SCOPED_MUTATION` | 200 `{task_id,state=queued}` | `planned->queued` | pending enqueue entry exists | `audit_events.action='queued'` | integration-test | `tests/integration/runtime/test_release_gating_runtime_real.py::test_rg_queue_admission_end_to_end` |
| RG-05 (Invalid envelope) | tenant-facing routes, e.g. `POST /v1/tasks/{id}/queue` | `backend/middleware/{tenant_context,auth_context}.py` | missing/invalid tenant or auth rejected | `SAFE_READ_ONLY` (on failure) | 400/401/403 as applicable | no mutation | no enqueue | no audit side-effects | contract-test | `tests/contract/api/test_tenant_isolation_policy.py` |
| RG-06 (Happy execution) | worker flow from queue claim to completion | `backend/services/worker_runtime_service.py::{claim_next_task,start_execution,complete}` | worker tenant context | `TENANT_SCOPED_MUTATION` | n/a (service path) | `queued->claimed->running->completed`; lease claimed->active->released | processing removal + lease key removal | `audit_events.action='task_completed'`, worker loop logs | integration-test + runner | `tests/integration/runtime/test_release_gating_runtime_real.py::test_rg_happy_execution_flow` + runner `RG-06` |
| RG-07 (Forced failure) | deterministic failure path (`task_type=force_fail`) | `backend/workers/task_dispatcher.py::force_fail_handler`, `worker_runtime_service.fail` | worker tenant context | `TENANT_SCOPED_MUTATION` | n/a (service path) | task enters `failed` (or dead-letter terminal per retry path) | dead-letter envelope added | `audit_events.action='task_failed'`, worker log failure markers | integration-test + runner | `tests/integration/runtime/test_release_gating_runtime_real.py::test_rg_forced_failure_path` + runner `RG-07` |
| RG-08 (Claimed recovery) | `POST /v1/operations/recovery` | `backend/services/runtime_maintainer.py::recover_expired_leases` | public (global control) | `GLOBAL_MUTATION` | 200 summary counts | stale claimed `claimed->queued`, lease->expired | task re-enqueued | audit `claimed_task_requeued_on_lease_expiry` | integration-test + runner | `tests/integration/runtime/test_release_gating_runtime_real.py::test_rg_claimed_recovery` + runner `RG-08` |
| RG-09 (Running recovery) | `POST /v1/operations/recovery` | `runtime_maintainer.recover_expired_leases` | public (global control) | `GLOBAL_MUTATION` | 200 summary counts | `running->recovering->queued` with retry++, or `->dead_lettered` on exhaustion | requeue only if retries remain | audit recovery rows | integration-test + runner | `tests/integration/runtime/test_release_gating_runtime_real.py::test_rg_running_recovery_and_retry_exhaustion` + runner `RG-09` |
| RG-10 (Dead-letter retry legality) | `POST /v1/operations/dead-letter/{task_id}/retry` | `backend/services/operations_service.py::retry_dead_letter` + state machine | auth + tenant | `TENANT_SCOPED_MUTATION` | 400 when illegal transition attempted | remains `dead_lettered` | no enqueue | no retry audit on failure | contract-test + integration-test | `tests/contract/operations/test_dead_letter_retry_contract.py` + `tests/integration/operations/test_dead_letter_retry_real.py` |
| RG-11 (Recovery safety) | `POST /v1/operations/recovery` | `operations.py::trigger_recovery`, `runtime_maintainer` | public global endpoint | `GLOBAL_MUTATION` | 200 summary | only stale leases mutate; healthy tenants/tasks unchanged | only affected stale tasks re-enqueue | recovery audit only for mutated tasks | integration-test + runner | `tests/integration/runtime/test_release_gating_runtime_real.py::test_rg_recovery_safety_only_stale_mutates` + runner `RG-11` |
| RG-12 (Pending review) | `POST /v1/tasks/{task_id}/queue` (policy deny case) | `execution_coordinator.queue_task`, `policy_guardian.evaluate_task` | auth + tenant | `TENANT_SCOPED_MUTATION` | 400 with policy reason | `planned->pending_review`, `requires_human_review=true` | no enqueue | compliance audit + governance event | integration-test + runner | `tests/integration/runtime/test_release_gating_runtime_real.py::test_rg_pending_review_policy_gate` + runner `RG-12` |

---

## Broader runtime scenarios (28 total)

### Control plane

1. CP-01: root liveness `GET /health` (public, 200).
2. CP-02: root readiness `GET /readiness` validates DB path.
3. CP-03: system health route is public.
4. CP-04: system readiness route is public.
5. CP-05: metrics route returns Prometheus text and includes `ajenda_up`.

### Auth + tenant envelope

6. AT-01: missing `X-Tenant-Id` rejected 400 on tenant-scoped route.
7. AT-02: invalid tenant UUID rejected 400.
8. AT-03: missing auth rejected 401.
9. AT-04: cross-tenant principal rejected 403.
10. AT-05: public health/readiness/recovery remain accessible without envelope.

### Execution plane

11. EX-01: single-task queue admission queued + audit.
12. EX-02: queue admission blocked when task missing/wrong tenant.
13. EX-03: mission queue mixed results (queued + pending_review) verified by DB not only response.
14. EX-04: claim creates lease + metadata worker_lease_id.
15. EX-05: start execution transitions claimed->running.
16. EX-06: complete transitions running->completed and removes processing payload.
17. EX-07: duplicate active-lease claim rejected.

### Failure + retry plane

18. FR-01: forced failure transitions to failed + dead-letter envelope.
19. FR-02: stale claimed lease recovery claimed->queued.
20. FR-03: stale running lease recovery with retry increment.
21. FR-04: stale running with retry exhaustion to dead_lettered.
22. FR-05: recovery idempotency: second pass no double increment on already-resolved lease.

### Dead-letter plane

23. DL-01: dead-letter inspection lists tenant-specific rows only.
24. DL-02: dead-letter retry legality enforced (400, unchanged DB/queue).

### Integrity plane

25. IN-01: no duplicate active lease for same task.
26. IN-02: queue/DB coherence check after completion (no processing leftovers).
27. IN-03: recovery does not mutate healthy leases/tasks.

### Observability plane

28. OB-01: worker happy-path logs + `task_completed` audit.

### Compliance plane

29. CO-01: policy denial leads to pending_review + governance + no enqueue.

### Implemented in runner with direct DB/Redis/audit evidence (minimum six)

The runner implements direct checks (API + DB + Redis + audit) for:

- RG-04 queue admission
- RG-06 happy execution
- RG-07 forced failure
- RG-08 claimed recovery
- RG-09 running recovery
- RG-12 pending review

(Plus read-only checks RG-01..RG-03 and recovery safety RG-11.)

Runner hardening notes:

- Unknown `--scenario` values are rejected at argument-parse time (usage + non-zero exit) to prevent no-op green summaries.
- RG-02 validates missing-tenant and missing-auth branches deliberately; missing-auth assertion is only executed when a tenant value is available.
- RG-06 only passes when required evidence files are present/non-empty and the task-state evidence includes `completed`.
- RG-07 only passes when required evidence files are present/non-empty and the task-state evidence includes `failed` or `dead_lettered`.
