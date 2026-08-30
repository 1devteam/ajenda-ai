# VR-01 — Revenue Operations Capability Baseline

**Baseline revision:** `d8a786c383d79f985663ebc1c0428d819f2d6b4a`  
**Inventory:** [`vr01-revops-capability-inventory.v1.yaml`](vr01-revops-capability-inventory.v1.yaml)  
**Decision:** [`D8_REVENUE_OPERATIONS_V1_DECISION.md`](D8_REVENUE_OPERATIONS_V1_DECISION.md)  
**Status:** Development corpus measured; held-out release corpus and promotion thresholds pending

## Outcome

The selected Revenue Operations workflow has useful runtime-bound components, but current code does
not prove an outcome-complete vertical. Research, qualification, enrichment, drafting, optional
email delivery, and optional CRM update actions exist. Typed artifact continuity and a read-only
mission-level RevOps assembler now exist, including independent deliverable completion and
approval/effect/receipt projection. Canonical end-to-end orchestration, held-out quality, real
provider reconciliation, and release proof remain incomplete.

No release-readiness score is assigned. The initial development run against the baseline revision
passed 6 of 10 cases. The corrective semantic slice now passes all 10 declared development
expectations, including fail-closed clarification for unsupported and unresolved long-context
clauses. These are diagnostic results, not promotion scores. Unit tests establish local contract
behavior, not held-out product competence or production provider safety.

## UPG/LAP baseline

### Responsibility

VR-01 inventories the existing semantic, planning, action, provider, and proof surfaces and defines
the evaluation work required before changing planning behavior. It does not mutate runtime state,
enable actions, grant approval, select a model provider, or promote the product.

### Dependencies

- D8 supplies the authorized product boundary.
- The mission-composition job catalog, resolver, interpreter, compiler, action schemas, ability
  manifests, registry, vertical roles, and templates supply the current implementation vocabulary.
- Targeted unit/contract tests and validation sentinels supply bounded proof.
- Real PostgreSQL/Redis and provider sandboxes are required later; they were not exercised here.

### Pitfalls

Catalog maturity may be mistaken for reachability; aliases may hide missing manifests; unit tests
may be reported as outcome quality; templates may be treated as runtime authority; simulated output
may be labeled external; planner-generated approval may be treated as independent authorization;
averages may hide unsafe individual cases; development prompts may leak into held-out evaluation.

### Invariants

- This inventory is derived from implementation and grants no authority.
- Unknown, unavailable, uncredentialed, or unauthorized work remains blocked.
- External effects are not enabled by this artifact.
- Held-out results must be linked to a corpus version, runner version, code revision, and raw result
  artifact before they can support a release claim.

### Proof

The original inventory was produced at the exact revision above. On the 2026-08-18 V1 working tree,
the authority sentinel reports 15 reviewed sinks: 11 canonical boundaries and four daemon-spine
sinks, with zero `competing_http_spine` and zero `exception_bypass` entries. The former HTTP
claim/start/run mutations are 410 tombstones, and approval/retry re-enter ordinary admission.

## Verified delta map

| Layer | Implementation entry point | Verified state | Selected-V1 gap | Closure artifact |
| --- | --- | --- | --- | --- |
| Intent interpretation | `mission_composition/intent_interpreter.py` | Bounded regex-based interpretation with coverage/readiness checks | No versioned RevOps held-out corpus or measured clause/refusal quality | Corpus runner and baseline report |
| Job vocabulary | `mission_composition/job_catalog.py` | Eleven selected jobs are `runtime_bound` | Semantic overlap and missing outcome on `sales.research_context`; maturity is not readiness | Drift-free derived inventory |
| Action selection | `mission_composition/capability_resolver.py` | Deterministic registered-action selection and credential hints | `crm.research` lacks a direct manifest; provider readiness not release-proven | Reconciled action/job/provider inventory |
| Plan/graph preview | `mission_composition/plan_compiler.py` | Dependency preview and partial input bindings | First-output-only bindings, incomplete typed artifact identity, and self-issued authorization | VR-02 contracts plus PR-10 authorization fix |
| Fixed templates | `vertical_ops/plan_templates.py` | Separate queueable research and email templates | No selected end-to-end RevOps template; several selected jobs absent | Versioned RevOps know-how contract |
| Internal actions | action registry plus sales/GTM/Knowledge/decision handlers | Registered with Pydantic inputs and evidence contracts | Product quality and cross-stage binding unmeasured | Held-out and canonical-runtime proof |
| Email delivery | `gtm.email_send` | Registered, credentialed, high-risk, idempotency-required, disabled by default | Independent approval and crash/effect receipt promotion proof missing | PR-10/PR-11 plus Gmail sandbox matrix |
| CRM update | `gtm.crm_upsert` | Registered hybrid internal/external write, idempotency-required, disabled by default | Independent approval, provider truth, and effect receipt promotion proof missing | PR-10/PR-11 plus HubSpot sandbox matrix |
| Runtime | worker loop, dispatcher, tool authority | One daemon claim/start/run spine; approval and retry re-enter admission | Real PostgreSQL/Redis race/fault proof remains | PR-07/PR-08 integration artifacts |
| Evaluation | no versioned RevOps corpus/runner found | Absent | No development/held-out separation or measured baseline | VR-01 corpus, runner, sealed cases, raw report |

## Development baseline result

The versioned non-executing runner at `scripts/validation/vr01_revops_baseline.py` evaluated ten
development scenarios. The initial run exposed four gaps:

| Case | Failure |
| --- | --- |
| `dev-draft-only-001` | “do not ... update CRM” still selected `update_crm`, causing a connection block |
| `dev-paraphrase-002` | Paraphrased qualification was missed and material clauses were unmatched |
| `dev-contradiction-007` | Conflicting send/do-not-send language did not request clarification |
| `dev-long-context-010` | Prohibitions were misread as requested CRM/publish outcomes and material clauses were dropped |

Across all ten cases, forbidden executable actions remained absent from `allowed_actions`. That is
useful fail-closed evidence, but it does not erase the semantic failures or prove downstream runtime
safety.

The follow-up semantic slices corrected coordinated CRM/publish negation, send-policy contradiction
detection, qualification paraphrases, over-broad HubSpot source matching, and explicit typed
deliverable-clause accounting. The corpus now passes 10/10, and `dev-long-context-010` now reaches
`proposal_ready` with its requested deliverable represented structurally. That closes the former
interpretation gap only. Typed artifact continuity and mission-level deliverable assembly are now
unit-proven, but canonical runtime completion, held-out quality, and production provider safety
remain unproven and promotion-blocking.

## Required corpus structure

VR-01 next needs versioned, machine-readable cases separated into:

- `development`: visible cases for deterministic interpreter/validator work;
- `held_out`: sealed release cases unavailable to prompt/template development; and
- `fault`: controlled missing-credential, provider-failure, ambiguous-effect, and stale-approval
  fixtures that do not contact production systems.

Each case must identify scenario class, instruction, tenant-safe fixture references, expected
material clauses, allowed/forbidden outcomes and jobs, required clarification, expected review
boundary, required deliverable sections, provider mode, and prohibited effects. Expected action
names constrain validation; they do not grant execution authority.

The runner must report per case, not only averages:

1. material-clause coverage and unmatched high-risk clauses;
2. intent/outcome/job selection;
3. clarification and unsupported-action refusal;
4. graph validity and required dependencies;
5. input-binding validity;
6. forbidden/unavailable action selection;
7. credential and review readiness;
8. deliverable rubric fields available at composition time;
9. wall time and deterministic local cost counters; and
10. a stable raw result keyed by corpus, runner, and code versions.

Model factuality, draft quality, provider latency/cost, final deliverable completion, and effect
safety cannot be honestly measured by the current composition-only runner. They require later
provider and canonical-runtime stages and must remain `not_measured` in VR-01.

## Dependency-ordered next work

1. Add sealed held-out case metadata and archive development raw results in CI without exposing
   held-out instructions to prompt/template development.
2. Ask the owner to approve numeric promotion thresholds and operational budgets using the metric
   definitions, before any release comparison.
3. Fix the four measured semantic cases and the four inventory drift items without adding another
   executable catalog.
4. The code-first VR-02 contract may be implemented without inventing promotion thresholds, but it
   must remain promotion-blocked until inventory/corpus acceptance and owner budgets exist.
5. Keep optional delivery and CRM update disabled for promotion until PR-07 through PR-11 and their
   real provider/race/fault artifacts pass.

### Sealed held-out execution contract

The runner accepts an external corpus through `--corpus` and never emits prompt text. A held-out
corpus must declare `"corpus_kind": "held_out"` and `"sealed": true`, and the evaluator must be
invoked with an independently recorded `--expected-corpus-sha256 sha256:<digest>`. A missing or
mismatched digest fails before evaluation. External paths are redacted to `<external>/<filename>`
in the result while the report records corpus ID, kind, seal state, digest, runner version, code
revision, dirty-worktree state, per-check totals, and case results.

The development corpus cannot be relabeled as held-out evidence. Held-out instructions and expected
results must be authored and sealed outside the implementation/prompt-development loop, then made
available to the release runner without committing their plaintext to this repository.

## Validation recorded

The current development corpus passes 10/10 declared cases. Targeted V1 tests and the contract,
runtime-authority-inventory, migration-seed, and ability-rollout validation scripts pass. Provider
sandbox proof, a sealed held-out score, and production-like runtime proof have not run and are not
represented as passing. See `V1_PATH3_IMPLEMENTATION_STATUS_2026-08-18.md` for current gate details.
