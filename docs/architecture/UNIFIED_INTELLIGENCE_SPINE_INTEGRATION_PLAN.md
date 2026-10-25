# Unified Intelligence Spine — Coordinated Integration Plan

**Status:** implementation plan grounded in the current source and runtime
findings. This document assigns no execution authority.

## Purpose

Ajenda already has the principal owners needed for a complete intelligence
spine. The work is to connect their factual inputs, interpretation, reviewed
composition, governed execution, evidence, outcome evaluation, and qualified
learning without introducing another planner, runtime, evidence ledger, or
learning authority.

The required invariant is:

```text
business facts / customer instruction / observed outcome / qualified knowledge
  -> need and assessment (when applicable)
  -> semantic snapshot -> reviewed composition -> governed task graph
  -> runtime result -> acceptance -> later business impact -> qualified reuse
```

An instruction remains directly composable. A recognised need remains valid
even when no capability can address it. Neither grants execution authority.

## Minimum complete spine and existing owners

| Stage | Existing owner files | Current role | Required connection / proof |
|---|---|---|---|
| 1. Source facts and instructions | `backend/domain/business_profile.py`, `backend/services/business_profile/record_sync.py`, `backend/api/routes/mission_composition.py` | Approved profile facts and direct instruction ingress | Preserve source ownership and tenant scope; profile or instruction must never be recast as verified outcome evidence. |
| 2. Business observations and continuing needs | `backend/domain/business_understanding.py`, `backend/services/business_understanding/service.py`, `backend/repositories/business_understanding_repository.py`, `backend/api/routes/business_understanding.py` | Tenant-bound measurements, observations, need revisions, and impact records | Source measurement -> observation -> stable need identity -> materially justified revision. Prove RLS, idempotency, and no automatic authorization. |
| 3. Need reasoning | `backend/services/business_understanding/reasoning.py`, `backend/services/ontology/evaluation.py`, `backend/services/ontology/outcome.py` | Evidence-attributed causes, responses, uncertainty, capability gaps, and impact semantics | Make assessment facts available to later semantic composition only by explicit references; preserve contradictory causes and unavailable responses. |
| 4. Semantic interpretation | `backend/services/mission_composition/intent_interpreter.py`, `backend/services/mission_composition/interpretation/rule_engine.py`, `backend/services/mission_composition/semantic_lattice/*` | Clauses, outcomes, constraints, semantic bindings | Add bounded business-review/recovery/report semantics only where an existing factual reader and artifact contract exist. Do not translate broad review language into prospect research. |
| 5. Job and capability selection | `backend/services/mission_composition/job_catalog.py`, `backend/services/mission_composition/capability_resolver.py`, `backend/services/abilities/catalog.py` | Catalog jobs, dependencies, action readiness, and capability gaps | Candidate response validity precedes capability availability. The catalog selects only supported work after semantic meaning is established. |
| 6. Immutable reviewed composition | `backend/services/mission_composition/proposal_phase.py`, `proposal_store.py`, `confirmation_phase.py`, `compile_phase.py`, `contracts.py` | Semantic and reviewed-composition snapshots, materiality and revalidation lineage | Persist need/assessment provenance with snapshots and prove successor revisions on material jobs, artifacts, dependencies, strategy, or acceptance changes. |
| 7. Governance and admission | `backend/services/operating_charter.py`, `backend/services/execution_coordinator.py`, `backend/services/policy_guardian.py`, `backend/services/mission_runtime_queue_admission_service.py` | Current permission, review, quota, and queue admission | Maintain independent authorization. Intelligence can recommend or compose but cannot queue itself. |
| 8. Runtime execution | `backend/services/runtime_queue_dispatcher.py`, `backend/services/worker_runtime_service.py`, `backend/workers/task_dispatcher.py`, `backend/services/tools/runtime_authority.py` | Durable dispatch, lease ownership, handler execution, recovery | Prove retry after commit, dependency recovery, and no duplicated side effect. |
| 9. Evidence and acceptance | `backend/repositories/evidence_repository.py`, `backend/services/runtime_evidence_ledger.py`, `backend/services/mission_acceptance.py`, `backend/services/worker_runtime_rollup.py` | Runtime lineage, artifacts, task/mission truth, deliverable acceptance | A task or mission completion must not be reported as unmet/accepted inconsistently, and mission acceptance must not be business impact. |
| 10. Outcome and qualified learning | `backend/services/decision_episode_materialization.py`, `backend/services/durable_experience_consolidation.py`, `backend/services/knowledge/*`, `backend/services/tools/knowledge_actions.py` | Canonical episode, experience, qualification, retrieval, applicability, decision support | Feed only adequately evidenced outcome episodes into existing qualification; prove later applicable reuse and reject stale, contradictory, inapplicable, or cross-tenant knowledge. |

## Findings from real mission attempts

| Mission class | Observed result | Spine boundary implicated | Correct disposition |
|---|---|---|---|
| Gmail review / HubSpot cross-reference / follow-up summary | Gmail provider read succeeded after tenant credential-session correction. The composed graph selected only `gtm.email_check`; it did not select HubSpot contact lookup or a summary artifact. | Stages 4–6 and 8–9 | Preserve the Gmail result as observed evidence. Add no fabricated HubSpot match: the current adapter cannot establish sender-email contact cross-reference. A later semantic/catalog path must name all requested read and synthesis work. |
| Three internal CRM follow-up tasks | The original graph was incorrectly composed as prospect research. The existing `sales.create_followup_task` action and Light CRM store were available but unreachable. | Stages 4–9 | Implemented bounded `create_internal_followup_tasks` routing, binding, typed artifact/readback acceptance, and real PostgreSQL/Redis runtime proof. |
| Provider failure then task retry | A successful retry left stale task failure metadata, a failed parent mission, and blocked descendants. | Stages 7–9 | Implemented governed mission reopening, historical failure/acceptance preservation, dependency re-admission only after all dependencies complete, and real PostgreSQL/Redis proof. |
| Business readiness, strategy comparison, history review, goal-progress reconciliation | Composition rejected the instructions or misrouted them because no ordinary semantic outcome joins tenant business facts, mission/evidence history, outcome reviews, need assessments, and qualified knowledge into a bounded report. | Stages 2–6 and 10 | Do not force these prompts into prospect research or generic income review. First add a source-owned read/assessment artifact boundary using the existing business-understanding, evidence, outcome, and knowledge owners. |

## Verified ownership and the missing edges

The following map is based on the current implementation rather than an
intended architecture. It identifies where the existing owners already meet
and where a connection is still absent. A missing edge is not authority to
replace either endpoint with a new service.

| Boundary | Existing producer owner | Existing consumer owner | Present behavior | Missing connection that the spine must add |
|---|---|---|---|---|
| Source facts → continuing need | `business_profile/record_sync.py` and `business_understanding/service.py` | `BusinessUnderstandingRepository` and `reasoning.py` | Customer-attested KPI ingestion persists a measurement and calls `recognize_goal_gap()` in the caller transaction. The goal evaluator preserves `AT_RISK`, `OFF_TRACK`, recovery, and insufficient-evidence distinctions. | A supported operational producer must supply an input when measurement ingestion is not invoked directly. Customer-attested data remains customer-attested; it is not provider verification. |
| Continuing need → assessment | `business_understanding/service.py` | `business_understanding/reasoning.py` | Assessment validates that hypotheses and candidate responses cite observations belonging to the tenant-scoped need revision. It records contradictions and capability gaps without execution authority. | **Connected:** composition consumes only an explicit tenant-scoped assessment reference; automatic operational assessment production remains a separate source-owner connection. |
| Assessment → reviewed composition | `MissionCompositionService._business_need_assessment_reference()` | `proposal_phase.py`, `confirmation_phase.py`, `compile_phase.py`, `proposal_store.py` | Need and assessment references are tenant validated and carried through revalidation into immutable semantic and reviewed-composition snapshots. | **Connected:** the snapshot includes bounded assessment context and digest: condition, alternatives, uncertainty, observation IDs, subject/objective semantics, and original evaluation time. Revalidation cannot substitute a newer assessment. |
| Reviewed composition → decision/retrieval work | `plan_compiler.py` and `action_input_analysis.py` | `knowledge_actions.py`, `decision_actions.py` | Profile retrieval binds `business_profile_facts` into the existing `decision.recommend_next_action` business-review path. Knowledge retrieval and decision support are registered catalog actions. | **Connected:** assessment context compiles into the existing Decision input. Exact subject, objective, and evaluation-time semantics select existing `knowledge.inform_decision`; incomplete semantics use existing assessment-only Decision. |
| Decision → business impact | `analysis_actions.py` / `ontology/outcome.py` | `BusinessUnderstandingService.record_canonical_measurement_impact()` | `analysis.evaluate_outcome` produces canonical runtime evidence; impact recording verifies comparable durable measurements, subject identity, chronology, and canonical outcome payload before appending a need revision. | No composition/runtime path currently assembles baseline and later measurement identities into an outcome evaluation and then invokes the existing impact recorder. Mission completion is correctly insufficient. |
| Impact → reusable knowledge | `decision_episode_materialization.py` | `durable_experience_consolidation.py` and `knowledge_actions.py` | The canonical materializer verifies recommendation, outcome, execution evidence, tenant/mission lineage, chronology, and action ownership. Consolidation owns Experience, qualification, and ledger writes. | Measurement/observation records are not automatically runtime `EvidenceRecord`s. A source-to-runtime evidence bridge must be explicit; assessment or customer-attested measurement identifiers must never be disguised as canonical decision-support evidence. |
| Qualified knowledge → later decision | `knowledge_retrieval.py` and `knowledge_applicability.py` | `knowledge_actions.py` / `decision.recommend_next_action` | Existing knowledge-informed decision support retrieves, evaluates applicability, appends derived facts with durable lineage, and preserves constraints. | **Connected:** a semantically complete, tenant-validated assessment supplies the existing typed decision/options/criteria/query/context payload. Incomplete assessment semantics deliberately use the assessment-only decision action instead. |

### Runtime launch and the remaining decision-to-response boundary

`frontend/src/pages/MissionDispatchPage.tsx` already owns the client-side
handoff: **Start execution** calls `launchMission()` in
`frontend/src/api/client.ts`, which calls the existing
`POST /v1/missions/{mission_id}/launch` route. That route compiles the
confirmed composition, records graph materialization, invokes runtime
admission, materializes `ExecutionTask` rows, and uses the canonical queue
admission owner. A red readiness panel with missing materialization and
admission therefore means that this launch request has not successfully
completed for that mission; it is not evidence that another client runtime or
queue service is required.

The next unconnected boundary is intentionally narrower:

```text
assessment-backed recommendation
  -> operator-selected response / successor reviewed composition
  -> existing governed execution (if admitted)
  -> comparable later measurement -> existing outcome/learning owners
```

`knowledge.inform_decision` and `decision.recommend_next_action` own a
recommendation; they do not own mission selection, composition confirmation,
or execution. `MissionCompositionService` already owns the latter records.
The composition ingress now accepts an explicitly selected candidate only with
its referenced assessment and a tenant-owned baseline measurement. It validates
both source references, snapshots the candidate and a non-authoritative intent
to remeasure the same subject/objective/metric, then revalidates that lineage
at confirmation and compilation. The instruction remains the sole input to
semantic routing and planned work; the candidate is not passed into action
selection or execution authority. Runtime evidence retains a digest of the
same provenance package for readback.

The remaining boundary is deliberately downstream: only a later measurement,
canonical outcome evidence, and the existing measurement-comparability owner
may invoke `record_canonical_measurement_impact()`. Neither composition nor a
recommendation may manufacture that later measurement, assert impact, or
promote learning. This preserves the open path to the existing outcome and
learning owners without implementing it prematurely.

### Integration constraints proved by the current owners

- `BusinessNeedReasoningService` is an assessment owner, not a planner: it
  reports catalog coverage but does not resolve capability, enqueue work, or
  invoke providers.
- `MissionCompositionService` owns semantic and reviewed snapshots; its
  business-need references are read-only provenance and cannot issue runtime
  authority.
- `DecisionEpisodeMaterializationService` accepts durable runtime evidence,
  not caller-authored measurement or observation claims. This is the required
  guard against promoting correlation or customer-attested data into causal
  learning.
- `DurableExperienceConsolidationService` remains the sole path from a valid
  decision-learning signal to qualification and ledger state.
- `TaskDispatcher` and `WorkerRuntimeService` remain the only route to tool
  execution. None of the proposed source-to-assessment connections may queue
  work.

### Implemented assessment-to-decision and qualified-knowledge connections

The first spine edge is now implemented through existing owners:

```text
tenant-scoped need revision + durable assessment
  -> MissionCompositionService validated assessment context
  -> immutable semantic/reviewed-composition reference
  -> existing business.review_need catalog entry
  -> existing knowledge.inform_decision or decision.recommend_next_action runtime action
  -> existing graph materialization -> runtime admission -> task materialization
  -> existing queue admission -> lease-owned TaskDispatcher execution
  -> runtime EvidenceRecord when a governed mission is admitted and executed
```

`business.review_need` is a catalog route to the existing decision action, not
a new reasoning or execution service. The interpreter emits its contextual
outcome only when composition already holds a tenant-validated assessment
reference; the same words remain non-executable without that reference. Its action input
marks assessment-derived support as inferred and non-canonical. A contradictory
assessment candidate remains visible but does not become supporting evidence;
capability availability is not a scoring criterion. The resulting decision can
guide reviewed composition, but it is not yet sufficient for decision-episode
materialization or knowledge promotion without the existing canonical outcome
and execution evidence.

When the immutable assessment has exact business subjects, an objective key,
and a timezone-aware evaluation time, the same catalog boundary prefers the
existing `knowledge.inform_decision` action:

```text
assessment semantic context
  -> Knowledge Retrieval
  -> Knowledge Applicability
  -> bounded Knowledge Decision Support
  -> canonical Decision result
```

The adapter supplies neither condition assertions nor fabricated evidence. A
stale, contradictory, unresolved, or inapplicable knowledge record therefore
cannot become decision support. If a tenant charter does not allow
`knowledge.inform_decision`, capability resolution falls back to the existing
assessment-only Decision action; unavailable knowledge cannot erase a
recognized need. Both candidates are read-only and expose the established
`recommendation` artifact contract.

The existing intake-quality owner now accepts a source-bound scope only during
composition confirmation when the immutable semantic snapshot contains a
validated need ID, revision, and non-empty subject references. This removes
the redundant requirement that the operator repeat those internal identifiers
in the review sentence. It does not relax public/direct mission intake, and it
does not waive any other quality, charter, quota, or runtime-admission check.

## Coordinated implementation sequence

1. **Finish runtime truth and bounded operational missions.** Maintain the
   existing dispatcher, coordinator, worker, evidence, and acceptance owners.
   Prove a real provider-read mission through its selected graph, plus a real
   internal CRM write/readback mission. The Gmail/HubSpot request remains only
   partially fulfilled until its missing read and synthesis edges are
   implemented.
2. **Make assessment-backed semantic ingress explicit.** Extend only the
   existing interpreter, lattice, catalog, and artifact contracts so a tenant
   can request an evidence-limited business review or recovery analysis. Its
   inputs must be actual tenant-owned profile, observation, need, outcome, and
   qualified-knowledge references; missing source owners remain a reported
   gap, not invented data.
3. **Bind the result to reviewed meaning.** Use the existing proposal store and
   snapshots to preserve selected alternatives, rejected alternatives,
   dependencies, planned artifacts, acceptance criteria, and need/assessment
   provenance. Material changes create successors; current governance remains
   a separate admission decision.
4. **Close outcome-to-learning continuity.** Reuse outcome evaluation,
   canonical decision episode materialization, durable experience
   consolidation, qualification, retrieval, and applicability. Successful work
   alone neither resolves a need nor promotes knowledge.
5. **Run progressive tenant-generic proofs.** Start with read-only review,
   then internal CRM persistence/readback, then governed external reads. Use
   an Ajenda commercial case and an unrelated tenant case. Each proof must
   inspect artifacts, evidence, task/mission state, outcome semantics, and
   tenant isolation—not merely a handler return value.

## Non-goals and guardrails

- No second planner, business-state database, evidence ledger, runtime,
  policy engine, or knowledge authority.
- No automatic external outreach, contact, or provider write from a need or
  recommendation. Existing governance decides whether composed work is
  admitted.
- No causal claim from KPI correlation, mission completion, or temporal
  sequence alone.
- No customer-attested measurement presented as independently verified source
  evidence.
- G.R.A.F.T.+ remains observational proof tooling; it cannot authorize work.

## Current proof state

- Focused unit, contract, and static validation cover the implemented runtime
  recovery and CRM composition changes.
- PostgreSQL/Redis Testcontainers proofs cover the bounded CRM task lifecycle
  and durable retry/dependency recovery path.
- `tests/integration/intelligence/test_business_need_composition_spine_real.py`
  proves real PostgreSQL persistence from tenant-owned need and assessment,
  through immutable semantic/reviewed snapshots and existing
  `knowledge.inform_decision` composition, to governed mission confirmation
  and its task graph. Its runtime case continues through the existing launch,
  graph-materialization, runtime-admission, task-materialization,
  queue-admission, lease, and `TaskDispatcher` owners. It verifies the
  completed internal-read action, released lease, durable decision evidence,
  empty Redis processing state, and immutable selected-candidate strategy
  provenance. The proof uses only isolated PostgreSQL and Redis test
  containers; it does not contact a provider or tenant data.
- `tests/integration/intelligence/test_change_c_full_learning_lineage_real.py`
  proves the separate canonical outcome → decision episode → qualification →
  later applicable knowledge-decision chain. Its measurements are explicitly
  customer-attested fixtures, never asserted as independently verified facts.
- The full non-integration suite requires a separately captured result before
  release handoff; a detached local run must not be reported as a pass.
- Broad business-readiness and learning-reuse mission composition now has a
  bounded assessment-reference ingress. It still requires real tenant-owned
  assessments and, for runtime proof, canonical decision/outcome evidence;
  it does not infer those records from broad natural-language review prompts.
