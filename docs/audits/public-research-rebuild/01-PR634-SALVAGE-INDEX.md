# PR #634 salvage index — source code inventory, not acceptance

Recorded: 2026-10-27
Repository: `1devteam/ajenda-ai`
Original PR: https://github.com/1devteam/ajenda-ai/pull/634
Base observed in original PR: `02571d448efdaaae7e63b5ad1c5559375db6ffe5`
Preserved head: `5fbc84ab5b46f7cc6358f842f55a77072efedffb`
Immutable reference by SHA; dedicated archive branch: `archive/public-research-pr634-5fbc84ab`
Clean recovery branch: `rebuild/public-research-evidence-first` (created from `main`, **not** from #634).

## Source lineage — three distinct levels

1. **Original investigation (primary historical findings):** [00-ORIGINAL-INDEPENDENT-INVESTIGATION.md](00-ORIGINAL-INDEPENDENT-INVESTIGATION.md), reconstructed from the full 423-line user-supplied historical review. It was not originally numbered F01–F20. The new O01–O10 identifiers are for navigation only.
2. **Later implementation handoff and old PR:** #634, archived at its exact SHA. The later F01–F20 handoff must not be treated as a verbatim citation or numbered copy of the original investigation.
3. **Post-PR independent review:** R01–R20 in [02-INDEPENDENT-DEFECT-LEDGER.md](02-INDEPENDENT-DEFECT-LEDGER.md). These are additional source hypotheses/defects needing precise reproduction, not original discoveries retroactively.

## Use this index correctly

The old PR introduced ~1,176 additions and 160 deletions across 26 files. Green tests do not establish that its verification, empty-result, browser or commercial qualification invariants were correct. **No full PR merge, wholesale cherry-pick, or automatic copying of test expectations.** Review each indexed hunk against the fresh baseline and apply only a verified correction. Retain original historical commits and tests for comparison.

Status vocabulary: `salvage candidate` = promising design/code, **not** independently approved. `rework` = behavior concept needed but old patch is not acceptable as-is. `historical only` = reference, not authoritative.

## Code index — all 26 changed files

| File(s) in PR #634 | Index classification | Relevant bounded change / prerequisite |
|---|---|---|
| `backend/app/config.py` | Salvage candidate | Enumerate configured `duckduckgo_html`; explicitly settle legacy `ddgs` behavior and diagnostics |
| `backend/services/internet/__init__.py` | Salvage candidate | Export governed `public_search` and provider contracts |
| `backend/services/internet/contracts.py` | Salvage candidate | `SearchAttempt` and `SearchBundle.attempts`; carry attempt records to **both** web actions |
| `backend/services/internet/search.py` | Rework | HTML provider/parser and governed dispatch are valuable; first make transport safe, distinguish challenge/malformed HTML from no hits, preserve status/fallback semantics, and clarify `ddgs` explicit setting |
| `backend/services/internet/browser_session.py` | Salvage candidate with rework | GET/HEAD, block service workers/downloads/WebSockets; preserve origin **port**, test actual browser request interception against controlled server |
| `backend/services/network_egress.py` | Salvage candidate with rework | Remove arbitrary hostname substring block while retaining public-DNS/IP constraints; also reject URL userinfo, constrain response **streaming** bytes, and fix `.local.` false-positive logic |
| `backend/services/mission_composition/interpretation/rule_engine.py` | Salvage candidate | Remove leading bounded quantity tokens from captured industry; test industry/location and named-company isolation |
| `backend/services/mission_composition/capability_resolver.py` | Rework | Explicit contact observation should not be globally implicit; reconstruct intent conditions before changing graph selection |
| `backend/services/mission_composition/job_catalog.py` | Rework | Company qualification and contact observation are distinct; confirm CRM and explicit contact paths before dropping dependencies |
| `backend/services/mission_composition/plan_compiler.py` | Rework | Verified identity as terminal dependency; allow-empty must be narrowly scoped to valid completed-empty evidence, not any empty list |
| `backend/services/mission_runtime_projection.py` | Salvage candidate with contract proof | Transfer declared materialization role and allow-empty semantics through the canonical task projection |
| `backend/services/tools/mission_input_binding.py` | Rework | Completed-empty provenance is useful, but unconditionally clearing `binding_required` based on a nonempty `research_gap` is too permissive; require authoritative evidence of expected producer/output/status |
| `backend/services/tools/sales_action_qualification.py` | Rework, old fix incomplete | Removed some context-derived unsupported facts, but still merges a synthetic `payload.lead` into first observed prospect and falls back to it when prospects are empty |
| `backend/services/tools/standalone_actions.py` | Rework | Reconnect `public_search`, propagate attempts, balanced query variants; fix false no-hit diagnoses, title-based dedupe and `web.search` provenance too |
| `backend/services/worker_runtime_contracts.py` | Rework | Terminal-empty exception must bind to specific verified evidence and declared contract, not only `research_gap` string/list shape |
| `docs/architecture/PUBLIC_RESEARCH_RUNTIME_RECONCILIATION.md` | Historical only | Old PR's disposition and claims; compare with independent defect ledger. Do not treat as conclusive proof |
| `tests/integration/runtime/test_public_research_runtime_live.py` | Salvage harness only | API→queue→lease→dispatcher→persisted evidence→fresh readback is valuable; improve authorization coverage, true positive verified business, explicit negative semantics and controlled Chromium attack case |
| `tests/unit/internet/test_browser_session.py` | Salvage candidate | Read-method and context-option tests; add genuine interception/port rejection |
| `tests/unit/internet/test_search.py` | Salvage candidate | Provider-resolution and HTML parser fixtures; add anti-bot/empty/malformed, fallback and provenance cases |
| `tests/unit/services/test_mission_composition_engine.py` | Rework | Graph terminal contracts useful; test currently **expects** `company=="HVAC"`, an invalid market-category identity |
| `tests/unit/services/test_mission_input_binding.py` | Rework | Completed-empty case useful; additionally prove malformed/missing/failing producer cannot bypass required bindings |
| `tests/unit/services/test_mission_runtime_projection.py` | Salvage candidate | Declared terminal-empty projection test |
| `tests/unit/services/test_network_egress_hostnames.py` | Salvage candidate | DNS/IP false-positive tests; add actual `.local` boundary and connection-level constraints |
| `tests/unit/services/test_worker_runtime_service_transaction_contract.py` | Rework | Empty terminal contract proof needs genuine upstream lineage and no fallback pseudo-prospect |
| `tests/unit/tools/test_sales_actions.py` | Rework | Target constraints test misses composition-provided `lead`; use real composed lead and empty-input cases |
| `tests/unit/tools/test_standalone_actions.py` | Salvage candidate with correction | Provider wiring/variant budgeting; test collisions (same title/different domains), provider failures and attribution |

## Existing code outside PR #634 that must be fixed **before** promotion

- `backend/services/internet/page_read.py`: `real=True` without checking HTTP status, including 403/404/503; do not equate transport with observation.
- `backend/services/tools/web_action_contacts.py`: self-derived domain verification, loose company-token checks, Dallas fallback for short/absent location, no-contact placeholder counted toward contact completion.
- `backend/services/tools/web_action_identity_policy.py`: short industry token exclusions; directory blacklist is not independent proof of official identity.
- `backend/services/mission_composition/action_input_research.py`: market industry placed into `company`.
- `backend/services/mission_composition/action_input_sales.py`: composition-generated `lead` with market category as company and unobserved industry/location.
- `backend/services/tools/sales_action_research.py`: contact merge/real-contact semantics require provenance-aware identity matching.
- `backend/services/mission_composition/deliverable_runtime_artifacts.py` and `deliverable_runtime_read_model.py`: materialized bare empty list does not alone explain insufficient evidence to operator.

## Provenance of independent review

The original PR received independent review submissions:
- https://github.com/1devteam/ajenda-ai/pull/634#pullrequestreview-5672481646
- https://github.com/1devteam/ajenda-ai/pull/634#pullrequestreview-5672501247
- https://github.com/1devteam/ajenda-ai/pull/634#pullrequestreview-5672695879
- https://github.com/1devteam/ajenda-ai/pull/634#pullrequestreview-5672710072

Reintroduction standard: restore separation between authorization, provider choice, egress and evidence before accepting any changes. Source ownership established; a failing regression reproduced; minimal correction applied; positives and negatives pass; no governance weakening; then comprehensive runtime proof. See adjacent independent defect register and rebuild order.
