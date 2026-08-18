# End-to-end findings verification — `main@7ccadea`

**Audit date:** 2026-08-16  
**Audited revision:** `7ccadea5a9da7700ccf9b0ccd6087c027bff9a12`  
**Mainline identity:** merge commit for GitHub PR `#434` on `main`
**Method:** static implementation, migration, deployment, frontend, and test inspection, plus
targeted executable checks. Product documentation was used only to identify claimed contracts,
never as proof of runtime behavior.

## Executive decision

The submitted system map is substantially accurate. Its central conclusion is supported: the
repository implements a tenant-scoped API, queue/lease worker execution, evidence-producing
registered tools, signed/deduplicated Stripe ingress, and a durable Knowledge ledger; it does not
prove that every documented product or control-plane loop is safe or closed.

The audit also overstates a few points. Most importantly, absence of RLS is a missing
defense-in-depth control, not by itself proof of an exploitable cross-tenant query; Redis worker
identity is enforced by the database lease even though it is not independently enforced by Redis;
and `knowledge.record_qualification` is an explicit low-level persistence action while the newer
canonical consolidation path does reconstruct durable learning-signal history. These nuances do
not remove the associated risks.

Verdict labels in this report mean:

- **Confirmed** — the described behavior follows directly from the inspected code/schema.
- **Confirmed with qualification** — the core fact is true, but scope, impact, or wording needed
  correction.
- **Not established** — the cited files do not prove the stronger claim.
- **Disproved** — implementation contradicts the claim.

## UPG review and audit boundaries

- **Responsibility:** verify the supplied findings, not remediate them.
- **Sources of truth:** route dependencies and middleware, service/repository call chains, worker
  and queue adapters, Alembic migrations, frontend routing/storage, deployment manifests, and
  executable tests.
- **Dependencies traced:** HTTP tenant/auth/RBAC context; admission/governor/policy; queue claim,
  lease, dispatch, terminal persistence; action authority/evidence; Stripe receipts; Knowledge
  persistence/retrieval; browser credential handling; exposed network surfaces.
- **Pitfalls:** a static path may be unreachable through production configuration; a missing DB
  policy does not prove an unscoped query; handler-level idempotency differs by provider; unit tests
  with injected state can bypass middleware; direct registry tests do not prove queue authority.
- **Invariants checked:** tenant scope, authorization, queue/lease authority, fail-closed behavior,
  replay safety, evidence persistence, and migration parity.
- **Proof boundary:** no live Stripe/provider delivery, browser exploit, Redis race, or production
  cluster was exercised. Such exploitability/operability claims remain runtime follow-ups.

### Corrected evaluation method — 2026-08-18

The original audit was too dependent on manually selected call-chain reading. Documentation and
tests were used as claimed-contract and proof indexes, but the repository did not have a
machine-enforced inventory of concrete runtime-authority sinks. That process allowed the shared
dispatcher/tool engine to be mistaken for one current claim/start/run authority even though the
HTTP mission bridge independently mutates and executes runtime state.

The corrected progressive method is:

1. Enumerate production `backend/` call sites for admission, direct queue enqueue, queue claim,
   runtime claim/start, dispatcher execution, direct tool-handler calls, and action-registry
   invocation using `scripts/validation/runtime_authority_inventory_check.py`.
2. Classify every observed call site as canonical boundary, canonical daemon spine, competing HTTP
   spine, or explicit exception/bypass, with a remediation disposition. Unknown, moved, duplicated,
   or removed sinks fail closed until reconciled.
3. Trace each classified sink forward to state mutation, queue behavior, lease ownership,
   dispatcher/tool execution, terminal persistence, evidence, audit, retry, and recovery; trace it
   backward to every HTTP, worker, scheduler, or maintenance producer.
4. Treat tests as proof only for the exact exercised path. Direct handler/registry tests are not
   production runtime proof; docs and ledger entries are not implementation proof.
5. Run race/fault scenarios for every pair of state-changing authorities before claiming
   convergence. Static inventory proves topology and drift, not race safety.

The sentinel is now a CI gate. It currently reports the daemon spine, the competing HTTP
worker-run queue/dispatcher spine, normal authority boundaries, and known exception bypasses. This
does not remediate the split; it prevents another authority sink from being silently missed while
PR-07/PR-08 perform convergence.

## 1. HTTP edge and authentication

| Finding | Verdict | Verification |
|---|---|---|
| Middleware order is SecurityHeaders → CORS → Tenant → Auth → Idempotency → RateLimit → RequestContext. | **Confirmed** | Registration is reversed by Starlette, and `main.py` registers exactly this stack. |
| Tenant header/UUID/status/DB failures and cross-tenant auth fail as described. | **Confirmed** | Tenant middleware returns 400/403/404/503; auth compares the resolved principal tenant with request tenant. |
| `/v1/admin` is public to middleware and live handlers therefore lack an attached principal. | **Confirmed** | The public prefix bypasses both tenant and auth middleware, while `_require_admin` reads `request.state.principal`. Unit route tests inject that state and therefore do not prove the live middleware path. This is a dead control plane, not an unauthenticated write. |
| `/v1/observability/metrics` is public and cluster-wide. | **Confirmed** | It is a public prefix and the metrics handler uses the unscoped DB dependency and global task/lease queries. |
| Tenant-authenticated `/operations/recovery` performs global recovery. | **Confirmed** | The route intentionally uses `get_db_session`; `RUNTIME_OPERATE` is tenant-authorized, but `RuntimeMaintainer.run_recovery_cycle()` scans expired leases without restricting the initiating tenant. |
| Tenant validation and API-call quota skip if `database_runtime` is absent. | **Confirmed with qualification** | This is explicit middleware behavior intended for lifespan-free tests. Normal lifespan startup always installs the runtime, so the production risk is mis-wiring/test-host construction rather than an ordinary configured request. |
| Comment claiming all `/v1/auth/*` is public is false. | **Confirmed** | The shared allowlist exposes only OIDC-prefixed routes and session refresh; `/me` and logout remain protected. |

## 2. Customer signup, billing, and launch

| Finding | Verdict | Verification |
|---|---|---|
| Email verification always returns a live 72-hour bootstrap API key. | **Confirmed** | `VerifyEmailResponse.api_key` is required, verification creates a `signup_bootstrap` key, and the route returns it regardless of `signup_expose_verification_token` (that setting controls only the verification token). |
| A bootstrap principal can queue read-safe ability work on the free plan. | **Confirmed** | The role includes `EXECUTION_QUEUE`; the launcher gates `ability_runtime` only for external actions or actions needing runtime side-effect authority. Read-safe actions bypass that feature check. |
| Signup/resend disclose whether an email exists. | **Confirmed** | Existing/pending signup returns distinct 409 messages and resend returns a distinct 404. |
| Invalid verification guesses avoid the per-email verify-failure gate and require an Argon2 scan of pending members. | **Confirmed** | Token resolution iterates pending token hashes before an email identity exists; the email failure check occurs only after a member match. Edge IP throttling still applies, so “unlimited brute force” would be inaccurate. |
| `ability_runtime` is not a universal paid launch gate. | **Confirmed** | Internal/read-safe launches can execute without it; the paid-loop calendar-read proof therefore does not prove the premium feature boundary. |
| Unknown plans fail open. | **Confirmed** | quota methods return when the plan row is absent and `FeatureFlagService.is_enabled()` returns true. |
| Most seeded feature strings and `max_concurrent_workers` are stored but unenforced. | **Confirmed with qualification** | Repository-wide `require_feature` call sites cover only a subset of seeded features, and no runtime admission uses `max_concurrent_workers`. This is contract drift, not proof every unused feature was intended as an active gate. |
| `invoice.payment_failed` does not suspend or downgrade a tenant. | **Confirmed** | Stripe processing records/logs the event without changing tenant plan/status. |
| A non-retryable Stripe processing failure can leave a `processing` receipt that deduplicates later delivery. | **Confirmed** | Receipt insertion precedes handling; non-retryable outcomes are acknowledged without a terminal receipt update on the relevant error path. This needs an integration fault-injection proof before quantifying real Stripe loss frequency. |
| Billing portal accepts an unconstrained `return_url`. | **Confirmed** | The route passes the query value through to Stripe without an application-origin allowlist. Stripe may impose its own validation, but the application does not. |
| Browser session material and full API keys are in `sessionStorage`; `/dev` is not protected. | **Confirmed** | Session serialization includes access/refresh tokens or the full API key. `/dev` is outside `ProtectedRoute` and its console supports launch/billing configuration. This increases XSS impact; storage alone is not proof an XSS primitive currently exists. |

## 3. Queue, lease, dispatch, and recovery authority

| Finding | Verdict | Verification |
|---|---|---|
| Normal task admission uses `ExecutionCoordinator`; review approval and dead-letter retry are exceptions. | **Confirmed** | Normal routes call coordinator admission. Approval calls the coordinator's separate enqueue method, while dead-letter retry can enqueue from DB metadata. |
| HTTP worker claim/start is a second state-transition spine that does not claim the queue payload. | **Confirmed** | Mission-bridge claim/start creates DB admission/lease state and explicitly declares `enqueues_work=False`; daemon claim remains independently able to move the queued message. |
| Redis terminal/heartbeat operations do not independently validate `worker_id`. | **Confirmed with qualification** | Redis adapter methods key by tenant/task, unlike the local adapter's worker claim map. `WorkerRuntimeService` still enforces DB lease ownership, so “no ownership enforcement” would be false; this is queue-level asymmetry and split-brain exposure. |
| Review approval and dead-letter retry bypass the governor/policy admission evaluation. | **Confirmed** | Only `queue_task()` evaluates governor and guardian. `approve_review_and_queue()` transitions/enqueues directly; `OperationsService.retry_dead_letter()` reconstructs/enqueues without those gates. |
| Operational `requires_human_review` can be ignored by policy. | **Confirmed** | Policy derives review from compliance categories and does not universally hold a task merely because the boolean is true. Ability/GTM operational tasks can therefore carry the flag without entering pending review. |
| Governor never produces restricted/recovery behavior and permits execution on failed health. | **Confirmed with qualification** | Current evaluation returns normal/degraded semantics and health degradation does not itself deny execution; forced restriction is not wired into the evaluated path. The system can still deny for other policy/runtime reasons. |
| Recovery is an operator HTTP operation, not a queued worker job. | **Confirmed** | The recovery route invokes maintainer logic synchronously; the legacy `LeaseManager`/`RetryPolicy` abstractions are not its authority path. |
| Runtime recovery can replay an external mutation after a crash between provider success and completion. | **Confirmed** | Expired running tasks are requeued without a runtime-wide external-effect receipt. SMTP and `web.open_write` have durable claims, but several provider writes rely on provider/header idempotency or have no durable claim. Exact duplication depends on provider behavior. |
| Ability launch directly sets mission `RUNNING`. | **Confirmed** | The launch path assigns status rather than using the mission transition helper. |
| Unknown task types complete through the default handler. | **Confirmed** | Dispatcher falls back to the registered `default` handler, which returns completed without tool execution. |
| Route rollback after queue success can orphan a pending queue message. | **Confirmed** | enqueue occurs after a DB flush but before route commit; later transaction failure does not retract the queue item. Maintainer reconciles processing/leases, not every pending-message/DB-state mismatch. |

### Runtime-authority topology addendum — 2026-08-18

The earlier wording needs a more exact distinction between **execution engine** and **runtime
authority entry point**:

1. **Daemon worker spine:** `WorkerLoop` calls `WorkerRuntimeService.claim_next_task()`, which claims
   the tenant queue payload, creates/owns the DB lease, starts the task, and invokes
   `TaskDispatcher`.
2. **HTTP mission-bridge spine:** worker-claim and worker-start admission services independently
   mutate task/lease state under a synthetic mission-scoped holder. Worker-run admission then calls
   `QueueAdapter.claim_existing_task()` and invokes `TaskDispatcher` synchronously inside the API
   request.

They share the same `ExecutionTask`, queue adapter, DB lease model, dispatcher, tool runtime
authority, and terminal persistence. Therefore they are **not two completely separate execution
engines**, but they **are two competing runtime-authority/control spines** for claim, start, and run.
The bridge's delayed queue claim narrows the original statement that it “never claims the queue,”
but it does not remove the race: a daemon may claim the already-admitted payload before the HTTP
run stage, while HTTP claim/start has already changed DB state and lease ownership.

The “Ajenda Brain” is **not a third runtime authority** in production code. `BRAIN_MISSIONS` is a
fixed demonstration/readiness catalog, `brain_capability_check` reads profile/credential/charter
state, and `ajenda_brain` is primarily a provider/provenance label on registered actions. Brain
actions launched through ability/runtime tasks use the same dispatcher and `ToolRuntimeAuthority`
as other actions. Some standalone and Knowledge tests call `ActionRegistry.invoke()` or the
`tool_invoke_handler` directly; those are test harnesses and do not establish a production Brain
worker, queue, lease, scheduler, or runtime authority.

**Corrected verdict:** RUN-01 remains confirmed, but its precise form is “two competing
claim/start/run authority spines converging on one dispatcher/tool execution engine.” PR-08 must
remove the competing ownership/state-transition path, not create a third runtime or merely rename
either existing path.

### Swarming/workforce capability addendum — 2026-08-18

Ajenda currently has **workforce nouns, not swarming behavior**:

- `WorkforceProvisioner` persists a fleet and agent rows, transitions them to ready/provisioned,
  and emits membership lineage/audit records.
- `WorkforceCoordinator.assign_task_to_agent()` only writes `assigned_agent_id` after a tenant
  check. It does not schedule the task, coordinate dependencies, exchange artifacts, enforce the
  agent's declared role, manage parallelism, aggregate results, or enter runtime admission.
- Fleet/agent state machines and quotas exist, but no worker loop consumes agent identity, no swarm
  coordinator advances a fleet, and no end-to-end test proves multiple agents collaborating on a
  mission.

The repository therefore does not support a claim of agent swarming, multi-agent collaboration, or
fleet execution. A safe future swarm must remain an orchestration/control-plane projection over
the canonical task graph and queue/lease runtime; agent records must never become independent
executors or runtime authorities.

## 4. Tools, external effects, and credentials

The executable registry contains **48 canonical actions** (51 names including aliases), matching
the submitted count.

| Finding | Verdict | Verification |
|---|---|---|
| Successful actions require evidence; credentials and production simulation fail closed as described. | **Confirmed** | Registry result validation requires evidence and matching tenant/task/mission. Runtime credential authority rejects missing requirements, and production external simulation is disabled. |
| Ability launch creates capability/adapter/side-effect authorization records for its own task. | **Confirmed with qualification** | The records are real authorization artifacts and are later revalidated, but their launch authority is derived from the same request path. High-risk GTM actions have additional guardian/autonomy/idempotency checks; the weakness is broader self-issuance, not total absence of authorization. |
| Mission materialization can server-mint side-effect authorization. | **Confirmed** | Runtime projection defaults `approved_by` to `server:runtime_task_materialization`, enabling graph-materialized writes without a human principal when upstream materialization authority accepts them. |
| `http.request` writes permit arbitrary public HTTPS when `allowed_hosts` is empty and lack a durable effect claim. | **Confirmed** | URL safety blocks private/unsafe destinations, but an empty allowlist is unrestricted among vetted public HTTPS hosts; write methods have no durable claim-before-send. |
| `webhook.dispatch` creates a new delivery/POST per invocation rather than a durable once-only effect. | **Confirmed** | Delivery records are attempts; migration and service behavior explicitly permit new rows/retries. The idempotency comment does not establish exactly-once delivery. |
| `sales.research` can label internal fallback output as real. | **Confirmed** | Unless external CRM is required, fallback output retains the `real` indicator despite not proving an external provider response. |
| Google Contacts OAuth has no registered action. | **Confirmed** | Credential/token/API routes exist, but the default action registry registers no Google Contacts action module. |
| `gtm.social_publish` lacks a concrete production plugin contract and defaults to an example host. | **Confirmed** | The default target is `api.social.example.com`; no provider plugin establishes production delivery. |
| Intelligence actions omitted from ability `EXPOSED_ACTIONS` can still execute from a queued `tool.invoke`. | **Confirmed** | `EXPOSED_ACTIONS` limits only the product launcher. Dispatcher/runtime authority resolves any registered action when a valid task reaches `tool.invoke`. |

## 5. Route-level RBAC

| Finding | Verdict | Verification |
|---|---|---|
| Workforce provision and branch create lack handler permission checks. | **Confirmed** | Neither mutation calls `require_route_permission`, despite `PROVISION_WORKFORCE` existing. |
| Webhook mutations are available to any authenticated tenant principal. | **Confirmed** | Register/delete/test mutations have tenant dependencies but no permission gate. A viewer can therefore register an endpoint and receive its one-time secret. |
| Listed governance/runtime/plugin GETs generally lack per-handler RBAC. | **Confirmed with qualification** | Middleware still requires a valid tenant principal and repositories are tenant-scoped. The issue is least-privilege inside a tenant, not public disclosure or cross-tenant access by itself. |

## 6. RLS and persistence

**Confirmed:** the original RLS migration enables and forces RLS on its enumerated runtime tables;
later capability, adapter, evidence, outcome-review, retrieval, plan/profile, credential, CRM, and
Knowledge tables add forced RLS.

**Confirmed:** migrations do not enable/force RLS for `webhook_endpoints`, `webhook_deliveries`,
`tenant_members`, `customer_auth_sessions`, `oidc_login_intents`,
`email_send_idempotency_receipts`, `mission_composition_proposals`, `tenant_usage`, or
`audit_events`. The audit-event exception is documented as intentionally cross-tenant.

**Qualification:** this proves missing database-enforced tenant isolation, but not an existing
cross-tenant exploit. Each repository query must also be audited for a missing/misbound tenant
predicate. The absence is still a high-impact invariant gap because one future app-layer mistake
would not be contained, and table-owner behavior makes `FORCE ROW LEVEL SECURITY` material.

## 7. Intelligence and Knowledge loop

| Finding | Verdict | Verification |
|---|---|---|
| Intelligence is implemented as registered actions and grants no execution authority. | **Confirmed** | Decision, analysis, retrieval, and Knowledge handlers return results/evidence or write their own ledger; they do not enqueue runtime work or mint external side-effect authority. |
| `OutcomeReview` is separate from `OutcomeEvaluation`. | **Confirmed** | Outcome-review routes/repository persist governance CRUD JSON; `analysis.evaluate_outcome` validates caller input and does not consume those rows. |
| Retrieval contracts are separate from Knowledge retrieval. | **Confirmed** | The Knowledge candidate repository uses its own durable ledger path; retrieval-contract CRUD is not the query authority. The JSONB GIN index supports candidate discovery, so saying hybrid search “does not use the Knowledge index” is directionally true only for the separate retrieval-contract/hybrid-search implementation. |
| Outcome evaluation measurements are caller-supplied. | **Confirmed with qualification** | The evaluator validates chronology/shape and emits canonical evidence, but does not independently observe the outcome values. Later episode materialization reconstructs durable artifacts and rejects contradictory lineage; it does not retroactively make the measurements externally observed. |
| Applicability depends on canonical source-observation condition semantics. | **Confirmed** | Applicability reconstructs canonical evidence and requires `SOURCE_OBSERVATION` lineage plus typed condition observations. `record.read` is the currently registered producer of those semantics. |
| `knowledge.record_qualification` can persist a caller-authored qualification. | **Confirmed with qualification** | The action accepts a validated `KnowledgeQualificationResult` and writes it directly. However, `knowledge.consolidate_learning_history` is now the canonical history path and reconstructs qualifications from durable learning signals. The low-level action remains a bypass surface and tests use it for seeding. |
| There is no autonomous scheduler that closes the entire loop. | **Confirmed with qualification** | The head revision adds bounded temporal advancement within decision-episode/Knowledge composition, but no scheduler automatically queues every next action. Advancement still requires an explicitly queued `tool.invoke`. |
| There is no public Knowledge HTTP API. | **Confirmed** | Knowledge is action/repository-backed; no Knowledge router is mounted. |
| Some Knowledge integration tests call `ActionRegistry` directly rather than worker authority. | **Confirmed** | Consolidation/decision-support tests exercise registry/service integration directly. Queue-backed proof exists for canonical decision materialization and source observation, not for every Knowledge stage end to end. |

## 8. Frontend and deployment

| Finding | Verdict | Verification |
|---|---|---|
| Compose exposes both nginx `:8080` and API `:8000`. | **Confirmed** | Both services publish host ports, so direct API access bypasses nginx routing (but not API middleware). |
| K8s ingress exposes all `/v1` routes. | **Confirmed** | Prefix routing sends `/v1` to the API, including intentionally public and accidentally weak surfaces. |
| Product and marketing route inventory is substantially accurate. | **Confirmed** | The SPA defines the listed customer pages, public marketing pages, and unprotected `/dev` route. |

## Corrected severity decision

### Release blockers for a stranger-facing production API

1. Public, unscoped operational metrics.
2. Live bootstrap execution credential returned by public verification plus read-safe free launch.
3. Missing RBAC on webhook/workforce/branch mutations.
4. Browser-held bearer/API credentials combined with an unprotected operational dev console.
5. Missing DB-enforced isolation on security- and tenant-sensitive tables (exploitability requires
   repository/runtime proof, but the invariant is absent).
6. Replay-unsafe external mutations and no runtime-wide exactly-once/claim contract.
7. Tenant principal capable of triggering global recovery.

### High-priority contract/control-plane gaps

1. Admin live-auth path is unreachable.
2. Paid `ability_runtime` gate is partial and its current proof uses an ungated read.
3. HTTP bridge claim/start and daemon queue claim are competing authorities.
4. Review approval/dead-letter retry skip normal admission gates.
5. Human-review intent is not universally enforced.
6. Stripe payment failure and receipt terminalization are incomplete.
7. Unknown plans fail open.
8. Default dispatcher silently completes unknown task types.

### Product completeness gaps

1. Review/evaluation and retrieval-contract/Knowledge concepts are distinct, not joined products.
2. The intelligence loop has bounded composition but does not autonomously schedule its next stage.
3. There is no Knowledge HTTP surface.
4. Compose exposes the API beside nginx.
5. Workforce fleets and agent assignments do not implement swarming, collaboration, or fleet
   execution.

## Claims supported at this revision

Safe claims are narrower than the project specification: tenant-authenticated HTTP APIs;
queue-backed worker execution with DB lease ownership; registered `tool.invoke` actions with
evidence enforcement; signed and deduplicated Stripe ingress; and a tenant-scoped durable
Knowledge ledger whose decision-support outputs do not authorize execution.

The inspected artifacts do **not** justify claiming a production-ready paid customer loop, a live
admin control plane, a universal `ability_runtime` paid gate, database-enforced isolation for all
tenant data, exactly-once external effects, an autonomously closed intelligence loop, one current
claim/start/run authority spine, or agent swarming.

## Required runtime follow-ups

The implementation sequence, ownership decisions, acceptance evidence, rollback requirements, and
release gates for these follow-ups are defined in the
[complete remediation execution plan](../remediation/end-to-end-audit-remediation-plan-2026-08-16.md).

This static audit should be followed by separate remediation PRs with fault-injection tests for:

1. real middleware admin authentication and authorization;
2. metrics access from an unauthenticated client;
3. viewer webhook registration/secret receipt;
4. queue/DB divergence between HTTP bridge and daemon claim;
5. crash-after-provider-success replay for every external write action;
6. Stripe non-retryable failure receipt recovery;
7. cross-tenant negative tests for every non-RLS repository;
8. full queue → lease → dispatcher → consolidation → retrieval → informed-decision proof;
9. daemon-versus-HTTP-bridge claim/start/run race proof, including delayed
   `claim_existing_task()`;
10. governed multi-agent graph proof demonstrating typed artifact handoff, bounded parallelism,
    aggregate completion, tenant fairness, and no third runtime authority.
