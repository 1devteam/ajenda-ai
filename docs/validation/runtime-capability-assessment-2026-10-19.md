# Ajenda Runtime Capability Assessment — 2026-10-19

**Assessed implementation:** `a39e667a5482ef2e4c17eea5d9c5864287f7434c` (`fix/deployment-lifecycle-coherence`)
**Assessment authority:** diagnostic only. This document does not authorize work, alter mission state, or certify production readiness.
**Source of truth:** current source, generated G.R.A.F.T. graph, local API/runtime evidence, and executable tests named below.

## Scope and method

This assessment tests the real local Compose vertical and maps the wider repository with G.R.A.F.T. It intentionally distinguishes code presence, local fixture proof, configured external-provider proof, and production proof.

UPG/LAP scope:

- **Responsibility:** assess the current mission spine and document evidence-backed capability, gaps, and commercially relevant follow-up work.
- **Dependencies:** mission composition, action/capability resolution, queue admission, Redis, worker/lease execution, deliverable projection, runtime evidence, G.R.A.F.T. graph tooling, and their tests.
- **Pitfalls:** treating fixtures as public-web proof; treating graph topology as runtime proof; allowing one mission or task to mask another; and exposing credentials in artifacts.
- **Invariants:** the release correction changes only deterministic composition/confirmation validation and fixture-scope normalization; it does not grant runtime authority, alter credentials, change tenant permissions, or add provider configuration. G.R.A.F.T., continuous assurance, and runtime projections remain diagnostic/read-only.
- **Proof:** generated graph/completeness audit, focused evidence/composition/worker tests, required static and contract gates, and twenty isolated public-API local-fixture missions.

## G.R.A.F.T. result

The canonical graph was regenerated locally with `python scripts/validation/build_dependency_graph.py` and then passed `--check`.

| Fact | Result |
|---|---:|
| Graph schema | `1.4` |
| Nodes / edges | 2,121 / 5,852 |
| Static cycles | 0 |
| Production nodes / edges in completeness audit | 1,547 / 3,921 |
| Cross-boundary edges | 1,432 |
| Completeness integrity | Pass: no missing semantic-edge evidence, invariant source, or unacknowledged blocking finding |
| Main concentration points | `ActionRegistry`, `vertical_know_how`, mission routes, capability resolver, worker runtime service, and deliverable runtime state |

The graph selected the tenant-isolation, worker-spine, side-effect approval, retry/readmission, secret, governed-egress, and state-ownership proof bundles for changes across composition, coverage, worker scheduling, and operator proof. Those selections describe obligations; they do not establish that every path ran.

## Local vertical runtime evidence

The healthy local Compose stack reported `/health=ok` and `/readiness=ready` with PostgreSQL and Redis ready. The API proof used only public HTTP routes and a fresh disposable tenant:

```text
signup → email verification → bootstrap-key promotion
→ POST /v1/missions/compose
→ proposal confirmation (no queue authority)
→ POST /v1/missions/{id}/launch
→ Redis queue → worker lease/dispatch
→ task evidence + deliverable → runtime-evidence read
```

The final release proof ran 20 isolated fixture-only missions through the same
public API route. The source artifact is deliberately kept outside Git because
it contains ephemeral tenant and mission identifiers; its safe aggregate digest
is `6bbf97e8a2fdc3e932fb94c75532107d2a1d4d74d247dd62ad4fc79ca9454b22`.
It was generated at the assessed implementation revision above between
`2026-10-19T21:03:40Z` and `2026-10-19T21:13:33Z`.

The 20 lanes were software development, HVAC, roofing, plumbing, professional
services, advertising, electrical, landscaping, pest control, legal, dental,
recruiting, SaaS, e-commerce, and five alias/verb repetitions. The repetitions
include the former confirmation failure:

```text
Discover three e-commerce companies in Austin using local fixture data only.
```

Observed facts:

| Boundary | Evidence |
|---|---|
| Composition | All 20 proposals confirmed; confirmation did not queue work. The `Discover` verb passed the same confirmation quality gate as `Find` and `Research`. |
| Runtime | Every mission materialized, queue-admitted, and completed the canonical research and public-candidate-verification tasks. |
| Worker/evidence | All 20 exports reported zero contradictions and no first divergence. |
| Causal decisions | Interpretation, planner selection, capability selection, constraint propagation, task input binding, provider selection, source partition where applicable, tool output, output validation, and deliverable acceptance were persisted by their producers. |
| Deliverable | Every mission completed with exactly three fixture prospects and `aligned` runtime reconciliation. |
| Tenant isolation | Every proof attempted cross-tenant runtime-evidence access and received the expected denial. |

The current joined G.R.A.F.T./runtime artifact had two observed runtime nodes,
zero selected-but-unobserved nodes, zero contradictions, zero missing evidence,
and zero artifact-linkage gaps for the representative five-prospect path. The
twenty-mission aggregate independently confirms the same completed/reconciled
outcome for each three-prospect lane.

This confirms the local **fixture** research vertical. It does not show a live public search, a real external CRM, a provider credential, an email send, or production edge/Tunnel health.

## Capability and evidence matrix

| Capability | Source owner | Evidence status | Assessment |
|---|---|---|---|
| Tenant onboarding and promoted API-key path | onboarding routes and `TenantLifecycleService` | Direct local API proof | Demonstrated for the fixture mission. |
| Interpretation → plan → capability selection | mission-composition service, job catalog, capability resolver | Direct causal observations + focused unit tests | Demonstrated for the successful fixture path; not proof that every natural-language synonym has equivalent coverage. |
| Governed confirmation and launch | mission composition confirmation and mission routes | Direct local API proof | Demonstrated; confirmation remained non-executing and launch used the canonical runtime path. |
| Queue, lease, dispatcher, terminal state | `ExecutionCoordinator`, Redis adapter, `WorkerRuntimeService`, `TaskDispatcher` | Direct local API proof | Demonstrated for two read-safe tasks. |
| Runtime evidence, task-scoped coverage, reconciliation | ledger, projection, export, continuous-assurance consumers | Direct mission projection + focused unit tests | Demonstrated for this mission; read-only/non-authoritative by source and route contract. |
| Local fixture research and candidate verification | standalone/web actions and fixture records | Direct local API proof | Demonstrated; fixture sources remain non-real and must not be marketed as public research. |
| Public web research/transport/provider parsing | web/provider handlers | Not proven in this assessment | Requires a configured provider and an independently inspectable live run. |
| External CRM read/write | connector credentials, adapters, CRM actions | Not proven in this assessment | Connector-bound paths must be tested with authorized disposable credentials and explicit side-effect scope. |
| Email drafts / sends | sales and GTM email actions | Draft path not run; send not run | A send requires separate authorization, idempotency, provider, and mailbox evidence. |
| Production deployment, Cloudflare, tunnel | deployment configuration and external infrastructure | Not assessed | Local Compose proof cannot establish these properties. |
| Database role/RLS below HTTP | restricted roles, RLS migrations, integration tests | Not independently rerun end-to-end here | Requires restricted-role PostgreSQL integration proof; no inference from the HTTP isolation result. |

## Verified gaps and failure evidence

1. **Resolved — fixture aliases now share one capacity owner.**
   `local_fixture_scope_capacity()` normalizes industry/location aliases before
   both coverage assessment and action-input binding. The exact `software`
   alias regression now composes, confirms, launches, and completes.

2. **Resolved — validation contracts track the real migration head.**
   Migration contract tests now expect the canonical single head
   `0054_merge_roles_evidence`; they no longer describe the retired 0053
   release. Formatting issues in deployment tests were corrected. The complete
   non-integration suite, Ruff, format check, mypy, all listed contract
   controls, and G.R.A.F.T. reconciliation are rerun before release.

3. **Worker discovery latency needs an explicit bounded proof.**
   A prior isolated API proof observed a replacement tenant queued before the worker's roster refresh, then claimed after refresh. The current scheduler refresh interval is configuration-dependent. This is a latency/reliability finding; it is not evidence of task loss. Add a real Redis integration test before changing scheduler behavior.

4. **Provider and production lanes are evidence gaps, not product failures.**
   The local environment did not establish a live public-search provider, tenant connector credentials, external write authority, or Cloudflare backend execution. They remain unproven rather than assumed healthy or broken.

## Prioritized improvement plan

| Priority | Improvement | Why it matters | Acceptance evidence |
|---|---|---|---|
| Completed | Align migration contract assertions and deployment formatting | Restores a trustworthy broad CI baseline without weakening migration safety | Assertions name `0054_merge_roles_evidence`; complete non-integration gate passes. |
| Completed | Move fixture scope normalization and capacity lookup to one canonical fixture owner | Prevents equivalent scope names from being accepted at binding but rejected during composition | Exact `software` instruction composes, confirms, launches, and completes through the API; unsupported scopes remain fail-closed. |
| P1 | Add a sanitized operator-proof failure envelope | Lets an incomplete API mission identify its failed stage/status/mission or proposal correlation without leaking raw bodies or credentials | Regression proof captures compose/confirm/launch/wait stage and safe IDs; no secrets in output. |
| P1 | Add multi-tenant scheduler latency integration proof | Separates acceptable roster-refresh delay from lost dispatch work | New tenant after worker startup is claimed inside documented bound; Redis/schema failure is visible, not silently reported as no work. |
| P2 | Configure and prove public-web research with source provenance | Converts registered capability into actual customer value while preserving public-only constraints | Real provider run records query fingerprint, safe response summary, source eligibility, verification, and no internal-data contamination. |
| P2 | Add connector-specific commercial proofs | Makes CRM, email, calendar, and provider capability claims evidence-backed | Per-provider read proof first; write/send only with scoped approval, idempotency receipt, and external read-back. |
| P3 | Promote runtime evidence into a tenant-safe operational review UI/export | Turns the existing diagnostic substrate into a useful product support and quality workflow | Permission-gated timeline shows task/path coverage, causal decisions, gaps, historical unknowns, and first divergence without raw secrets/payloads. |

## Profitable upgrades grounded in existing capabilities

These are product opportunities, not claims that revenue or providers are already ready:

- **Evidence-backed prospect research:** convert the proven queue/evidence spine into a live public-source research offering once provider transport and verification are proven. Its differentiator is explainable source selection and failure visibility, not unbounded scraping.
- **Review-first revenue operations:** package draft-only lead qualification, research reports, and follow-up drafts for technical service firms. External sends and CRM mutations stay opt-in, approval-bound, and receipt-backed.
- **Mission reliability/assurance view:** expose the existing read-only runtime evidence as a tenant-safe “why did this mission fail?” product surface. This can reduce support cost and creates a paid governance/observability tier without granting new runtime authority.
- **Connector readiness as a commercial onboarding path:** validate OAuth/provider connections with bounded read checks before enabling customer workflows, then sell the verified connector lane rather than an untested integration catalog.

## Reproduction record

```bash
# Structural G.R.A.F.T. graph and completeness
python scripts/validation/build_dependency_graph.py
python scripts/validation/build_dependency_graph.py --check
python scripts/validation/graph_completeness_audit.py --output /tmp/ajenda-graft-completeness-20261019.json

# Focused composition, causal evidence, reconciliation, and scheduler tests
python -m pytest \
  tests/unit/services/test_mission_runtime_evidence_projection.py \
  tests/unit/services/test_runtime_reconciliation_export.py \
  tests/unit/services/test_runtime_evidence_ledger.py \
  tests/unit/workers/test_tenant_scheduler.py \
  tests/unit/services/test_mission_composition_engine.py \
  tests/unit/services/test_mission_composition_coverage.py \
  tests/unit/services/test_mission_composition_epistemic.py -q

# Required static/contract controls
ruff check backend/ tests/ scripts/validation/
ruff format --check backend/ tests/ scripts/validation/
mypy backend/
python scripts/validation/contract_drift_check.py
python scripts/validation/runtime_authority_inventory_check.py
python scripts/validation/migration_seed_contract_check.py
python scripts/validation/ability_rollout_contract_check.py
python scripts/validation/graft_plus_graft1st_reconciliation_check.py
python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration" -q
```

The twenty-mission aggregate proof is run separately after these gates:

```bash
python /tmp/run_twenty_api_proofs.py
```

No current graph, projection, continuous-assurance report, or documentation entry is a substitute for provider-specific and production runtime evidence. The release proof establishes only the documented local, fixture-only paths.

---

## Update — 2026-10-21: persisted-charter authority and release proof

**Status of this update:** source and GitHub Actions evidence review at `main` commit `e352c511fd71330ebbcf8fd7b318e249531419c9`. The earlier 2026-10-19 assessment above remains historical evidence for commit `a39e667a`, not an assertion that every old finding persists today.

### Implemented changes

- **PR #609, merged as `9e0b75a6`:** active tenant Business Profile is the authority for persisted operating-charter permissions. Missing and malformed persisted charters are differentiated as `CHARTER_MISSING` and `CHARTER_INVALID`; the UI's default charter is an editor draft, not runtime authority. Charter writes use revision checks with database locking. Composition and downstream admission/execution consumers are expected to reevaluate current authority rather than retain authorization from a stale composition snapshot. Human approval remains separate from charter permission.
- **PR #610, merged as `e352c511`:** the operator mission proof now expects a new tenant to have no charter, explicitly persists the charter via the Business Profile API, and verifies its active revision before composing work. This is a fixture correction necessitated by fail-closed onboarding, not a relaxation of charter enforcement.
- The supplied engineering handoff reports an integration test in which a queued external write was denied following charter revocation, a denial was persisted, and a fake provider was invoked zero times. This is **reported test evidence**, not an independently repeated test in this documentation update.

### Deployment topology and scope of proof

The engineering handoff identifies `ajenda-ai.com` as a frontend served by a Cloudflare Worker, with browser API requests directed to `api.ajenda-ai.com` through a Cloudflare Tunnel to the separately hosted FastAPI backend. Cloudflare frontend build success therefore does not establish backend availability or live provider results.

The local fixture-backed twenty-mission suite demonstrates the governed research execution spine under its stated conditions. Its results must not be promoted to proof of external web search, CRM/email effects, or production routing. The artifact audit reported only 15 of 20 current per-mission evidence projections correctly linked to their corresponding aggregate missions, plus a mismatch between embedded and final-file SHA-256. Treat aggregate functional completion separately from artifact provenance certification pending a run-scoped evidence recapture.

### Exact current main CI status

At `e352c511`, GitHub's **CI — Pull Request Gate failed**, although its lint/type, unit, integration, migration, frontend, and Docker jobs succeeded. The failing **Live Runtime Proof** job reached the operator proof script, then exited at:

```text
deploy/scripts/operator-mission-proof.py
  persist_proof_operating_charter(...)
  from backend.services.operating_charter import default_operating_charter
ModuleNotFoundError: No module named 'backend'
```

Evidence: [main CI run 39541455425](https://github.com/1devteam/ajenda-ai/actions/runs/39541455425), job `119030969260`.

This is a **proof-runner Python import-path/packaging defect** in the observed execution environment. It occurs before mission composition and does not demonstrate that `CHARTER_MISSING` is incorrectly enforced or that the queued-worker revocation rule failed. PR #610's pre-merge checks cannot substitute for the failed post-merge main proof.

The separate pre-merge-live-runtime-proof workflow also reported failure on this main revision. Do not call the whole main release green until the appropriate workflow failures are resolved or conclusively classified with their own evidence.

### Outstanding verification, in operational order

1. Correct the operator proof's dependency on importing `backend` from a standalone script execution context; prefer a stable package execution contract or an API-level fixture construction path. Preserve the explicit persisted-charter requirement.
2. Rerun the **actual post-merge main** Live Runtime Proof and require a completed mission, deliverable, reconciled evidence, and a green workflow conclusion.
3. Rebuild local images from the tested commit before attributing container behavior to current source.
4. Reconcile the twenty-mission aggregate to run-scoped, mission-ID-matched evidence records and a separately computed immutable digest.
5. Test one provider-backed, public-only research mission with bounded request/transport/provenance evidence. Keep external connector writes and sends approval-bound.
6. Evaluate remaining upstream decision-instrumentation coverage and the reported missing canonical graph node for `deploy/scripts/operator-mission-proof.py` against the current graph before treating these as new implementation defects.

**Release decision as of this update:** charter-policy changes are merged, but **main is not green**. Production/public-web capability remains unproven by the fixture missions. This document does not authorize ungating external abilities.
