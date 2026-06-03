# Mission V1 Finish Contract

## 1. Purpose

This contract defines what "mission-layer v1 finished" means and how that state is proven on current `main`.
It is a measurement and governance document, not an implementation plan and not runtime authority.

Mission-layer v1 is finished only when each mission-layer area has an explicit status, canonical source files, an MVP/prod-readiness distinction, and proof that matches real files in this repository. When proof is absent, this document says so instead of inventing old prompt paths or stale branch assumptions.

Status values in this document are limited to `finished`, `partial`, `missing`, and `future`:

- `finished`: implemented and backed by current proof for the stated scope.
- `partial`: implemented or specified in part, but with proof or behavior gaps before the area can be called complete.
- `missing`: expected for mission-layer v1 but no current implementation/proof surface exists.
- `future`: intentionally beyond v1 MVP or explicitly deferred until narrower contracts stabilize.

## 2. Non-Negotiable Product Rules

- Ajenda is mission-driven at the user layer.
- Business Profile is additive context, not a replacement for `MissionCreate`.
- Mission Brief shapes the current mission, but is not runtime authority by itself.
- Runtime execution remains behind explicit governed bridge stages.
- Queue/worker internals stay hidden from normal users.
- Durable Business Profile updates are never silently written.
- Ignore / dismiss means keep going with no profile update.
- No / not now means the information stays only in the current mission.
- Declarative contracts do not imply execution authority.
- Runtime queue admission is the first-class authority truth for admitted runtime work.

## 3. Mission Layer Areas

| Area | Definition | MVP status | Production status | Canonical files | Required proof |
| --- | --- | --- | --- | --- | --- |
| Business Profile / Operating Context | Additive tenant/business context used above mission intake to reduce repeated clarification without becoming the mission itself. | finished | partial | `backend/api/routes/business_profile.py`; `backend/domain/business_profile.py`; `backend/repositories/business_profile_repository.py`; `docs/product/business-profile-and-mission-context.md`; `docs/product/business-profile-implementation-contract.md`; `docs/product/mission-based-ai-core.md` | `tests/contract/api/test_business_profile_routes.py`; `tests/unit/repositories/test_business_profile_repository.py`; `tests/unit/db/test_business_profile_migration_contract.py` |
| Profile update suggestions | User-approved flow for turning durable facts discovered during missions into reusable Business Profile truth. | finished | partial | `backend/api/routes/business_profile.py`; `backend/domain/business_profile.py`; `backend/repositories/business_profile_repository.py`; `docs/product/business-profile-and-mission-context.md` | `tests/contract/api/test_business_profile_routes.py`; `tests/unit/repositories/test_business_profile_repository.py`; `tests/unit/db/test_business_profile_migration_contract.py` |
| Mission Brief | Structured interpretation of the current mission using approved Business Profile context plus current mission-specific intent. | finished | partial | `backend/api/routes/mission_brief.py`; `backend/services/mission_brief.py`; `docs/product/business-profile-and-mission-context.md`; `docs/product/mission-based-ai-core.md` | `tests/contract/api/test_mission_brief_routes.py`; `tests/unit/services/test_mission_brief.py` |
| Mission intake / MissionCreate | Tenant-authenticated creation of a planned mission and persisted `mission_intake` envelope for the specific current mission. | finished | partial | `backend/api/routes/mission.py`; `backend/domain/mission.py`; `docs/product/mission-based-ai-core.md`; `docs/contracts/authority-ledger.v1.yaml` | `tests/unit/api/test_mission_intake_route.py`; `tests/unit/domain/test_mission_intake_metadata.py`; `tests/contract/api/test_mission_queue_envelope_contract.py` |
| Mission planning | Declarative, tenant-scoped mission plan contract above mission intake and below task graph. | finished | partial | `backend/api/routes/mission.py`; `backend/domain/mission.py`; `backend/repositories/mission_plan_repository.py`; `docs/contracts/authority-ledger.v1.yaml` | `tests/unit/api/test_mission_planning_contract.py`; `tests/unit/repositories/test_mission_plan_repository.py`; `tests/unit/db/test_mission_plan_migration_contract.py` |
| Task graph | Normalized declarative DAG contract for planned mission work; graph persistence does not create tasks or dispatch runtime work. | finished | partial | `backend/api/routes/mission.py`; `backend/domain/mission.py`; `docs/product/mission-based-ai-core.md`; `docs/contracts/authority-ledger.v1.yaml` | `tests/unit/api/test_mission_intake_route.py`; `tests/unit/domain/test_mission_task_graph_contract_metadata.py`; `tests/contract/api/test_task_graph_runtime_boundary_contract.py` |
| Graph materialization | Metadata bridge from reviewed/planned mission plan to validated task graph materialization; metadata-only and not runtime execution. | finished | partial | `backend/api/routes/mission.py`; `backend/domain/mission.py`; `docs/product/mission-based-ai-core.md` | `tests/unit/api/test_mission_intake_route.py`; `tests/integration/runtime/test_task_graph_runtime_admission_real.py` |
| Runtime readiness | Read-only eligibility gate for whether the current admitted graph can proceed toward runtime task materialization. | finished | partial | `backend/api/routes/mission.py`; `backend/services/mission_runtime_projection.py`; `docs/product/mission-based-ai-core.md`; `docs/contracts/authority-ledger.v1.yaml` | `tests/unit/api/test_mission_intake_route.py`; `tests/unit/services/test_mission_runtime_projection.py`; `tests/contract/api/test_task_graph_runtime_boundary_contract.py` |
| Runtime task preview | Read-only pre-materialization projection of the `ExecutionTask` rows and payload envelopes that would be created from a ready admitted graph. | finished | partial | `backend/api/routes/mission.py`; `backend/services/mission_runtime_projection.py`; `docs/product/mission-based-ai-core.md`; `docs/contracts/authority-ledger.v1.yaml` | `tests/unit/api/test_mission_intake_route.py`; `tests/unit/services/test_mission_runtime_projection.py`; `tests/contract/api/test_task_graph_runtime_boundary_contract.py` |
| Runtime task materialization | Governed bridge that creates planned `ExecutionTask` rows from current ready runtime task preview; it does not enqueue or dispatch. | finished | partial | `backend/api/routes/mission.py`; `backend/repositories/execution_task_repository.py`; `backend/services/mission_runtime_projection.py`; `docs/contracts/authority-ledger.v1.yaml` | `tests/unit/api/test_mission_intake_route.py`; `tests/contract/api/test_task_graph_runtime_boundary_contract.py`; `tests/contract/api/test_task_queue_contract.py`; `tests/integration/runtime/test_task_graph_runtime_admission_real.py` |
| Runtime queue admission | Runtime-authoritative bridge that admits current planned materialized tasks to the queue through `ExecutionCoordinator`. | finished | partial | `backend/api/routes/mission.py`; `backend/services/execution_coordinator.py`; `backend/repositories/execution_task_repository.py`; `docs/contracts/authority-ledger.v1.yaml` | `tests/contract/api/test_mission_queue_contract.py`; `tests/contract/api/test_task_queue_contract.py`; `tests/unit/architecture/test_authority_ledger_contract.py` |
| Runtime dispatch readiness | Read-only gate for whether queued/claimed/running materialized work is dispatch-ready before worker execution. | finished | partial | `backend/api/routes/mission.py`; `backend/services/mission_runtime_projection.py`; `docs/contracts/authority-ledger.v1.yaml` | `tests/unit/api/test_runtime_dispatch_readiness_contract.py`; `tests/unit/services/test_mission_runtime_projection.py` |
| Worker eligibility / preview / claim / start / run bridge | Worker-facing staged bridge for dispatch eligibility, claim preview, claim admission, start admission, and run admission under queue/lease authority. | finished | partial | `backend/api/routes/mission.py`; `backend/services/worker_runtime_service.py`; `backend/workers/task_dispatcher.py`; `backend/workers/worker_loop.py`; `docs/contracts/authority-ledger.v1.yaml` | `tests/unit/api/test_worker_dispatch_eligibility_contract.py`; `tests/unit/api/test_worker_claim_admission_contract.py`; `tests/unit/api/test_worker_start_admission_contract.py`; `tests/unit/api/test_worker_run_admission_contract.py`; `tests/unit/services/test_worker_runtime_service_transaction_contract.py`; `tests/integration/runtime/test_worker_loop_dispatcher_compensation_real.py`; `tests/contract/workers/test_real_worker_loop.py` |
| Evidence / outcome review | Declarative mission/task evidence records and outcome review records used for governed assessment without directly mutating runtime execution state. | finished | partial | `backend/api/routes/evidence.py`; `backend/domain/evidence.py`; `backend/api/routes/outcome_review.py`; `backend/domain/outcome_review.py`; `docs/contracts/authority-ledger.v1.yaml`; `docs/policies/EVIDENCE_LIFECYCLE_POLICY.md` | `tests/unit/api/test_evidence_route.py`; `tests/unit/repositories/test_evidence_repository.py`; `tests/unit/api/test_outcome_review_route.py`; `tests/unit/repositories/test_outcome_review_repository.py` |
| Memory promotion | Governed promotion of reviewed mission knowledge into durable reusable memory. | missing | missing | `docs/product/business-profile-and-mission-context.md`; `backend/domain/evidence.py`; `backend/domain/outcome_review.py`; `backend/domain/retrieval_contract.py` | Proof path absent on current main. Existing domain docs state evidence/outcome/retrieval contracts do not promote memory by themselves. |
| Retrieval / recall governance | Declarative retrieval/recall contract records with tenant-scoped memory references and no implicit embedding/vector execution. | finished | partial | `backend/api/routes/retrieval_contract.py`; `backend/domain/retrieval_contract.py`; `docs/contracts/authority-ledger.v1.yaml` | `tests/unit/api/test_retrieval_contract_route.py`; `tests/unit/repositories/test_retrieval_contract_repository.py` |

## 4. Canonical Mission Runtime Chain

Intended staged chain:

Business Profile context
→ user mission
→ Mission Brief
→ MissionCreate / mission intake
→ mission plan
→ task graph
→ graph materialization
→ runtime readiness
→ task preview
→ runtime task materialization
→ runtime queue admission
→ dispatch readiness
→ worker eligibility / claim / start / run
→ evidence / outcome review
→ memory / recall

| Stage | User-facing | Operator-facing | Runtime-authoritative | Mutates runtime state | Creates `ExecutionTask` rows | Queues work | Dispatches workers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Business Profile context | yes | yes | no | no | no | no | no |
| user mission | yes | no | no | no | no | no | no |
| Mission Brief | yes | yes | no | no | no | no | no |
| MissionCreate / mission intake | yes | yes | no | no | no | no | no |
| mission plan | yes | yes | no | no | no | no | no |
| task graph | operator-facing summary may exist; queue/worker internals hidden | yes | no | no | no | no | no |
| graph materialization | no | yes | no | no | no | no | no |
| runtime readiness | no | yes | no | no | no | no | no |
| task preview | no | yes | no | no | no | no | no |
| runtime task materialization | no | yes | no | yes | yes | no | no |
| runtime queue admission | no | yes | yes | yes | no | yes | no |
| dispatch readiness | no | yes | no | no | no | no | no |
| worker eligibility / claim / start / run | no | yes | claim/start are governed mutation; run is runtime-authoritative | yes for claim/start/run admissions | no | no | yes at run admission |
| evidence / outcome review | yes | yes | no | no | no | no | no |
| memory / recall | yes | yes | retrieval contracts are declarative; memory promotion is missing | no proven memory-promotion mutation on current main | no | no | no |

Notes:

- `MissionCreate / mission intake` creates a tenant-owned `Mission` record and intake metadata, but that is product-contract state rather than runtime execution state.
- `mission plan`, `task graph`, and `graph materialization` may mutate mission/plan contract metadata, but they must not mutate queue, lease, dispatcher, worker, or runtime execution state.
- Runtime task materialization creates planned `ExecutionTask` rows but intentionally does not queue them.
- Runtime queue admission is the first stage in this chain that queues work and is runtime-authoritative.
- Worker run admission is the stage that may invoke dispatcher execution for already admitted running work with valid queue/lease authority.

## 5. Proof Map

| Stage | Existing proof path | What it proves | Missing proof if any |
| --- | --- | --- | --- |
| Business Profile context | `backend/api/routes/business_profile.py`; `backend/domain/business_profile.py`; `backend/repositories/business_profile_repository.py`; `tests/contract/api/test_business_profile_routes.py`; `tests/unit/repositories/test_business_profile_repository.py`; `tests/unit/db/test_business_profile_migration_contract.py` | Tenant-scoped Business Profile storage/API, approved fact upserts, suggestion lifecycle, mission-id validation, history read surface, audit events, and no-runtime-side-effect boundaries are proven. | Mission Brief read model/API proof remains absent. |
| user mission | `tests/unit/api/test_mission_intake_route.py`; `tests/unit/domain/test_mission_intake_metadata.py` | A tenant-authenticated user mission request becomes a planned mission intake envelope. | No user-facing UX proof path exists on current main. |
| Mission Brief | `docs/product/business-profile-and-mission-context.md`; `docs/product/mission-based-ai-core.md` | Product definition exists for the Mission Brief concept. | Proof path absent on current main for Mission Brief read model/API behavior. |
| MissionCreate / mission intake | `tests/unit/api/test_mission_intake_route.py`; `tests/unit/domain/test_mission_intake_metadata.py`; `tests/contract/api/test_mission_queue_envelope_contract.py` | Mission intake persists tenant-owned planned mission metadata and does not queue runtime work. | End-to-end Mission Brief-to-MissionCreate proof absent. |
| mission plan | `tests/unit/api/test_mission_planning_contract.py`; `tests/unit/repositories/test_mission_plan_repository.py`; `tests/unit/db/test_mission_plan_migration_contract.py` | Mission plan contract persistence, repository behavior, and migration shape. | Full planner-generation proof absent; current proof is contract persistence/validation. |
| task graph | `tests/unit/api/test_mission_intake_route.py`; `tests/unit/domain/test_mission_task_graph_contract_metadata.py`; `tests/contract/api/test_task_graph_runtime_boundary_contract.py` | Task graph validation, normalization, tenant boundaries, no queue/worker side effects, and runtime-boundary separation. | End-to-end autonomous graph orchestration proof intentionally absent. |
| graph materialization | `tests/unit/api/test_mission_intake_route.py`; `tests/integration/runtime/test_task_graph_runtime_admission_real.py` | Materialization metadata persists without queue/runtime execution and can participate in real admission setup. | Broader full-chain proof from plan generation through materialization remains partial. |
| runtime readiness | `tests/unit/api/test_mission_intake_route.py`; `tests/unit/services/test_mission_runtime_projection.py`; `tests/contract/api/test_task_graph_runtime_boundary_contract.py` | Runtime readiness is read-only and evaluates current graph/materialization/admission state. | Live release-gate proof specifically for readiness remains partial. |
| task preview | `tests/unit/api/test_mission_intake_route.py`; `tests/unit/services/test_mission_runtime_projection.py`; `tests/contract/api/test_task_graph_runtime_boundary_contract.py` | Preview rows are deterministic and read-only before materialization. | Live release-gate proof specifically for preview remains partial. |
| runtime task materialization | `tests/unit/api/test_mission_intake_route.py`; `tests/contract/api/test_task_graph_runtime_boundary_contract.py`; `tests/contract/api/test_task_queue_contract.py`; `tests/integration/runtime/test_task_graph_runtime_admission_real.py` | Planned `ExecutionTask` rows are created through the governed bridge without queueing/dispatching. | Full Mission Brief-to-worker happy-path proof absent. |
| runtime queue admission | `tests/contract/api/test_mission_queue_contract.py`; `tests/contract/api/test_task_queue_contract.py`; `tests/unit/architecture/test_authority_ledger_contract.py` | Current planned materialized tasks are admitted to the queue through `POST /v1/missions/{mission_id}/runtime-queue-admission`, the canonical runtime-authoritative mission queue bridge. `POST /v1/missions/{mission_id}/queue` remains a general mission queue route for tenant-owned planned tasks and is not the canonical staged bridge for current runtime task materialization. | Full live mission bridge proof remains partial. |
| dispatch readiness | `tests/unit/api/test_runtime_dispatch_readiness_contract.py`; `tests/unit/services/test_mission_runtime_projection.py` | Dispatch readiness read model does not mutate runtime state. | Broader full-chain proof from queue admission into readiness remains partial. |
| worker eligibility / claim / start / run | `tests/unit/api/test_worker_dispatch_eligibility_contract.py`; `tests/unit/api/test_worker_claim_admission_contract.py`; `tests/unit/api/test_worker_start_admission_contract.py`; `tests/unit/api/test_worker_run_admission_contract.py`; `tests/unit/services/test_worker_runtime_service_transaction_contract.py`; `tests/integration/runtime/test_worker_loop_dispatcher_compensation_real.py`; `tests/contract/workers/test_real_worker_loop.py` | Worker bridge preserves staged eligibility, claim, start, lease, and run authority boundaries. | Mission-specific full-chain happy-path proof remains partial. |
| evidence / outcome review | `tests/unit/api/test_evidence_route.py`; `tests/unit/repositories/test_evidence_repository.py`; `tests/unit/api/test_outcome_review_route.py`; `tests/unit/repositories/test_outcome_review_repository.py` | Evidence and outcome review records are tenant-owned declarative governance contracts. | Autonomous outcome scoring and runtime mutation from review are intentionally absent. |
| memory / recall | `tests/unit/api/test_retrieval_contract_route.py`; `tests/unit/repositories/test_retrieval_contract_repository.py` | Retrieval/recall contract records are tenant-scoped and do not implicitly run retrieval engines or mutate runtime state. | Memory promotion proof path absent on current main; retrieval engine execution proof is absent by design for this contract layer. |

## 6. MVP vs Production-Ready

| Area | MVP enough means | Production-ready means | Gap |
| --- | --- | --- | --- |
| Business Profile / Operating Context | Tenant-scoped storage/API/read model exists and cannot be mistaken for MissionCreate replacement. | Tenant-scoped storage/API/read model, approval semantics, audits, JSON/category hardening, and tests prove durable profile behavior. | Mission Brief consumption and UI review flow remain separate production gaps. |
| Profile update suggestions | Choice semantics are implemented for approve, edit, decline, and dismiss without silent profile writes. | Durable update proposal workflow is tenant-scoped, auditable, test-backed, mission-link validated, and cannot silently write profile truth. | UI-supported review/edit flow remains separate. |
| Mission Brief | Mission Brief role is defined as current-mission interpretation, not runtime authority. | Read-model/API contract proves Business Profile context plus current mission intent produces a bounded brief without runtime side effects. | Read model/API/proof are absent. |
| Mission intake / MissionCreate | Tenant-owned planned mission and `mission_intake` metadata are created without queueing. | Intake is connected to Mission Brief and Business Profile context while preserving fail-closed validation and release-gate proof. | Business Profile/Mission Brief integration proof is absent. |
| Mission planning | Declarative plan persistence and tenant/repository boundaries are proven. | Planner provenance, operator approval semantics, and full plan-to-graph generation proof are robust. | Generation/provenance proof is partial. |
| Task graph | Normalized graph contract validates shape and stays declarative. | Complex DAG compatibility, capability compatibility, and live full-chain graph proof are release-gated. | Live graph orchestration proof is intentionally absent. |
| Graph materialization | Materialization metadata persists and does not create runtime work. | Plan-to-graph materialization provenance, review outcomes, and broader integration are fully proven. | Full provenance/review coverage is partial. |
| Runtime readiness | Read-only readiness gate blocks unsafe progression. | Readiness is covered by both targeted contract tests and release-gating live validation rows. | Live proof is partial. |
| Runtime task preview | Preview is deterministic and read-only. | Preview coverage includes broad graph/dependency/payload matrix and current live proof. | Matrix breadth/live proof are partial. |
| Runtime task materialization | Planned `ExecutionTask` creation is governed and separated from queueing. | Materialization has broad integration, idempotency, rollback, supersession, quota, and release-gating evidence. | Some broad/live proof remains partial. |
| Runtime queue admission | `POST /v1/missions/{mission_id}/runtime-queue-admission` is documented as the canonical runtime-authoritative bridge for current materialized mission tasks, while `POST /v1/missions/{mission_id}/queue` remains general mission queue routing. | Canonical route is covered by full live mission bridge proof and operator-facing docs/tests consistently distinguish it from general queue routes. | Full live mission bridge proof is partial. |
| Runtime dispatch readiness | Dispatch-readiness read model is proven not to mutate runtime state. | Full mission-chain dispatch readiness is proven after queue admission and before worker run. | Full-chain proof is partial. |
| Worker eligibility / preview / claim / start / run bridge | Staged worker bridge and lease/dispatcher boundaries are test-backed. | Mission-specific worker bridge is covered by complete happy-path and negative-path release gates. | Mission-specific full-chain proof is partial. |
| Evidence / outcome review | Declarative evidence and review contracts are tenant-scoped and non-runtime-authoritative. | Evidence lifecycle, outcome review decisions, retention, supersession, and release/audit linkage are operationally complete. | Runtime outcome loop maturity is partial. |
| Memory promotion | No silent durable memory/profile promotion occurs. | Approved promotion workflow, storage, audit, recall linkage, and tests exist. | Area is missing. |
| Retrieval / recall governance | Retrieval contracts exist and do not execute retrieval implicitly. | Retrieval execution, returned memory ranking, recall safety, and promotion linkage are production proven. | Execution/promotion linkage is partial or absent. |

## 7. Do Not Touch Yet

Do not implement the following before this finish contract stabilizes and the next focused PR chooses a narrow proof target:

- broad UI implementation
- autonomous graph orchestration
- direct capability-adapter execution from declarations
- merging Business Profile into `MissionCreate`
- making Mission Brief runtime authority
- silent profile memory writes
- bypassing explicit runtime bridge stages
- implicit queueing from mission intake, mission plan, task graph, graph materialization, readiness, or task preview
- treating retrieval contract creation as embedding/vector retrieval execution
- treating evidence/outcome review creation as automatic memory promotion
- replacing the canonical runtime queue admission bridge with the legacy/general mission queue route

## 8. Follow-Up PR Offers

### 1. Align mission proof manifest with current test paths

- **Title:** Align Mission Proof Manifest With Current Main
- **Branch name:** `docs/align-mission-proof-manifest-current-main`
- **Goal:** Add or update a docs-only proof manifest that lists only current-main proof paths for mission intake, planning, graph, bridge, worker, evidence, outcome, and recall governance.
- **Files likely touched:** `docs/product/mission-v1-finish-contract.md`; possibly `docs/product/mission-based-ai-core.md`; possibly `docs/contracts/authority-ledger.v1.yaml` if wording-only proof references are stale.
- **Smallest proof set:** `python scripts/validation/contract_drift_check.py`
- **Broader validation set:** `ruff check docs scripts tests`; `ruff format --check backend/ tests/`
- **Merge risk:** Low; docs/governance only.
- **Why it comes now:** This finish contract exposes absent or fragmented proof references and should be made easier to maintain before implementation PRs rely on it.

### 2. Clarify canonical mission queue path versus legacy/general queue route

- **Title:** Clarify Canonical Mission Queue Admission Path
- **Branch name:** `docs/clarify-canonical-mission-queue-path`
- **Goal:** Document that `POST /v1/missions/{mission_id}/runtime-queue-admission` is the canonical mission runtime queue authority, while `POST /v1/missions/{mission_id}/queue` remains legacy/general queue routing unless separately governed.
- **Files likely touched:** `docs/product/mission-based-ai-core.md`; `docs/product/mission-v1-finish-contract.md`; `README.md`; `docs/contracts/authority-ledger.v1.yaml`
- **Smallest proof set:** `python scripts/validation/contract_drift_check.py`; `pytest tests/unit/architecture/test_authority_ledger_contract.py`
- **Broader validation set:** `ruff check docs scripts tests`; `ruff format --check backend/ tests/`; `pytest tests/contract/api/test_mission_queue_contract.py tests/contract/api/test_task_queue_contract.py`
- **Merge risk:** Low to medium; wording must not imply API behavior changes.
- **Why it comes now:** Queue admission is now first-class authority truth, and future mission bridge work needs a single canonical route story.

### 3. Harden runtime readiness/materialization proof map

- **Title:** Harden Runtime Readiness And Materialization Proof Map
- **Branch name:** `docs/harden-runtime-readiness-materialization-proof-map`
- **Goal:** Tighten docs and proof references around runtime readiness, task preview, and runtime task materialization, including what each stage must not mutate.
- **Files likely touched:** `docs/product/mission-based-ai-core.md`; `docs/product/mission-v1-finish-contract.md`; `docs/contracts/authority-ledger.v1.yaml`; possibly `docs/validation/live-runtime-matrix.md`
- **Smallest proof set:** `python scripts/validation/contract_drift_check.py`; `pytest tests/unit/api/test_mission_intake_route.py tests/unit/services/test_mission_runtime_projection.py`
- **Broader validation set:** `ruff check docs scripts tests`; `ruff format --check backend/ tests/`; `pytest tests/contract/api/test_task_graph_runtime_boundary_contract.py tests/integration/runtime/test_task_graph_runtime_admission_real.py`
- **Merge risk:** Medium; proof wording must stay aligned with current route behavior and not overclaim live graph execution.
- **Why it comes now:** These stages sit directly between declarative mission graph contracts and runtime-authoritative queue admission.

### 4. Add full mission bridge happy-path proof

- **Title:** Add Full Mission Bridge Happy Path Proof
- **Branch name:** `test/add-full-mission-bridge-happy-path-proof`
- **Goal:** Add the smallest test that walks current implemented stages from mission intake through graph/materialization/readiness/preview/task materialization/queue admission and verifies the expected stage boundaries.
- **Files likely touched:** likely `tests/contract/api/test_task_graph_runtime_boundary_contract.py` or `tests/integration/runtime/test_task_graph_runtime_admission_real.py`; docs only as needed to reference the new proof.
- **Smallest proof set:** The new targeted test plus `python scripts/validation/contract_drift_check.py`.
- **Broader validation set:** `ruff check docs scripts tests`; `ruff format --check backend/ tests/`; `pytest tests/contract/api/test_task_graph_runtime_boundary_contract.py tests/contract/api/test_mission_queue_contract.py tests/integration/runtime/test_task_graph_runtime_admission_real.py`
- **Merge risk:** Medium; test may need careful fixture setup and must not alter runtime behavior.
- **Why it comes now:** The current proof map is strong by stage but still partial for an end-to-end mission bridge happy path.

### 5. Continue Business Profile production hardening

- **Title:** Harden Business Profile Operational Readiness
- **Branch name:** `feature/business-profile-operational-readiness`
- **Goal:** Keep Business Profile inside its declarative/additive authority boundary while adding remaining operational readiness items such as retention/deletion policy, UI review proof, and monitoring dashboards/alerts for profile update failures.
- **Files likely touched:** `backend/api/routes/business_profile.py`; `backend/repositories/business_profile_repository.py`; `docs/product/business-profile-implementation-contract.md`; `docs/product/mission-v1-finish-contract.md`; Business Profile tests as needed.
- **Smallest proof set:** `python scripts/validation/contract_drift_check.py`; `pytest tests/unit/api/test_business_profile_hardening.py tests/unit/repositories/test_business_profile_repository.py`
- **Broader validation set:** `ruff check docs scripts tests`; `ruff format --check backend/ tests/`; `pytest -m "not integration"`
- **Merge risk:** Medium; wording and implementation must not imply Mission Brief, MissionCreate, queue, worker, retrieval, evidence, outcome-review, or memory-promotion authority.
- **Why it comes now:** Backend/API proof now exists for profile storage, suggestions, mission-id validation, history reads, audit events, and no-runtime side effects; remaining Business Profile work should focus on operational readiness without crossing authority classes.

### 6. Harden Mission Brief read-model operations

- **Title:** Harden Mission Brief Read Model Operations
- **Branch name:** `feature/mission-brief-operational-readiness`
- **Goal:** Extend the implemented Mission Brief read model with broader product field coverage, UI review proof, and release-gated integration evidence while preserving read-only authority.
- **Files likely touched:** `backend/api/routes/mission_brief.py`; `backend/services/mission_brief.py`; `docs/product/business-profile-and-mission-context.md`; `docs/product/mission-v1-finish-contract.md`; Mission Brief tests as needed.
- **Smallest proof set:** `pytest tests/unit/services/test_mission_brief.py tests/contract/api/test_mission_brief_routes.py`; `python scripts/validation/contract_drift_check.py`
- **Broader validation set:** `ruff check docs scripts tests`; `ruff format --check backend/ tests/`; `pytest -m "not integration"`
- **Merge risk:** Medium; changes must not create Mission, MissionPlan, task graph, ExecutionTask, queue messages, worker leases, evidence, outcome-review, retrieval, Business Profile truth, or memory-promotion records.
- **Why it comes next:** The backend read-model/API proof now exists; remaining work is operational maturity and user-facing review flow.
