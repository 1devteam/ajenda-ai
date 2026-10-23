# Unified Intelligence — Phase I Inventory

**Baseline:** `fafb93069a70e6a01becaf154c57e67dfa6f7693` plus the local
business-understanding foundation (migration `0055_business_understanding`).
**Graph:** `docs/architecture/dependency-graph.v1.json`, SHA-256
`1648a0a4a37f0eb03b79919923f3cf10ea56e228be2ccf5bf40cf6200036eb21`
**Status:** source-backed inventory; it does not alter runtime authority.

This document records the implementation topology that the Unified Intelligence
Reconciliation Program must preserve and connect. It is an inventory, not a
replacement architecture or an execution authority.

## Converging business-understanding inputs

The current ordinary composition path begins with a customer instruction. That
is one valid ingress, not the only legitimate source of business
understanding. The reconciled architecture must allow four independently
attributable inputs to converge without imposing an artificial order:

```text
approved business state ─┐
customer instruction ────┼─> business understanding and needs reasoning
observed evidence ───────┤       (non-authoritative)
qualified knowledge ─────┘                    |
                                               v
    semantic framing -> options -> catalog selection -> validated plan
```

Each input may be absent. A recognised condition must not be discarded merely
because Ajenda cannot currently perform a response, and recognition itself
does not create permission, queue work, or alter a reviewed plan. The current
source supplied foundations for several inputs but not a durable need owner.
The foundation now provides tenant-scoped observations and append-only need
revisions, plus optional read-only composition provenance. It intentionally
does not make needs an automatic planner input or a runtime authority.

## Canonical composed-mission path

`POST /v1/missions/compose` in
`backend/api/routes/mission_composition.py` invokes
`MissionCompositionService.compose`. The current ordinary composition path is:

1. `intent_interpreter.interpret_instruction` creates `MissionIntent`, including
   clauses, semantic units, extracted entities, quantities, explicit constraints,
   deliverable requirements, ambiguity, and interpretation provenance.
2. `proposal_phase.compose` reads the active tenant Business Profile and passes a
   bounded profile context to the interpreter. It resolves tenant semantic aliases
   and builds a pre-routing `SemanticSelection`.
3. `capability_resolver.route_jobs_for_intent` retains catalog ownership of job
   selection. Semantic bindings may add only catalog-defined jobs.
4. `structured_planner.build_catalog_planner_proposal` validates the deterministic
   catalog result for ordinary composition. A provider-backed structured planner is
   currently optional and only considered when vertical know-how is selected.
5. `capability_resolver.resolve_jobs` maps jobs to registered, manifested,
   charter-allowed, connection-ready actions. It selects no runtime work itself.
6. `plan_compiler` creates typed planned-step and task-graph previews;
   `intelligence_envelope` records gaps and non-authoritative composition
   algorithms.
7. `proposal_store.put_proposal` writes the proposal record. Confirmation and
   compilation revalidate dynamically, then respectively persist a mission graph
   or refresh an existing graph. Neither phase queues work.
8. Existing runtime admission, task materialization, queue admission,
   `WorkerRuntimeService`, and `TaskDispatcher` remain the sole execution path.
9. `deliverable_completion`, the deliverable runtime read model, and
   `worker_runtime_rollup` independently evaluate artifacts and mission acceptance.

## Extended Phase I: business understanding and need signals

The following inventory extends the existing composition map; it does not
restart it. The classifications identify actual ownership and current
reachability, not intended product semantics.

| Input or concept | Existing owner and source-backed behavior | Current consumer / reachability | Disposition |
|---|---|---|---|
| Approved business identity and operating context | `BusinessProfile.approved_facts` and provenance in `backend/domain/business_profile.py`; deterministic profile projection in `backend/services/business_profile/record_sync.py` | `MissionCompositionService._profile_context` and `resolve_business_context` read a bounded profile view before composition or tool execution | Durable tenant context, but not a complete business-state record and not a need hypothesis |
| Goals, KPI definitions, state snapshots, and events | Typed ontology models in `backend/services/ontology/commercial_state.py` | Inputs to `analysis.evaluate_goal_progress`, `analysis.evaluate_outcome`, decision support, and knowledge semantics | Implemented semantic/evaluation contract. No repository or migration persists goals, KPIs, snapshots, or events as a tenant business-state history. |
| Performance and business-impact evaluation | `evaluate_goal_progress` in `ontology/evaluation.py`; expected-versus-observed assessment in `ontology/outcome.py` | Registered governed analysis actions in `tools/analysis_actions.py`; catalog job for explicit goal-progress requests | Evaluates caller-bound inputs conservatively; it is not automatic need recognition or a durable impact monitor. |
| Mission acceptance | `backend/services/mission_acceptance.py`, `deliverable_completion.py`, and `worker_runtime_rollup.py` | Worker roll-up and customer-visible mission projections | Answers whether promised artifacts/contract requirements were produced. It does **not** establish that the motivating business condition improved. |
| Outcome review and business-facing findings | Tenant-scoped `OutcomeReview` in `backend/domain/outcome_review.py`; route/repository and worker-created draft review path | Mission read models, deliverable projections, knowledge-change proposal read model | Durable review evidence, explicitly non-executing and not an automatic business-state update. The automatic bridge is limited to completed high-risk GTM external effects and is best-effort, so it cannot serve as general impact monitoring. |
| Qualified knowledge | Retrieval, applicability, lifecycle, and ledger services in `backend/services/knowledge/*` | Direct governed knowledge/decision actions; ordinary composition only when explicit decision support is requested | Tenant-scoped and applicability-bounded, but not yet a normal attributable preplanning input. |
| Need hypothesis, priority, candidate response, and resolution lifecycle | `BusinessObservation` / `BusinessNeedRevision`, repository, and service in `backend/services/business_understanding`; migration `0055_business_understanding` | Tenant-scoped API and optional read-only provenance on normal mission composition | Durable analytical hypothesis only. It does not own canonical facts, automatically produce work, or establish business impact from mission acceptance. |

### What the existing foundations prove

- A `BusinessStateSnapshot` is explicitly a point-in-time operating
  representation, not system-of-record truth or evidence; it cites evidence by
  identity and does not update itself (`commercial_state.py`).
- A `BusinessEvent` represents a possible state change and likewise does not
  update a snapshot. This supports observation without claiming that the
  resulting condition has been resolved.
- Goal-progress and outcome evaluation fail conservatively on missing KPI or
  evidence data. An `OutcomeEvaluation` distinguishes progress, regression,
  inconclusiveness, and insufficient evidence; it does not persist an
  `OutcomeReview` or execute work (`ontology/outcome.py`).
- `analysis.evaluate_goal_progress` currently fabricates an explicitly marked
  mission-instruction goal when durable goal context is unavailable. Its output
  records `evaluation_scope=mission_instruction_only`; that is valid for a
  bounded analysis task but must not be promoted as durable business state.
- A decision episode already distinguishes a recommendation, its observed
  execution fidelity, and subsequent outcome evidence
  (`ontology/decision_feedback.py`). This is a useful downstream learning
  foundation, not an upstream need-recognition authority.

### Required outcome separation

Two non-equivalent results must remain separate throughout the program:

1. **Mission acceptance:** the authorised mission produced the specified
   deliverables under its acceptance contract.
2. **Business-need resolution / impact:** later evidence establishes whether a
   condition, opportunity, obligation, or risk improved, persisted, or
   worsened.

For example, an advertising deliverable can be accepted even while a
revenue-decline need remains unresolved. Business impact may be observed long
after task completion. Neither task success nor deliverable acceptance may
silently set a need to resolved.

### Implemented Phase 1 need-hypothesis contract

The implemented model treats a recognised need as a tenant-bound,
non-authoritative claim separate from a proposal. It persists references to
existing source owners and preserves:

- affected business subject and relevant objective;
- supporting observation/evidence references and observation dates;
- origin classification: explicitly stated, observed, or inferred;
- confidence, uncertainty, and unresolved questions;
- priority when available;
- candidate responses with caller-supplied, non-authoritative capability
  availability;
- proposal and mission references validated against their tenant owners; and
- a separately evidenced resolution lifecycle, never inferred from mission
  acceptance.

The new contract remains outside the catalog, planner, governance layer,
worker, and evidence ledger. Need recognition can create an explanation, a
recommendation, or a request for review; it cannot admit or execute work.

## Ownership map

| Responsibility | Current owner | Reachability |
|---|---|---|
| Instruction normalization and interpretation | `mission_composition/interpretation/*`, `intent_interpreter.py` | ordinary composition |
| Semantic concepts, tenant aliases, and advisory job bindings | `semantic_lattice/*`, `semantic_vocabulary.py` | ordinary composition, before and after catalog routing |
| Business jobs and dependencies | `job_catalog.py` | ordinary composition |
| Readiness and action choice | `capability_resolver.py` | ordinary composition; governance is consulted but not replaced |
| Deterministic plan contract | `structured_planner.py`, `plan_compiler.py` | ordinary composition |
| Proposal/confirmation/compile persistence | `proposal_phase.py`, `proposal_store.py`, `confirmation_phase.py`, `compile_phase.py` | ordinary composition |
| Task execution authority | runtime admission/materialization/queue services and workers | governed runtime only |
| Artifact schemas and deliverable acceptance | `artifact_schemas.py`, `deliverable_*`, `worker_runtime_rollup.py` | post-execution |
| Causal composition observations | `runtime_evidence_ledger.py` | observational; non-authoritative |
| Knowledge retrieval and decision support | `knowledge/*`, `tools/knowledge_actions.py` | catalog composition only when decision support is explicitly requested; otherwise direct governed action |
| Decision episode materialization and consolidation | `decision_episode_materialization.py`, `durable_experience_consolidation.py` | direct governed actions; not automatically composed after ordinary missions |

## Catalog and analytical reachability

The catalog contains 30 runtime-bound jobs. Jobs with supported outcomes are
ordinarily routable when the interpreter recognizes that outcome. Jobs without
supported outcomes are intentionally dependency- or context-gated:

- `research.verify_public_candidates` is injected for public prospect discovery.
- `intelligence.retrieve_knowledge` and `intelligence.advise_next` are added only
  when the interpreter emits `decision_support_requested`.
- `sales.research_context` is dependency-driven.

The action registry exposes additional governed analytical and learning actions,
including `analysis.evaluate_outcome`,
`analysis.assess_attribution_integrity`,
`analysis.materialize_decision_learning_signal`,
`analysis.qualify_pattern_knowledge`, and
`knowledge.consolidate_learning_history`. They are implemented and registered,
but ordinary composition does not yet select them as a post-outcome learning
sequence. They therefore remain direct/specialized paths, not evidence that the
ordinary learning loop is closed.

`ontology/algorithms.py` declares seven deterministic algorithms. Only these
have confirmed ordinary consumers:

- `gtm.evidence_completeness.v1` and `gtm.source_confidence.v1` in
  `intelligence_envelope` during composition;
- `gtm.runtime_artifact_completeness.v1` in `worker_runtime_rollup` after
  runtime acceptance evaluation.

`geo.service_area_match.v1`, `identity.business_verification.v1`,
`gtm.lead_fit_score.v1`, and `gtm.duplicate_identity_resolution.v1` are declared
and tested as algorithms, but this inventory has not found an ordinary
composition or worker consumer. They require an explicit applicability and
consumer disposition in Phase V; they must not be inserted into every mission.

## Confirmed contract strengths

- Semantic routing occurs before catalog selection and is revalidated against
  selected jobs afterward.
- The deterministic catalog path is validated by the structured-planner
  contract; an LLM is not required for ordinary planning.
- Revalidation records retain `reviewed_proposal_id`,
  `revalidated_from_proposal_id`, and a revision reason.
- The runtime path distinguishes planned graph, admission, materialization,
  queueing, task completion, typed artifact completion, and mission acceptance.
- Deliverable completion is deliberately independent of terminal task status.
- Knowledge retrieval, applicability, and decision support preserve tenant
  scope and remain non-authoritative.

## Confirmed gaps to carry into later phases

1. The proposal storage record is a mutable JSON projection keyed by proposal ID.
   It has revision lineage fields but does not yet provide the charter's two
   immutable snapshot contracts or an explicit materiality-comparison result.
2. Composition receives business-profile context before routing, but current
   qualified knowledge is not yet a bounded, attributable preplanning context
   input. Knowledge retrieval is composed only for explicit decision support.
3. Outcome analysis, episode materialization, experience consolidation, and
   future retrieval exist, but normal mission completion does not deliberately
   connect them as one qualified learning loop.
4. Four declared algorithms lack a confirmed consumer relationship. Their
   disposition must be explicit rather than inferred from registry presence.
5. Existing alternatives are recorded as action candidates. The approved
   recovery-equivalence contract from the architecture charter does not yet
   exist as a durable reviewed composition field.

## G.R.A.F.T.+ baseline

`build_dependency_graph.py --check` passes at this revision. The initial
intelligence-surface impact analysis covered 12 core source files, produced 126
changed nodes, 482 downstream dependencies, 604 upstream consumers, and no
unmapped changed files. Its proof selection requires unit and integration
coverage plus live-runtime review because this surface crosses action contracts,
tenant isolation, worker authority, side-effect approval, and durable state.

The generated graph is observational evidence. It is not a source of execution
authority and does not decide which components belong in ordinary composition.

## Phase 1 entry criteria

After the Phase I extension, Phase 1 must first decide whether the existing
business-profile, evidence, outcome-review, and knowledge owners can represent
a recognised need without overloading mission acceptance, an outcome review, or
qualified knowledge. Before any persistence change, the implementation must
complete UPG/LAP for both the need-recognition and proposal-revision boundaries.
It must prove one atomic transaction contract for a reviewed proposal revision,
its semantic snapshot, reviewed composition snapshot, and producer-owned
lineage. Existing historical records must remain readable and must report
unavailable historical causation honestly rather than synthesizing it.
