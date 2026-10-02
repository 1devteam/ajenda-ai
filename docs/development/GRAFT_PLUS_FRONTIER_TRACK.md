# GRAFT+ Frontier Track

The Frontier Track is a parallel, non-runtime lane for ambitious or unconventional ideas in an
existing Ajenda program. It does not replace or alter standard GRAFT+. Both tracks use the same
canonical dependency graph, but they produce separate artifacts so reviewers can compare the
proven implementation path with the proposed frontier path.

## Standard GRAFT+

Standard GRAFT+ maps current implementation, blast radius, authority, invariants, and proof. It
guides changes that may be implemented in the existing program.

## Frontier GRAFT+

The frontier artifact captures:

- a falsifiable hypothesis and target outcome;
- alternative candidate paths and counterfactuals;
- deliberate unknowns and expected failure modes;
- experiments and reversible seams;
- non-negotiable invariants and authority boundaries;
- promotion criteria, rollback, and a kill switch.

Frontier artifacts are planning evidence only. They cannot dispatch work, call providers, resolve
credentials, register handlers, grant permissions, approve side effects, or become runtime truth.
Promotion requires a normal GRAFT+ impact/proof pass and explicit review.

## Generate and compare

```bash
python scripts/validation/graft_plus_frontier.py \
  --frontier-spec docs/templates/graft-plus-frontier-spec.v2.json \
  --impact-report artifacts/graph-impact-report.json \
  --output artifacts/frontier-validation.json \
  --comparison-output artifacts/frontier-side-by-side.json
```

The side-by-side artifact records the frontier proposal separately from standard GRAFT+ metrics and
states the promotion boundary explicitly. A frontier proposal may be rejected, remain experimental,
or become a promotion candidate; none of those states changes runtime authority.

## Evidence-ready Frontier v2

Schema version 2 makes a frontier proposal reviewable as a durable research record. It requires:

- named accountable, technical, and review owners;
- explicit unknowns and expected failure modes;
- a unique experiment ID, measurable success signal, measurement method, rollback, and durable
  `artifacts/` path for every experiment;
- an evidence policy describing required artifacts and retention;
- promotion evidence before a proposal can enter `promotion_candidate` status.

The validator records a canonical proposal hash, graph hash, owner, experiment IDs, evidence
requirements, and promotion boundary in the side-by-side artifact. This makes a frontier result
reproducible and prevents a passing structural check from being mistaken for empirical success.

Use v1 only for compatibility with historical proposals. New work should copy
`docs/templates/graft-plus-frontier-spec.v2.json`,
replace its example content with a real hypothesis, and retain the generated validation,
comparison, and experiment-result artifacts under `artifacts/frontier/<proposal-id>/`.

The Frontier Track still does not execute experiments. An experiment result must come from an
explicitly governed proof path or a documented non-runtime analysis. Promotion requires standard
GRAFT+ impact, invariant, runtime-artifact, and review proof; the Frontier validator cannot promote
itself.
