# Ajenda PR #569 — bounded semantic feedback contract

## Authority and baseline

PR #729 is a recovery-scoped change based on PR #569 merge commit
`f995ab9098b6837ac38978ffb0ae1a37a43ab9b8`.
It does not grant tool or runtime execution authority.
It does not import PR #725 implementation or post-recovery governance.

## Producer → consumer

1. `MissionCompositionService.compose` loads tenant-approved terminology and
   passes instruction and a concept-only `SemanticSelection` to
   `intent_interpreter.interpret_instruction`.
2. `interpret_instruction` delegates to
   `interpretation/feedback_loop.py`. The unchanged deterministic core
   `_interpret_instruction_pass` remains the sole owner of `MissionIntent`
   construction and interpretation-readiness evaluation.
3. The feedback loop calls the canonical
   `semantic_lattice.resolver.build_semantic_selection` with candidate
   canonical outcomes and `validate_job_bindings=False`; there are no
   selected jobs at this point. It revisits interpretation only for additional
   concept information or an explicitly grounded outcome hint.
4. An accepted candidate cannot remove a prior outcome, regress readiness,
   or change target, quantity, contact/send/publish/write policy, forbids,
   timing constraints, or contradictions. The loop terminates on convergence,
   cycle, rejection, or the three-pass limit. Decisions are recorded in the
   typed `MissionIntent.interpretation_passes` contract.
5. The final `MissionIntent` is consumed by existing coverage, epistemic,
   job routing, action selection, plan compilation, readiness, intelligence
   envelope, and composition provenance. **No downstream owner was moved.**
6. After jobs have been selected, composition invokes the same resolver with
   its default `validate_job_bindings=True`, preserving the original
   post-job conflict check.

## Existing knowledge and memory

`semantic_lattice/definitions.py` holds versioned shared semantic concepts
and relationships. Approved tenant aliases are loaded from business profile
`approved_facts.semantic_terminology_overrides`; the resolver does not query
historical mission records or learn relationships automatically. Composition
proposals persist the selected semantics, but that persistence is not
experience-based retrieval.

The old `semantic_vocabulary.build_semantic_selection` compatibility
entry point delegates to the canonical modular resolver so new and old callers
do not independently implement relationship matching.

## Evidence integrity

Semantic-context matches carry `semantic_concepts.*` field paths. The ontology
source-confidence metric and epistemic decision-confidence fallback exclude
those contextual matches. The full `SemanticSelection` is preserved in
composition provenance. The bounded `MissionIntent.interpretation_evidence`
contract still caps entries at 50; the interpreter now records
`semantic_evidence_omitted_count` instead of silently hiding the overflow.

## Deliberate limits

- The proven semantic action-feedback family is explicit qualification /
  lead-quality assessment; merely naming a concept cannot request work.
- The loop is bounded deterministic re-interpretation, **not** general semantic
  reasoning, autonomous memory retrieval, or learning from failed missions.
- Direct `POST /v1/missions` now invokes the same tenant-aware canonical
  interpreter before creating a mission. The full typed intent is retained in
  `mission_intake.objective_interpretation.intent` as an explicitly
  **objective-only**, non-authoritative read model. Structured success criteria,
  constraints, budgets, approval requirements, allowed actions, and allowed
  tools are still owned by intake and are not rewritten by inferred outcomes.
  This is initial entry-point alignment, **not** a complete reconciliation
  between structured intake policy and all interpretation findings.
- Successful unit, contract, and recovery workflows do **not** prove a
  successful real business mission or live runtime compatibility.

## Historical corpus adjudication (source-backed, not bypassed)

The original corpus had two cases whose expected *requested outcomes* exceeded
what their instructions asked for. Review of original #569 interpretation rules
confirmed this mismatch independently of PR #729:

- `crm-deal-records`: a requested CRM contact write does not independently
  request public contact observation; the full-workflow instruction now
  explicitly says to collect public contact details.
- `internal-crm-readback`: persistence and readback do not independently
  request qualification; the full-workflow instruction now explicitly says
  to qualify the prospects.

Both original exact instruction strings remain in the corpus as new
`-no-implied-*` cases, asserting **no invented outcome**. Thus the six-case
gate protects both requested full workflows and the original negative
interpretation boundaries. No implicit CRM work or contact observation was
added to the interpreter to satisfy an invalid expected set.

## Direct structured mission intake

`backend/api/routes/mission.py:create_mission` calls the shared
`interpret_instruction_with_profile` helper after existing permission and
intake-quality checks. The helper reads only the requesting tenant's active
business profile and supplies approved semantic aliases. The interpretation
snapshot is stored with an explicit `input_scope=objective_only` and
`grants_execution_authority=false`.

A structured mission does **not** have its policies, allowed actions or success
criteria inferred from this snapshot. They continue through the typed intake
contract unchanged. A separate policy-reconciliation review is required
before treating structured intake and freeform composition as equivalent
sources of canonical runtime intent.

## Other structured mission-creation entry points

A source-level scan of direct `Mission` creation identified two additional
routes on the #569 recovery baseline:

- `POST /v1/vertical-ops/missions` creates a mission from an approved
  vertical template and may immediately apply/queue its selected template tasks.
- `POST /v1/ability-runtime/tasks` can create a mission when no existing
  `mission_id` is provided and queue the explicitly selected action.

Both now invoke the same tenant-profile-aware
`build_objective_interpretation_snapshot` helper before creating a mission,
and persist its output under `objective_interpretation` in their existing
mission metadata. The provenance explicitly distinguishes
`input_origin=user`, `template`, and `generated_action`.
Every snapshot has `interpretation_usage=diagnostic_only` and
`grants_execution_authority=false`.

**Scope distinction:** interpreting an objective does **not** yet semantically
resolve every structured template step, action identifier, or action input.
Template/service action resolution and charter/permission/credential/queue
checks remain the pre-existing authority path, not a competing new system.
Thus these routes now participate in canonical **objective interpretation**
but complete typed structured-command interpretation and reconciliation
remain separate production-gate work.

## Merge gate

Keep PR #729 draft until all changed-source lint/format, the focused
interpreter/lattice/epistemic/ontology/compose/API suites, the historical
mission contract corpus, recovery operations checks, and GRAFT architecture
adjudication pass at the same head SHA. Separately require live business-mission
proof and explicit entry-point migration approval before a production rollout.
