# Public research causal simulation protocol — implementation-grade test harness

Branch: `rebuild/public-research-evidence-first`. This protocol is intentionally local and deterministic. **No independent simulator reimplements Ajenda logic.** Every scenario invokes real production modules using controlled/mock inputs at external boundaries.

Executable test suite: [`tests/simulation/test_public_research_causal_invariants.py`](../../../tests/simulation/test_public_research_causal_invariants.py).

## Run the new tests in isolation

From the checked-out recovery branch, using Ajenda's existing Python development environment:

```bash
python -m pytest tests/simulation/test_public_research_causal_invariants.py -q -rA \
  --junitxml=/tmp/ajenda-public-research-simulation.xml
```

The file is deliberately in `tests/simulation/` instead of existing `tests/unit/` to keep this **intentionally fail-first** experiment separate from ordinary unit/contract/deployment CI until corrections are in place. This is not a permanent exception: migrate accepted invariant tests to the existing unit/integration suites once the exact source owner is corrected and the test becomes green. Before changing source, archive baseline XML and failure messages; after fixes, rerun the **same** scenarios.

No test result has been claimed here; the new suite **has not been executed by the reviewer**, because the full private checkout and Python environment are not in this runtime.

## Simulation matrix

| ID | Controlled inputs / real code invoked | Expected invariant | Baseline outcome predicted from source (not executed) | Blast-radius/consumer |
|---|---|---|---|---|
| SIM-01 | `research_observe_contacts` with HTTP 200 official site, HVAC/Dallas text, no email/phone | Verified identity 1, observed contacts 0, contact acceptance false | **Expected fail:** placeholder has `real=True`; accepted count 1 | `observed_count`, `condition_observations`, `accept_met`, lineage |
| SIM-02 | Same official site with actual observed email | Verified 1, contact acceptance true, contact count 1 | **Expected pass** (positive control) | Prevent overly restrictive no-contact fix |
| SIM-03 | `research_observe_contacts` with candidate Quiet HVAC, search-result host `leadlanding.example`, generic HVAC/Dallas page | Identity unverified | **Expected fail:** self-derived host plus weak company-token HVAC | Artifact validation, qualification, operator |
| SIM-04 | Real `interpret_instruction` → `build_research_action_input` with industry-only public target | `company=None`, while public query retains HVAC | **Expected fail:** `company=industry` | Provider source search, named-company logic |
| SIM-05 | Real interpretation → `build_sales_action_input` → `sales_qualify` without bound evidence | No synthetic scored/qualified rows; fail-closed ValueError is permitted | **Expected fail:** composition `lead` scored | Qualification and terminal artifacts; not yet a proof of valid-empty terminal completion |
| SIM-06 | Same composed input with one real verified prospect missing observed industry/location | No planning criteria promoted into prospect | **Expected fail:** context copying and seed `setdefault` | Score, `qualification_dimensions`, future enrichment |
| SIM-07 | Real intent → resolver → catalog dependency compiler | Public verifier is a qualification dependency; implicit contact observer absent when no contact requested | **Expected fail:** verifier selected but not wired | Graph edges, world-state input bindings |
| SIM-08 | Direct explicitly provided lead with real email | Standalone lead still scored | **Expected pass** (positive control) | Preserve authorized single-lead flow |
| SIM-09 | `research_observe_contacts` output → fake completed `ExecutionTask` → production `_observe_acceptance_reasons` | Contact objective unmet, produced 0 | **Expected fail:** upstream `accept_met=True` hides gap | Mission acceptance rollup |
| SIM-10 | Fake completed intermediate discovery task → production `materialized_artifact_for_task` | Raw unverified public hit is not materialized | **Expected pass** (existing safeguard) | Preserve raw-vs-verified distinction |

A source-based failure prediction is **not** a substitute for the actual pytest result. Record the observed result with traceback, branch SHA and environment.

## Experimental controls

- **One intervention at a time:** Preserve all scenario inputs byte-for-byte while changing a responsible production function. If a test must be updated because the correct schema changes, record both old and new expectations and why.
- **Hold legitimate cases constant:** SIM-02, SIM-08, SIM-10 guard against easy but destructive solutions.
- **No external claims from mocks:** These tests prove handler, policy, graph and acceptance behavior on synthetic evidence. They do **not** establish live search relevance, browser write blocking, DNS pinning, CRM integration, real queue/lease/durability, or external provider correctness.
- **Trace causality not just counts:** Capture emitted `prospect_candidates`, `verified_prospect_candidates`, `observed_contacts`, `condition_observations`, `scored_prospects`, `qualified_prospects`, `accept_met`, `research_gap` and binding edges. Never infer a business fact from a planner context value.
- **Deduplicate evidence:** Distinguish test observation, source-inspected prediction, and runtime integration result. The same fail-first test is the comparison record, not another manually written summary.

## Follow-on simulation expansions — exact existing owners

1. `network_egress.NetworkEgressAuthority.vet_https_url`: controlled DNS and IP truth table (`metadata.io` with public vs private addresses; `*.local`; embedded `.local.`; userinfo; redirected targets). Verify actual safety rather than hostname substring heuristics.
2. `internet.search.public_search` and `standalone_actions.web_research/web_search`: provider matrix of HTTP 200 real positive, valid empty, 200 challenge, 429, timeout and Instant Answer empty fallback. Record per-provider attempts and distinguish discovery from verification.
3. `mission_input_binding.apply_input_bindings`, `worker_runtime_contracts._validate_declared_output_contract` and `deliverable_completion.evaluate_deliverable_completion`: exact completed-valid-empty / all-rejected / producer-failed / upstream-missing / malformed output states. This must use production `ExecutionTask` with declared metadata, **not** a manually inferred permissive Boolean.
4. `browser_session.run_browser_session`: real controlled Chromium/server negative POST/WS test and origin port matrix with no public-state mutation. Mocks alone cannot validate page scripts or route behavior.
5. PostgreSQL/Redis integration: composition → graph → admission → queue → lease → dispatcher → evidence persistence → fresh-session operator readback, including tenant isolation and CRM-only regression.

## Graduation gates

- **G0:** Baseline source SHA, run results, failure set archived.
- **G1:** One bounded fix turns its matched fail-first invariant green **without** regressing positive controls.
- **G2:** Compiler/binder/evidence/read-model simulation confirms side effects on all dependent branches.
- **G3:** Controlled network/Chromium and local PostgreSQL/Redis runtime proofs confirm effects mocks cannot measure.
- **G4:** Only then comprehensive CI and independent merge review.

For baseline G0, do **not** mark pending simulation findings as repaired simply because the code change appears sensible. Do not introduce a separate simulation engine or add paid testing services; all probes use installed pytest, existing models and deterministic fixtures.
