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
- Direct `POST /v1/missions` initially uses its separate structured-intake
  contract. Its subsequent compile path can recompose, but intake has not
  been migrated to canonical interpretation.
- Successful unit, contract, and recovery workflows do **not** prove a
  successful real business mission or live runtime compatibility.

## Historical corpus discrepancy (not waived)

The historical corpus `docs/contracts/mission-interpreter-corpus.v1.json`
currently disagrees with the interpreter on two cases:

- `crm-deal-records`: corpus expects `observe_contacts` from a request to
  save contacts, although the instruction does not explicitly ask to observe
  or collect public contact information.
- `internal-crm-readback`: corpus expects `qualify_prospects` although the
  instruction requests research, contact observation, persistence, and
  read-back without qualification language.

Both relevant original #569 regex and outcome branches were inspected and
remain unchanged by this PR. Neither expectation is silently modified to
obtain a passing build. The corpus gate remains failing and blocks merge until
the requested outcome semantics and corpus are adjudicated together.

## Merge gate

Keep PR #729 draft until all changed-source lint/format, the focused
interpreter/lattice/epistemic/ontology/compose/API suites, the historical
mission contract corpus, recovery operations checks, and GRAFT architecture
adjudication pass at the same head SHA. Separately require live business-mission
proof and explicit entry-point migration approval before a production rollout.
