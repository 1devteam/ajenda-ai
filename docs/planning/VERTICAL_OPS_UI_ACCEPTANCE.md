# Vertical operations UI acceptance

## UPG/LAP review (before implementation)

- Responsibility: collect template-specific planning inputs, select an existing
  tenant connection, submit a non-queued mission, and review its saved graph.
- Sources of truth: `plan_templates.py` default steps; `template_service.py`
  input/credential/idempotency validation and planned-task persistence;
  `tools/schemas.py` Research and Social inputs; `gtm_actions.py` Social credential
  requirement; `credentials/runtime_authority.py` credential scope checks;
  `api/routes/mission.py` tenant-scoped lifecycle graph; `middleware/idempotency.py`.
- Dependencies: existing vertical template/create APIs, credential list API,
  lifecycle GET, authenticated client, current template cards and Vitest setup.
- Pitfalls: missing/blank/oversized input, unsupported default actions, revoked or
  wrong-tenant credentials, credential-list failure, double submission, stale
  responses after tenant/navigation changes, ambiguous network errors, and a
  review link that recompiles the saved template through the composition UI.
- Invariants: create always sends `queue: false`; no new runtime admission path;
  credentials come from the active tenant and contain references only; backend
  permission, charter, quota and credential gates remain authoritative; retries
  of an unchanged form reuse HTTP and Social action keys; review reads saved data
  and cannot compile, approve or queue work; stale tenant data is discarded.
- Proof: rendered component tests for payloads, validation, credential filtering,
  errors, retries, duplicate clicks, tenant switches and read-only review; API
  request tests for idempotency header and forced non-queueing; backend bundle
  parity proof; existing route/runtime tests; frontend build and repository gates.

## Explicit boundaries

Self-service Social setup now accepts a tenant-owned API key through the
Connections page. It requires an explicit hostname and defaults the credential
scope to `gtm.social_publish` plus `external_publish`; platform-master Social
credentials remain forbidden. A LinkedIn read connection is not publish
authority. No external publish or send is performed during validation.

Review uses the persisted lifecycle graph. The general mission execution page
recompiles graphs, so it is not used as the template review handoff. Execution
controls and migration changes are outside this UI fix.

## Implementation and evidence

- `VerticalOpsPage.tsx` collects Research query and Social platform/content,
  filters existing publishing connections by tenant/status/provider/type/scope,
  and isolates drafts and pending results across workspace changes.
- `verticalOps/planModel.ts` binds only server-default steps. Unsupported runtime
  input forms fail closed. Existing Email, Finance, Ads and Code defaults remain
  accepted by backend validation.
- `api/client.ts` always sends `queue: false` and now supplies the existing HTTP
  idempotency middleware with a key reused by unchanged-form retries. The Social
  task receives a stable action key as well. Keys last for the mounted draft;
  cross-reload draft recovery and provider exactly-once delivery are not claimed.
- `VerticalPlanReview.tsx` uses the tenant-scoped lifecycle GET and renders saved
  graph inputs. It rejects mismatched mission/tenant data and ignores late reads.
- Component tests exercise the real authenticated client with mocked HTTP:
  required/oversized inputs, credential filtering, failed reads, duplicate
  submits, retries, tenant switches, stale review responses, and GET-only review.
- New Postgres integration tests verify both Research and Social inputs survive
  commit/reload and lifecycle projection, remain planned, preserve Social review
  requirements and credential/idempotency references, and produce no queue keys.

Validation on the changed tree:

- Frontend: 62 tests passed; `npm run build` passed.
- Integration: both new persistence tests and the existing Research
  queue/lease/dispatcher/evidence proof passed (3 tests).
- Actual frontend builder requests for all six server templates were validated
  with `VerticalTemplateCreateMissionRequest` and `build_bundle`: all passed.
- Ruff check/format, mypy, contract drift, runtime authority inventory, migration
  seed contract and ability rollout checks passed.
- Full backend gate: `python -m pytest tests/unit/ tests/contract/ tests/deployment/
  -m "not integration" --timeout=45` passed: 2,833 passed, 1 deselected (200.65s).
- No migration round-trip: no schemas, migrations or backend runtime code changed.
- No live browser/production mutation or external publish was performed; the
  integration environment was isolated. No deployment was performed.

The Social credential lane was subsequently added in `b48eeba` and validated
with focused management, route, and runtime-authority tests plus the full gate.

## Local Compose deployment — 2026-09-10

Deployed the validated frontend to the existing `ajenda-ai` Compose project on
port 8080 using `docker compose ... build frontend` followed by
`docker compose ... up -d --no-deps frontend`. The production Docker build used
the lockfile-backed dependency layer and passed TypeScript/Vite compilation.
API, worker, database and queue services were not recreated.

Evidence:

- Frontend image: `sha256:4c921f327e47bba5e1c937dc1ed34dede91896eb625aab66a682abb4f49280da`.
- Container health: `healthy`.
- `/vertical-ops?mission=deployment-smoke` serves the SPA with
  `index-Coi31sEx.js`; the served bundle includes Research input and saved-plan
  review UI.
- `/health` and `/readiness` succeed through the frontend's API proxy.
- These are deployment smoke checks, not an authenticated browser journey.
  No live mission was created and no external publish/send was performed.
