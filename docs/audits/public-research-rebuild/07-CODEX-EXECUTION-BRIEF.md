# Codex execution brief — public research corrective rebuild

**Work owner:** Codex CLI, implementing on `rebuild/public-research-evidence-first`.
**Independent reviewer:** ChatGPT, maintaining the source-based findings and reviewing the resulting code and executable proof.
**Tracking:** https://github.com/1devteam/ajenda-ai/issues/635
**Original closed PR (DO NOT MERGE):** https://github.com/1devteam/ajenda-ai/pull/634
**Read-only salvage snapshot:** `archive/public-research-pr634-5fbc84ab` at `5fbc84ab5b46f7cc6358f842f55a77072efedffb`.

## Why this handoff exists

**Codex does not inherit the ChatGPT conversation.** The following are factual source-trace inputs, not a preapproved patch. You are to *read the code yourself*, contest incorrect findings with evidence, run the intentionally red deterministic simulation, implement owned corrections at existing code owners, and rerun the same tests and affected consumers. No broad "make research work" task and no cherry-picking the full abandoned 26-file PR.

The original 423-line investigation was architectural and did **not** contain an F01–F20 list. Do not conflate its findings with later review additions. Read in order:

1. `AGENTS.md` — mandatory operating gates (UPG/LAP, GRAFT+, runtime invariants).
2. `docs/audits/public-research-rebuild/00-ORIGINAL-INDEPENDENT-INVESTIGATION.md` — original root causes O01–O10.
3. `docs/audits/public-research-rebuild/05-CAUSAL-TRACES-CORRECTIONS-AND-IMPACT.md` — production call chains T01–T06 and conditional-risk qualifiers.
4. `docs/audits/public-research-rebuild/04-FILE-LEVEL-CORRECTIVE-OWNERSHIP.md` — per-file owners and test obligations.
5. `docs/audits/public-research-rebuild/06-CAUSAL-SIMULATION-PROTOCOL.md` and `tests/simulation/causal_public_research_invariants.py` — controlled red/green differential simulation.
6. `docs/audits/public-research-rebuild/01-PR634-SALVAGE-INDEX.md` — selectively reusable prior changes.
7. `docs/audits/public-research-rebuild/02-INDEPENDENT-DEFECT-LEDGER.md` and `03-REBUILD-ORDER-AND-PROOF.md` — later R findings and wider proof gates.

Read **the entire source files you intend to edit**, then inspect tests/callers and the canonical GRAFT+ changed-file impact. Do not treat these documents as implementation authority when actual source or runtime tests disagree.

## Startup: establish evidence before changing more production files

Run from Ajenda checkout after fetching and checking out `rebuild/public-research-evidence-first`, with a clean working tree. Record `git rev-parse HEAD`, `git status --short`, Python environment and pytest version. **Do not reset or overwrite local uncommitted user changes.**

First inspect the already reviewer-committed fix:
- `tests/unit/internet/test_page_read.py` at test commit `f424656a` (later style correction `c000e37`).
- `backend/services/internet/page_read.py::fetch_public_page` at code commit `acc8c7bc`. Non-2xx becomes `PageSnapshot(real=False, status_code=<http>, error="HTTP <http>")`; this fix is **not yet runtime-test verified**.

Run:
```bash
python -m pytest tests/unit/internet/test_page_read.py tests/unit/tools/test_web_actions.py -q
python -m pytest tests/simulation/causal_public_research_invariants.py -q -rA \
  --junitxml=/tmp/ajenda-public-research-baseline.xml
```

The second file is an **opt-in red-scenario script** deliberately lacking a `test_` filename prefix; normal discovery should not collect it. Run it explicitly. Predicted source failures are **hypotheses until you run it**, and test harness defects are not evidence of production defects. Note passes, failures, collection errors and any discrepancy with the prior predictions. Save baseline output in a small source-controlled evidence note, not a large or private log; link exact command/result.

## First implementation wave — exact files and corrections

Work sequentially, making **failing tests precede implementation**, then compare regression and positive controls before proceeding. Keep corrections in the existing file owner. Do **not** edit `backend/services/network_egress.py` concurrently with the independent reviewer; that file is reviewer-owned A02 until ownership is transferred explicitly.

### C01 — category is NOT a named company (T01; simulation SIM-04)

**Code:** `backend/services/mission_composition/action_input_research.py::build_research_action_input`, current source around lines 38–83.

**Bug:** `extracted_company = entity.name or industry or _extract_company_from_instruction(source)`; a public market request such as `HVAC companies in Dallas` is emitted with `company="HVAC"`. `WebResearchInput.company` denotes an explicit named target, not an industry category. `standalone_actions.web_research` uses that as an explicit lookup.

**Precise correction:** for industry-only market search, set `company=None`; preserve the category in `query`. Use a genuine named-company entity for `company`; examine text-extraction fallback to ensure it cannot turn "HVAC" back into a fictitious name. Preserve explicit named-company/site-scrape behavior, external CRM reads and public-only source eligibility.

**Tests:** `tests/simulation/causal_public_research_invariants.py::test_market_scope_does_not_populate_named_company_target`, and `tests/unit/services/test_mission_composition_engine.py`. Update any test *currently asserting* `company=="HVAC"` only after recording that it encodes the incorrect behavior. Add distinct market-only/named-company/CRM fixtures.

**Consumers:** `WebResearchInput`; `standalone_actions.web_research` (`explicit_company`, `search_company`, `page_domain`, `crm_search`); intent interpretation/plan validation. A wrong `company` must not reduce general discovery or silently change tenant/private searches.

### C02 — planning-only lead must not become evidence (T01; SIM-05/SIM-06/SIM-08)

**Code:** `backend/services/mission_composition/action_input_sales.py::build_sales_action_input` around 23–101 and `backend/services/tools/sales_action_qualification.py::sales_qualify` around 158–240.

**Bugs:** generator creates `lead={"company":"HVAC (Dallas)","source":"mission_composition",...}`; `sales_qualify` when `prospects=[]` falls back to `payload.lead`; for real candidates it copies `context.industry/location/intent/automation_opportunity` onto observed rows and copies all seed fields to the first prospect via `lead.setdefault`. `_qualify_one` then scores these invented prospect properties, including business_fit/opportunity/urgency.

**Precise correction:** composed public-market qualification must consume observed verified bound prospects only. Keep market targeting separate as planning context/constraints. Do not copy mission target criteria into the company record, including for its first row. When a **genuinely completed empty upstream result** is established, score zero companies. A **missing/failed upstream binding still fails closed**; do not pretend it is genuine empty. Preserve directly supplied named-lead calls and CRM-only qualification.

**Tests:** SIM-05/06/08, `tests/unit/tools/test_sales_actions.py`, composition/binder tests. Create two verified candidates without declared location or intent and show neither inherits those fields. Compare scored dimension values before/after; only source-backed attributes should contribute. Do not alter scoring thresholds simply to make sample qualify.

**Consumers:** downstream `qualified_prospects`, enrichment/drafts/CRM writes, `revops_deliverable_prospects.py`, terminal typed artifacts and mission acceptance. Coordinate the valid-empty binding exception with C07; do not weaken global `binding_required`.

### C03 — contact observation must contain a contact (T03; SIM-01/02/09)

**Code:** `backend/services/tools/web_action_contacts.py::research_observe_contacts`, around 555–578 and 624–674 (two placeholder paths), plus 731–883 (aggregates). `backend/services/tools/sales_action_research.py::_has_real_contact` around 265–292.

**Bugs:** no-contact verified page appends `{"kind":None,"value":None,"real":True}` to `observed_contacts`; output `observed_count`, `contact_value_count`, `condition_observations`, `accept_met`, lineage and `real` can then misrepresent company-page observation as actual contact. `_has_real_contact` accepts an arbitrary `contacts[]` dictionary with `real=True` and no mailbox/phone as contactability. An existing test `test_observe_contacts_keeps_verified_company_without_contact_details` asserts this broken placeholder.

**Precise correction:** keep verified company record and `pages` evidence, but **do not emit a contact row without usable contact kind/value**. Count only observed contact URLs with recognized email/phone values (or explicitly agreed CRM contact-id semantics). Preserve explicit `local_fixture_only` and external CRM contact records, which have distinct legitimate source contracts. Set `accept_met` false for contact-request with zero usable values; maintain accurate gap/lineage and condition_observations. For identity-only `collect_contacts=False`, success should depend on verified companies, not contact acquisition.

**Tests:** SIM-01/02/09 and `tests/unit/tools/test_web_actions.py::test_observe_contacts_keeps_verified_company_without_contact_details`, plus `_has_real_contact` tests. Assert verified row 1, observed contact row 0, `accept_met=False`, mission acceptance reason nonempty; positive email/phone verified and accepted. Check `worker_runtime_contracts._observe_acceptance_reasons`, `worker_runtime_rollup.maybe_rollup_mission_status`, evidence source identity and `revops_deliverable_prospects._assemble_prospects`.

### C09 — qualification must bind verified public identities, not incidental contact observation (T05; SIM-07)

**Code:** `backend/services/mission_composition/capability_resolver.py::route_jobs_for_intent` around 315–325; `job_catalog.py` entry `sales.qualify_prospects` around 289–323; `plan_compiler.py::_dependency_jobs_for_selection`, `_dependency_output_name`, `compile_planned_steps`; `tools/mission_input_binding.py::apply_input_bindings`.

**Bug:** the resolver may add `research.verify_public_candidates`, but selecting it alone does **not** make it a dependency of `sales.qualify_prospects`. Catalog can instead expand `research.observe_sources` merely because `observed_contacts` is missing. Compiler knows the verifier output mapping, but only wires selected dependency keys.

**Precise correction:** for public **identity-only** market research → `research.discover_prospects` then `research.verify_public_candidates` then `sales.qualify` binding `$.verified_prospect_candidates → $.input.prospects`; contact observation is **not** implicitly required. For **explicit contact request**, contact observer remains separately selected, and its actual contacts may feed qualification; avoid duplicate terminal verifier candidates. For **internal CRM-only**, preserve `crm.read_records` and existing authorized read/binding without public verifier or external network calls. Do not solve this by adding a second unverified raw-candidate path.

**Tests:** SIM-07, `tests/unit/services/test_mission_composition_engine.py`, `test_mission_contacts_clause.py`, `test_mission_input_binding.py`, CRM-source cases. Assert **compiled graph edges and input_bindings** plus the actual `apply_input_bindings` output, not only job selection. Re-run both explicit contact and CRM positive controls.

## Second implementation wave — contract decisions grounded in real code

These are **not** already-proven algorithms and require targeted simulation and peer review before patching.

### C05 — company identity (T02)

**Owner:** `web_action_contacts.py` (around 380–432; directory linked-site around 440–575), `web_action_identity_policy.py`, `web_action_identity.py`. Candidate constructor `standalone_actions._prospect_from_web_result:256–291` derives domain from the search result itself, which cannot independently establish site ownership. Present code verifies with own-URL host equality, any common company token, broad industry/location lexical markers and blacklist absence. `artifact_schemas._public_prospect_errors` checks only `real` and `identity_status` after the observer has made that decision. **Do not fix by rewriting the typed artifact schema into another identity classifier**; correct the observer's evidence semantics, including directory outgoing link claims.

**Proof:** controlled legitimate official site positive; third-party non-blacklisted generic HVAC/Dallas page negative; directory link to unrelated site negative; true linked official site positive; AI/LA, IT/NY, no-location case; no false positive 4xx. Where site-brand/corporate-name matching is unclear, explicitly present competing evidence and conservative unresolved status—not unverified guess plus an invented confirmed identity.

### C04/C08 — governed general search and source lineage (O01–O04/O08)

**Owner:** `standalone_actions.web_research` and `web_search`, `internet/search.py::public_search` and `resolve_public_search_provider_chain`, `internet/contracts.py`, `tests/unit/internet/test_search.py`, `tests/unit/tools/test_standalone_actions.py`.

Current handlers hardcode `_fetch_duckduckgo_instant_answer` instead of calling the existing `public_search` chain. But default chain includes **DDGS package-owned transport** not proven under `NetworkEgressAuthority`; blindly reconnecting chain is unsafe. Safely select governed general-search providers/transport using existing security authority and free provider options, with explicit provider/error/HTTP status/no-hit trace in **both** actions. `local contractor` appended irrespective of industry is misleading; result title-only dedup suppresses valid distinct URLs. 200 challenge page is provider failure, not a market zero-hit. HTTP 200 Instant Answer empty is not evidence of no general search result. Reuse isolated safe source fragments of #634, not the whole PR.

**Proof:** positive real general-search hit, valid empty, 200 challenge, 429/timeout fallback, title collision, credentialed/private destination denied, truthful source partitions. Mocked transport tests first, controlled live read second. Chromium is separate and must not be used as a reason to disable approved general search.

### C07/C12 — exact valid-empty bound lifecycle (T04)

**Owner:** `standalone_actions.web_research`, `mission_input_binding.apply_input_bindings`, `worker_runtime_contracts._validate_declared_output_contract`, `artifact_schemas.validate_artifact_payload`, `mission_runtime_projection.py`, `plan_compiler.py`, `deliverable_runtime_read_model.py`, `deliverable_runtime_artifacts.py`, `worker_runtime_rollup.py`.

A completed intermediate source can legally return no verified candidates; current binder rejects nonempty-required list, terminal typed schema rejects empty lists and scorer may fall back to seed. **Require precise producer identity, completed task, expected output name/type, positive evidence of valid no-results/all-rejected outcome and preserved no-evidence reason** before allowing empty downstream. Missing/failed/malformed provider output is *not* valid-empty. Commercial quantity remains unmet even if observation task is completed. Do not globally relax required inputs or artifact schemas. Full lease-scoped real tasks + persisted metadata proof is needed before determining exact contract fields.

**Proof:** four variants through real `ExecutionTask`: valid-empty, all-rejected, provider-failed, missing/malformed. Downstream score has 0 rows and mission remains partially_met when quantity unmet. Verify reason appears in operator readback after fresh session.

### C06 — read-only Chromium (O06)

**Owner:** `browser_session.py`, browser unit test and controlled local receiving server. Prove no POST/PUT/PATCH/DELETE, WebSocket, service-worker, download or different-origin-port bypasses. Preserve default disabled while unproven; browser restrictions and governed general search are separate.

### C10 — conditional RevOps raw fallback (T06)

**Owner:** `revops_deliverable_prospects._assemble_prospects`. It falls back to raw `prospect_candidates` if `verified_prospect_candidates` list missing/empty, but the existing intermediate artifact materializer **already filters** unverified public rows. Do not claim normal runtime always leaks results. Test legacy unfiltered terminal artifact and mixed CRM/public; only then decide if an additional assembler verification guard is required.

## What to send back for each changed owner (no silent completion)

For each C-id, provide a compact evidence ledger:

| Field | Required content |
|---|---|
| Source reality | Exact owning function + path and original behavior |
| Reproduction | Test case, command, outcome, failure trace, baseline SHA |
| Implementation | Diff/commit with explicit rationale; any finding disproved |
| Blast radius | Callers, graph/binder, evidence, tenant/CRM, artifacts, acceptance |
| Regression | Same scenario after fix + positive controls and observed outcomes |
| Limitations | Tests not run, live proof pending, unresolved choices |

**Phase stop conditions:** A failing simulation due to wrong fixture is a test defect, not a product bug; unexpected state in legacy CRM is a blocker; unverified public hits in a terminal artifact are a blocker; any security or authority bypass is a blocker. Don't auto-merge. Do not spend 15-minute CI cycles on known-red baselines; run focused pytest, ruff, mypy, GRAFT and then one meaningful full CI after the coherent implementation.

**First deliverable:** record the baseline simulation outcomes, apply **C01**, **C02**, **C03**, **C09** where proven and preserve their positive controls, with one coherent group of commits. Before claiming the first wave complete, independently evaluate whether C02 must coordinate immediately with C07 (valid-empty binder): if yes, record it explicitly and prevent fallback by failing closed until C07 is implemented. Do not silently change the definition of completion. Then bring the actual branch/diff and evidence back for independent review.

**Operational limitation:** Saving this brief to GitHub does **not** dispatch commands to a running local Codex CLI. The user must open the recovery branch in Codex and tell it to read this file. It then has the complete source-grounded assignment without needing the current ChatGPT conversation.
