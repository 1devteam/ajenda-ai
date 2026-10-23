# Business Understanding and Need Recognition Contract

**Status:** implemented business-understanding foundation and bounded
need-assessment integration. Autonomous recognition, long-horizon impact
measurement, and learning promotion remain explicitly deferred.

**Baseline:** `fafb93069a70e6a01becaf154c57e67dfa6f7693`

## Purpose and invariant

Ajenda must be able to recognise, explain, and track a tenant business need
even when no available capability can fulfill it. A recognised need is an
analytical claim, not a command, approval, capability selection, or execution
authority.

The governing separation is:

```text
source-owned observations
        -> need hypothesis
        -> candidate responses
        -> existing composition and governance
        -> authorised work
        -> mission acceptance
        -> later independent impact observations
```

No arrow in this model is implicit. In particular, mission acceptance does not
resolve a need, and a need neither starts a mission nor changes a charter,
credential, approval, task, or queue state.

## Source-backed ownership inventory

| Meaning | Existing owner and boundary | What it can establish | Why it is not the need owner |
|---|---|---|---|
| Tenant business profile | `BusinessProfile` in `backend/domain/business_profile.py` and deterministic projection in `backend/services/business_profile/record_sync.py` | Approved reusable tenant facts and provenance; an active profile is unique per tenant | `approved_facts` is mutable current context, not time-versioned operating-state history or a lifecycle of business problems. |
| Operational records and documents | `TenantInternalRecord` and `TenantInternalRecordRepository` | Tenant-scoped mutable account, contact, opportunity, activity, task, document, and relationship records | The supported record types exclude need and obligation; `write_record` overwrites the current JSON value and has no observation/provenance/contradiction lifecycle. |
| Business objects, goals, KPIs, snapshots, and events | `backend/services/ontology/types.py` and `commercial_state.py` | Typed identity, desired outcomes, measurements, point-in-time snapshots, and events with supporting evidence identities | These are Pydantic ontology contracts. No persistent repository or migration owns goals, KPIs, snapshots, or events as tenant operational history. A snapshot explicitly is not system-of-record truth. |
| Runtime evidence | `EvidenceRecord` and `EvidenceRepository` | Durable mission/task/capability provenance and payloads, tenant-scoped | Every record has a required `mission_id`; it cannot be repurposed as general out-of-mission business observation storage or need state. |
| Outcome review | `OutcomeReview`, repository, and outcome-review route | Tenant-scoped mission review with evidence references, gaps, recommendations, and human review fields | It is mission-bound and mutable review metadata, not general business-impact monitoring. The worker bridge only creates a best-effort draft after high-risk GTM side effects. |
| Goal/outcome analysis | `ontology/evaluation.py`, `ontology/outcome.py`, `tools/analysis_actions.py` | Conservatively evaluate supplied goals, KPI deltas, state changes, and evidence gaps | They consume caller-bound typed inputs and return analysis evidence. They do not maintain business state, recognise needs, or persist an impact lifecycle. |
| Qualified knowledge | `KnowledgeQualificationRecord`, `KnowledgeArtifactRecord`, lifecycle, retrieval, and applicability services | Immutable tenant qualification history plus a current applicability projection | It is reusable qualified experience, not a statement that a tenant currently has an unresolved business need. |
| Mission proposal/composition | `MissionCompositionProposal`, `proposal_store.py`, composition phases | Instruction-derived semantic and composition records, clause evidence, revision/supersession metadata | It is an instruction/work proposal owner. It must not be overloaded as the durable owner of a condition discovered without a mission. |

## Required distinction of meanings

The following identities must remain separate even when they refer to the same
business subject.

| Meaning | Example | Owner and mutation rule |
|---|---|---|
| **Business observation** | Monthly revenue declined 12% between two source-dated measurements. | Source owner remains the system of record; Ajenda stores only an attributable observation reference/derived observation when needed. New contrary evidence does not rewrite history. |
| **Need hypothesis** | Retention may require attention because revenue decline and churn observations are compatible. | Tenant-bound analytical lifecycle. It records uncertainty and alternatives; it is neither a fact nor an authority. |
| **Candidate response** | Investigate churn drivers; improve onboarding; test pricing; launch a retention campaign. | Analytical option with evidence, assumptions, and capability availability. It has no selected action or admission authority. |
| **Reviewed composition** | Prepare a churn analysis report using approved sources. | Existing semantic and reviewed-composition snapshots; a reviewed successor is required for material change. |
| **Authorised work** | A governed task may read records or execute an approved external action. | Existing governance, admission, dispatcher, and worker owners only. |
| **Mission acceptance** | The requested analysis report was produced with required evidence. | Existing deliverable and mission acceptance owners. |
| **Business impact** | Churn fell after independently observed follow-up measurements. | Later observation/outcome analysis; it may resolve, weaken, or leave the need open. |

## Implemented logical contracts

Existing storage could not preserve an immutable, attributable observation
history or a need lifecycle independent of a mission. The implemented minimum
responsibility is therefore a **business-understanding record family**, not a
planner, policy engine, action registry, evidence ledger, or worker.

The implementation is `BusinessObservation`, `BusinessNeedRevision`, and
`BusinessNeedAssessment` in
`backend/domain/business_understanding.py`, with tenant-scoped repository and
service boundaries, migrations `0055_business_understanding` and
`0056_business_need_assessments`, and the
`/v1/business-understanding` API. Every write remains inside the caller-owned
tenant transaction; no service method commits or reaches runtime execution.

### 1. Business observation

`BusinessObservation` represents a bounded statement about a business
condition or event. It does not duplicate the raw source payload and does not
replace the source record or `EvidenceRecord`.

Implemented fields include:

- `observation_id`, `schema_version`, `tenant_id`;
- an authenticated producer, affected business subject references, source record
  reference, and safe source fingerprint;
- a bounded observation summary, `observed_at`, `evaluated_at`, confidence,
  limitations, and immutable creation time; and
- optional correction or contradiction references. Correction, expiry, or
  retraction is represented by a later observation and an explicit relationship,
  never destructive replacement.

Existing business-profile facts, internal records, mission evidence, outcome
reviews, and qualified knowledge remain source owners. A `BusinessObservation`
stores attributable references to them only when the condition must persist as
business understanding across missions. It must not copy credentials, raw
provider payloads, or full customer instructions.

### 2. Need hypothesis and revision

`BusinessNeedRevision` represents the meaning Ajenda derives from
one or more observations. It is append-only by revision. A stable `need_id`
identifies a continuing question; each revision records its predecessor and
material reason for change.

Implemented fields include:

- `need_id`, `revision_id`, revision sequence, `tenant_id`, schema/rule version;
- affected business subject(s), a descriptive relevant objective, and related
  need references;
- origin classification: `explicitly_stated`, `observed`, or `inferred`, plus
  tenant-validated observation references;
- bounded need statement, confidence, uncertainty, and priority where supplied;
- links to earlier, duplicate, superseded, or contradictory hypotheses;
- candidate response descriptions with a non-authoritative capability
  availability assessment;
- tenant-validated links to later proposal or mission records; and
- lifecycle status and an independently supported resolution rationale.

The stable need identity is server-assigned and tenant-bound. This foundation
does not yet implement automatic matching of repeated observations; callers
must deliberately select the continuing need and expected revision. It cannot
silently merge different subjects, objectives, or causal explanations.

### 3. Candidate responses and current authority

A candidate response belongs to a need revision until normal composition turns
it into a selected strategy. The foundation stores its caller-supplied,
non-authoritative availability description. It rejects a response that asserts
`grants_execution_authority=true`; it does not itself resolve readiness or
current authorisation.

Current charter permission, credential readiness, approval, quota, provider
eligibility, and side-effect admission remain exclusively owned by the existing
governance and runtime paths. A need record may link to a proposal or an
authorisation receipt for explanation, but that link is not an approval and
must be revalidated at existing execution boundaries.

### 4. Deterministic need assessment

`backend/services/business_understanding/reasoning.py` evaluates a specific,
tenant-scoped need revision using the existing goal/KPI evaluator, catalog, and
bounded qualified-knowledge decision-support result. The assessment persists
an immutable `BusinessNeedAssessment` and returns:

- the business condition, goal/KPI status, explicitly cited supporting and
  contradictory observations, and information gaps;
- competing cause hypotheses with `supported`, `contradicted`, `conflicted`,
  or `unresolved` status;
- candidate responses, assumptions, dependencies, trade-offs, and catalog
  coverage (`catalog_supported`, `partially_mapped`, or `unmapped`); and
- the next justified step and the independent evidence required to claim
  business improvement.

KPI variance establishes a condition, not a causal explanation. A cause or
response is supported only by its explicitly attributed observation IDs or a
separately produced qualified-knowledge influence. The assessment does not
infer that an available capability is appropriate, and an unmapped capability
does not erase an otherwise justified response.

Qualified knowledge enters only through
`KnowledgeDecisionSupportResult`, which already applies retrieval and
applicability rules. It remains derived, non-independent evidence. An
inapplicable, invalidated, or unresolved knowledge influence cannot justify a
response here.

## Lifecycle and temporal continuity

The need lifecycle is analytical, not an execution state machine.

```text
new evidence
  -> recognised / monitoring
  -> challenged <-> revised response hypotheses
  -> response proposed
  -> linked to reviewed composition (optional)
  -> impact monitored
  -> resolved | disproven | superseded | still unresolved
```

- A new observation appends a revision or establishes a distinct need according
  to documented subject/objective/condition matching. It never mutates a
  reviewed mission.
- Contradictory evidence produces an explicit `challenged` or successor
  revision. It must not be discarded because an earlier hypothesis was useful.
- `response proposed` means a response is explainable; it does not mean an
  action is selected, approved, admitted, or executed.
- A mission can be linked only after existing composition produces a proposal.
  The need remains open after a completed mission unless later independent
  observations satisfy the stated impact/resolution condition.
- `resolved` requires post-response evidence appropriate to the need. A task
  completion, delivery receipt, or accepted deliverable is insufficient by
  itself.
- `disproven` requires observations that invalidate the hypothesis, not merely
  inability to execute a response.

Revision writes require a tenant-scoped optimistic revision check and append a
new immutable row with its observation references and predecessor link in the
same caller-owned transaction. The repository locks the current revision and
has a database uniqueness constraint on `(tenant_id, need_id, revision)`; a
concurrent stale session receives a conflict without overwriting the committed
revision. The implementation preserves historical revisions. Retention and
source-deletion classification remain a later spine/retention phase.

## Integration with the two existing intelligence snapshots

Two ingress modes converge but neither blocks the other.

### Explicit customer instruction

`POST /v1/missions/compose` continues directly through interpretation and
composition. It does **not** require a need hypothesis. If an instruction
itself explicitly states a business problem and the product elects to persist
that understanding, a later need revision may cite the instruction clause as a
source; the normal mission remains valid without that side effect.

### Observation-, state-, or knowledge-driven reasoning

Observation inputs can create or revise a need hypothesis and yield an
explanation, clarification request, or candidate response. Only a deliberate
request to compose creates the normal semantic snapshot and reviewed
composition snapshot.

For the implemented need-linked composition:

1. `POST /v1/missions/compose` may include a tenant-visible `business_need_id`
   and revision, plus a matching persisted assessment ID. Composition verifies
   the exact tenant-owned references and records safe fingerprints in
   `CompositionProvenance`.
2. The reference is read-only provenance: it does not add objectives, choose
   catalog jobs, or change the instruction. Direct customer instruction remains
   independently composable without a need.
3. Composition persists paired immutable `semantic_snapshot` and
   `reviewed_composition_snapshot` payloads in the existing durable proposal
   record. Confirmation and compilation compare fresh semantic meaning with
   the reviewed snapshot. A material change to instruction-derived meaning,
   selected catalog jobs, or acceptance criteria requires a successor proposal;
   current charter, credential, and provider readiness continue through their
   independent authority checks.
4. Revalidation is transient until its proposal lineage, mission/plan/graph,
   and evidence are written in the caller-owned transaction. The process cache
   is never authoritative when a database session is available.
5. A proposal link is explanatory only. The need revision cannot mark a mission
   accepted, authorised, or resolved.

## Tenant, authority, privacy, and compatibility invariants

- Every observation, need, revision, source reference, candidate response,
  proposal link, and impact assessment is tenant-bound. Existing business
  profile, internal-record, evidence, review, knowledge, mission, proposal,
  observation, and need references are resolved through their tenant-scoped
  owners before persistence. External-provider and customer-instruction
  sources require an opaque source ID; they remain an attributed producer
  assertion until a future connector or instruction ledger supplies a durable
  owner.
- Read paths never update a profile, internal record, knowledge artifact,
  mission, need lifecycle, or authority state. Explicit write paths are subject
  to their existing owner and audit requirements.
- A need cannot create an `ExecutionTask`, task graph, queue item, provider
  invocation, external effect, or approval. It can only be consumed by existing
  composition and review boundaries.
- Evidence references preserve source ownership. Need/observation records do
  not turn `EvidenceRecord` into a cross-mission general evidence store.
- Credentials, tokens, authorization codes, raw provider payloads, and private
  instruction content are excluded. References and safe fingerprints are used
  where sufficient for reconstruction.
- Existing missions, profiles, outcome reviews, evidence, and knowledge records
  remain readable. Missing pre-contract lineage is represented as
  `historical_unknown`, never backfilled as observed fact.

## Representative proof matrix

| Scenario | Required result |
|---|---|
| Explicit customer request for a market report | Direct composition succeeds without creating or requiring a need hypothesis. |
| Tenant revenue record plus independently observed churn increase | Append attributed observations; recognise a retention-risk hypothesis with alternatives and uncertainty, not an asserted cause. |
| Capability unavailable | Need remains explainable and open with `capability_missing`; no task or external action is created. |
| Two observations support competing explanations | Need becomes challenged or receives distinct revisions; neither explanation becomes fact solely from plausibility. |
| Accepted advertising mission | Deliverable acceptance is true if its contract is satisfied; the revenue/retention need remains unresolved until post-response evidence exists. |
| Later measured improvement | A separate outcome/observation can support resolution only when subject, timing, evidence, and stated impact condition match. |
| Repeated scanner/session update | One atomic revision succeeds; stale revision conflicts without losing the other observation or changing a reviewed mission. |
| Cross-tenant source reference | Rejected before persistence and not exposed through projection. |
| Revoked charter or unavailable credentials | A previously recognised need remains readable; current composition/admission is denied or blocked by existing owners. |
| Ajenda self-operation reference case | The same generic contracts represent acquisition, marketing, administration, overhead, and service-delivery conditions; no Ajenda-only job or state type appears in shared contracts. |

## Implementation evidence and remaining work

The foundation and assessment are proven by
`tests/integration/intelligence/test_business_understanding_real.py`:
append-only continuity, independent impact observation before resolution,
stale revision conflict from two database sessions, cross-tenant reference
rejection, PostgreSQL RLS fail-closed behavior, cause/response evidence
separation, supported-but-unmapped responses, mapped-but-unjustified
capabilities, and inapplicable qualified knowledge. The composition contract
tests prove paired snapshots, semantic materiality comparison, transactionally
owned revalidation, and that need-linked composition remains a read model with
no execution authority.

Remaining work is deliberately outside this layer: automated
goal/outcome-to-observation projection, provider-backed investigation of
unresolved causes, formal retention/tombstone policy, long-horizon business
impact monitoring, and qualified-learning promotion/reuse.

This contract deliberately does **not** authorize: a generalized state graph,
automatic CRM mutation, an autonomous campaign engine, a new execution loop,
or an intelligence-specific policy layer.
