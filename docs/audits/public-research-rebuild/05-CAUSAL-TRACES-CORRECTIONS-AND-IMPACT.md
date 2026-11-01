# Causal code traces — correction design and influence on Ajenda's existing system

Snapshot: **`rebuild/public-research-evidence-first`**, 2026-10-27, following reviewer correction `acc8c7bc` to `page_read.py`. Historical PR #634 is archived at `5fbc84ab`; the present analysis is of **main-derived recovery code**, not the closed PR head.

Primary historical diagnosis: [00-ORIGINAL-INDEPENDENT-INVESTIGATION.md](00-ORIGINAL-INDEPENDENT-INVESTIGATION.md).
Work ownership and current test state: [04-FILE-LEVEL-CORRECTIVE-OWNERSHIP.md](04-FILE-LEVEL-CORRECTIVE-OWNERSHIP.md).

**Evidence convention**: **[S]** directly visible source mechanism; **[D]** derived control/data-flow influence; **[P]** proposed correction with precise owners, to be validated by tests; **[U]** not established by a full PostgreSQL/Redis/Chromium run. Paths and approximate 1-based line spans refer to recovery branch and will drift after repairs.

## T01 — Market scope becomes named-company and score evidence

**[S] Producer:** `backend/services/mission_composition/action_input_research.py:42-46`, `build_research_action_input` computes `company=entity.name or industry or instruction` even for generic `HVAC companies in Dallas`. `WebResearchInput.company` in `backend/services/tools/schemas.py:556-573` is an **optional named target**, distinct from the search query.

**[S] Separate sales producer:** `action_input_sales.py:23-36, 80-101` emits `lead={"company":"HVAC (Dallas)","source":"mission_composition","industry":"HVAC","location":"Dallas"}`, with `prospects=[]` and `context.binding_required=True`.

**[S] Consumer:** `sales_action_qualification.py:160-178` (1) falls back to this `lead` when bound `prospects` is empty; (2) copies `context.industry/location/intent/automation_opportunity` into **every** prospect; (3) `lead.setdefault` copies seed `industry/location/source` onto the **first** bound prospect. `_qualify_one:67-115` scores industry/location/intent/source as if prospect evidence. Its `ranking_only` path can mark a verified identity qualified on identity alone by design—do not conflate rankability with commercial purchase intent.

**[D] Consequences:** `scored_prospects` can contain a composition-only pseudo-company. Qualified row fields and `business_fit`, `automation_opportunity`, `urgency` or thresholds can be inflated from mission instructions, then flow to `qualified_prospects`, enrichment, drafts, and `revops_deliverable_prospects.py:265+`.

**[P] Correct in existing owners:**
1. `build_research_action_input`: only use an **actual explicit named entity** for `company`; keep category under `query` and `industry` targeting; inspect explicit name extraction fallback to prevent category leakage.
2. `build_sales_action_input`: for composed public market discovery, leave seed `lead` empty or solely an explicit named account; preserve scope in `context` exclusively. Do not change direct named-lead or CRM-source behavior without positive regression.
3. `sales_qualify`: only derive `prospects_in` from bound observed records for composed `binding_required` research; retain standalone explicit-lead calls. Delete the *context-to-prospect* and *seed-to-first-prospect* field promotion; expose market targeting under `qualification_evidence.target_market_constraints` if needed, without scoring these as observed attributes.
4. In no-prospect case return empty `scored_prospects/qualified_prospects` and a **separate** research result gap (see T04), never `_qualify_one(seed)` as authoritative outcome.

**Exact regression cases:** public HVAC Dallas + no upstream results => zero scored/qualified pseudo-prospects; two real named candidates without observed industry/intent => neither gains those fields; explicit named company direct call stays valid; internal CRM-only qualifications still use tenant records and preserve established outcomes.

## T02 — Identity verification is self-referential; artifact schema cannot repair it

**[S] Search result origin:** `standalone_actions._prospect_from_web_result:256-291` constructs `company` from the result title and `domain` from that same result's URL; tags `real=False`, `identity_status=unverified`. This correctly makes raw hits untrusted **before** the verification step.

**[S] Verifier:** `web_action_contacts.research_observe_contacts:380-432` obtains `expected_host` from that candidate and `actual_host` from the fetched URL. Equality can be guaranteed by construction, not by independent ownership evidence. The company check is `any` common token (or bypass when company token count <=1); industry and locality are simple string matches; list of forbidden directories is a blacklist, not provenance. `page_record["source_reliability"] = "official"` follows from host equality and blacklist absence.

**[S] Second route:** directory outgoing links `web_action_contacts:440-575` use link text or destination title and destination hostname tokens; when they match broadly, the handler constructs `candidate identity_status="verified"` with both URLs as evidence, despite no independent ownership link beyond the untrusted directory.

**[S] Consumer:** `artifact_schemas._public_prospect_errors:478-494` validates `real is True` and `identity_status=="verified"` **without independently reviewing source trust**. `worker_runtime_contracts._validate_declared_output_contract` trusts typed schema before recording completed task. `plan_compiler._dependency_output_name` and `mission_input_binding` hand verified lists to qualification.

**[D] Consequences:** a false positive decision at the verifier becomes schema-valid, can satisfy row counts, be scored, and appear as a verified prospect downstream. Strengthening only the schema's existing booleans cannot detect this false promotion.

**[P] Correct at the existing verification owner:** represent discovery as a candidate URL, then verify that the observed page actually self-identifies as the named company, with a defensible relationship to the business website and explicit industry/location evidence; keep directory mentions as lower-trust clues. Do not treat same URL-derived host as a second independent observation. Require successful page status (already fixed at `page_read`) and explicit evidence excerpts/attribution; ambiguous ownership -> unverified. `web_action_identity_policy.py` should share exact match semantics with browser-based `web_action_identity.py` to avoid two definitions of verified. Correct short AI/IT/3PL and LA/NY/SF tokens without introducing false substring matches or unrequested Dallas fallback.

**Decision still requiring controlled fixtures [U]:** how a real business's registered brand, DBA, corporate parent and domain aliases prove ownership. Do **not** hardcode a universal company-name equality rule or a new third-party whitelist before demonstrating legitimate positives and adversarial negatives.

**Required end-to-end cases:** result title "Dallas HVAC Contractors" pointing to generic independent lead site and carrying HVAC/Dallas -> unverified; known direct official site with matching brand+service+location -> verified; directory outbound link with arbitrary title -> unverified; genuine official outbound link -> verified if independent company evidence; short labels and missing location; never count a 4xx body as identity.

## T03 — No-contact placeholder influences mission acceptance, evidence lineage and UI

**[S] Producer:** `web_action_contacts.py:624-674` adds a fake `observed_contacts` row (`kind=None,value=None,real=True`) after verifying a company page that has no phone/email. Another placeholder occurs in the directory link resolution branch at ~560. The identity-valid company row itself is legitimate to keep.

**[S] Aggregation:** `web_action_contacts.py:731-879` counts *every* `real=True` item in `observed_contacts` toward `accepted_observation_urls`, `observed_count`, `contact_value_count`, `accept_met`, `condition_observations` and source lineage. This produces an apparently real contact even when no value exists.

**[S] Mission consumer:** `worker_runtime_contracts._observe_acceptance_reasons:164-183` returns **no** contact-coverage gap if `accept_met=True`; `worker_runtime_rollup.maybe_rollup_mission_status:200-248` includes that result when determining mission acceptance. The typed `observed_contacts` schema does not require a nonempty kind/value. `revops_deliverable_prospects._assemble_prospects:222-264` renders observed contacts even if kind/value are None, and the RevOps model preserves `real=True`.

**[D] Consequences:** explicit contact requirements can appear satisfied; evidence lineage can cite a contact that wasn't observed; operator may see an empty contact represented as real; downstream matching can carry this artifact. This is not merely a wrong counter.

**[P] Correct inside existing `research_observe_contacts`:**
- Keep `verified_prospect_candidates`, `pages`, source freshness/verification evidence unchanged for a no-contact company; **do not** append placeholder to `observed_contacts` or `condition_observations`.
- Define valid contact observation as a real or sanctioned fixture observation with valid `kind` (email or phone) **and** nonempty corresponding `value`. Count unique source URLs **only** for contacts meeting this predicate, preserving existing "source pages with contact details" cardinality if that is the operator contract; if quantity means distinct contacts, change contract and consumers explicitly rather than silently.
- Set `accept_met`, `observed_count`, `contact_value_count`, `real` and `research_gap` consistently. **Nuance:** the action's `real` may presently mean real contact observed, while page observations remain in `pages`; clarify before altering `real` globally.
- Preserve evidence of pages separately from contact source lineage; contact-specific source ID only when a real contact exists. Tighten `sales_action_research._has_real_contact` so an item with `real=True` but no contact data cannot count as contactable.
- Update `tests/unit/tools/test_web_actions.py::test_observe_contacts_keeps_verified_company_without_contact_details`, which presently **asserts the wrong placeholder**.

**Required consumer regressions:** valid verified company without contact yields `verified_prospect_candidates=1`, `observed_contacts=[]`, `observed_count=0`, `accept_met=False`, mission contact-acceptance unmet, no phantom RevOps contact; page with valid email/phone passes; fixture and external/internal CRM contracts unchanged unless explicitly reviewed.

## T04 — Zero real results currently becomes a graph/binder failure, not a truthful completed observation

**[S] Discovery:** `standalone_actions.web_research:472-606` retains raw search hits as `prospect_candidates` with `real=False` and verifier flags. If `web_results=[]`, the current `research_gap` expression is `None`; an HTTP-successful zero-result general search is not explicitly classified.

**[S] Graph compiler:** `plan_compiler.compile_task_graph_preview:390-436` marks public discovery as `materialization_role="intermediate"` and `allow_empty=True` when a downstream observer is present. `mission_runtime_projection.py:200+` carries that metadata into the durable expected output contract.

**[S] Worker:** `worker_runtime_contracts._validate_declared_output_contract:133-166` permits intermediate public discovery, but terminal list schemas via `artifact_schemas.validate_artifact_payload:515-526` reject **every empty typed list**.

**[S] Binder:** `mission_input_binding.apply_input_bindings:560-653` requires nonempty `prospects` when `binding_required` for downstream observer/qualifier. It does not distinguish a genuinely completed, zero-result producer from a missing/malformed output.

**[S] Read/acceptance:** `deliverable_runtime_artifacts.py` materializes a completed task's declared artifact only; `deliverable_completion.py` requires requested typed fields and often minimum rows; `worker_runtime_rollup.py` makes incomplete requested deliverable a mission-acceptance reason. This is a **good authority distinction** to preserve.

**[D] Consequences:** zero real companies can fail downstream execution or leave an opaque no-deliverable result instead of a durable truthful `no_verified_business` observation. Conversely, simply switching `binding_required=False` without evidence allows malformed/missing upstream work to masquerade as a valid empty result.

**[P] Narrow contract solution with existing components, not a new layer:**
1. `web_research`: emit an explicit typed outcome category based on *attempt provenance* (`valid_empty_general_search`, `provider_unavailable`, `hits_unverified`, `verified_candidates`) and `research_gap` when appropriate. Keep raw `web_results` and provider attempts.
2. `mission_input_binding`: relax a required empty input **only when** the exact bound upstream task is COMPLETED, expected action/output path match, and its durable result declares an evidence-backed valid empty or all-rejected status; preserve original gap in downstream context/audit. Missing path, unexecuted producer, provider failure or arbitrary nonempty gap string must still fail closed.
3. `worker_runtime_contracts._validate_declared_output_contract` + `artifact_schemas.validate_artifact_payload`: permit a *declared terminal no-data observation* only for the identified public read research lane and with a valid explanatory result envelope. Do not make every typed empty list globally valid. Use the existing `allow_empty` metadata path with explicit terminal contract discriminant as appropriate.
4. `sales_action_qualification.sales_qualify`: no `payload.lead` fallback for this genuine empty case; return empty scores/qualified rows and original gap.
5. `deliverable_runtime_artifacts.py`, `revops_deliverable.py` and `deliverable_runtime_read_model.py`: reflect the original reason through existing read fields (`limitations`, `result_semantics` or approved read contract), without treating zero requested company rows as fulfilled.
6. Preserve `mission_acceptance` and task failure separation; a valid completed zero-result research task can coexist with a **partially_met** commercial mission.

**Critical unproven detail [U]:** precise existing persisted metadata/evidence structure for a terminal empty result at runtime—requires an executable positive+empty+failed task run. Do not hardcode an unrelated output flag or open an uncontrolled exception.

## T05 — Verification selection and qualification binding are not equivalent

**[S] Resolver:** `capability_resolver.route_jobs_for_intent:315-325` adds `research.verify_public_candidates` for public research. However `job_catalog.py:292-321` still declares `sales.qualify_prospects` conditional dependency on `research.observe_sources` whenever observed contacts are missing, even for identity-only qualification.

**[S] Compiler:** `plan_compiler._dependency_jobs_for_selection:134-174` does not inject the public verifier as a qualification dependency; `_resolved_dependency_job_keys:27-43` returns catalog-selected dependencies. `_dependency_output_name:104-134` knows how to bind verifier output, **but only if the dependency exists**. `plan_compiler.compile_planned_steps:230-300` records the actual edge and output binding. `mission_input_binding` then follows the compiled edges, not the mere fact that another verifier node was selected.

**[D] Consequences:** verifier can execute but not control what qualification consumes; an implicit contact job may still run; two distinct verification lanes can produce conflicting or redundant artifacts. This is a graph wiring problem, not a provider deficiency. The historical PR #634 attempted to reconcile this; do not reintroduce its modifications without CRM and explicit-contact contract tests.

**[P] Correction must be coordinated across `capability_resolver.py`, `job_catalog.py`, `plan_compiler.py` and binding tests:**
- Public research without explicit contact request: discovery → public verifier → qualification; bind `$.verified_prospect_candidates` directly into `$.input.prospects`. Do not require `research.observe_contacts` for company-only ranking.
- Public research **with** contact request: explicit `research.observe_contacts` contributes actual observed contact evidence, while qualification still uses the canonical verified company list. Do not double-count two producers of the same terminal artifact.
- Internal CRM-only: retain `crm.read_records` or internal read producer and existing authenticated identity/contact paths; no public verifier or network discovery added.
- Review report/draft/enrichment edges separately to avoid unverified `prospect_candidates` reaching downstream.

**Tests must assert graph dependency keys and `input_bindings` at composition time, then perform the same bindings against fake completed tasks with verified vs unverified payload.** A green handler unit test without this graph assertion cannot close the defect.

## T06 — RevOps assembler has a conditional fallback needing an explicit truth test

**[S]** `revops_deliverable_prospects._assemble_prospects:186-193` uses `verified_prospect_candidates` if present and nonempty, otherwise falls back to `prospect_candidates`. `_record_for_row` then creates a prospect from company or ID without reviewing `identity_status`.

**[S] Existing mitigating control:** `deliverable_runtime_artifacts.materialized_artifact_for_task:35-69` **filters unverified public hits** from `prospect_candidates` when the task's expected output contract has `materialization_role="intermediate"`. `revops_deliverable_runtime._validated_artifacts` also rejects malformed typed payloads. Therefore **do not claim** every raw search result is currently rendered as an operator prospect.

**[D] Residual conditional risk:** if a legacy, non-intermediate, or improperly declared `prospect_candidates` artifact is materialized, or a mixed source has no verified terminal list, the read assembler fallback can project an unverified company without its verification status. Source trace establishes the path; exact normal-runtime exploitability is **unproven**.

**[P] Correction at existing assembler:** for public-source rows, require verified identity before presenting an entry as a verified RevOps prospect. Preserve tenant-owned CRM/fixture rows and historical supported read semantics. Unverified public hits may remain as *separate research observations* if the existing public read contract supports them, but not as a verified company. Test terminal raw unverified artifact, intermediate filtered artifact, verified list and mixed CRM+public.

## Invariants and change impact matrix

| Correction | Direct caller/consumer influence | Must remain true |
|---|---|---|
| Market-only named-company removal | `WebResearchInput.company`, store/CRM lookup scoping, public query construction | Named-company, website-scrape and CRM-only requests still work |
| No synthetic qualification seed | score, qualified rows, downstream enrichment/draft selection | No fabricated company; direct named-lead calls retained |
| Strong identity verification | verifier, artifact schema, binder, qualification, deliverable | Positive official business retained; unknown remains unverified |
| No phantom contacts | handler `observed_count/accept_met`, runtime acceptance, lineage, RevOps contacts | Verified company may exist without contact; contact request remains unmet |
| Evidence-backed empty outcome | worker task completion, binder, typed output, read model, mission acceptance | Missing/failed work never disguised as true empty; commercial quantity not fabricated |
| Correct graph dependencies | resolver, job catalog, compiler, binder, runtime ordering | Public identity not bypassed; internal CRM path remains unchanged |
| Raw artifact fallback guard | RevOps assembler with legacy task artifacts | Mixed internal business evidence remains readable; raw public not called verified |
| Search provider reconnection | standalone handlers, network authority, source provenance | Governance preserved; provider HTTP 200 not treated as market completeness |

**Execution standard:** Create a reproducing failing test for each causal trace (including consumer tests), fix at the existing owner, test all reachable affected call chains, then review both result and negative evidence. No application changes other than already committed `page_read.py` R03 are asserted by this document. Full integration verification is still pending.
