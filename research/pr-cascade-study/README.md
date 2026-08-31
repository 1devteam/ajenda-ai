# 1DevTeam PR Cascade Study

**Research organization:** 1DevTeam  
**Primary longitudinal system:** Ajenda AI  
**Inception date:** 2026-08-24

This directory contains the research protocol and supporting material for a longitudinal study of change scope, corrective PR cascades, architectural blast radius, and graph-assisted AI software development.

The study begins from a neutral empirical question: whether software changes whose inspected/reasoned scope is smaller than their actual architectural blast radius are associated with downstream corrective work.

## Study structure

- `research-protocol.md` — frozen initial research questions, study boundaries, evidence rules, metrics, confounders, and falsification conditions.
- `hypotheses.md` — hypotheses recorded before exhaustive PR classification.
- `definitions.md` — operational definitions and causal classification rubric.
- `provenance-notes.md` — qualitative research provenance and prior development approaches; not empirical proof.
- `methodology.md` — planned reproducible extraction and analysis workflow.
- `data/` — derived datasets generated during the study.
- `analysis/` — reproducible analysis code and outputs.
- `findings/` — empirical findings only after analysis.

## Current evidence-review artifacts

The following artifacts are exploratory evidence records, not findings:

- `analysis/pr-460-496-evidence-review-v0.1.md` — source-bounded review of the provisional graph-assisted/graph-maturing cohort through PR #496, including cohort partitioning, graph-capability timeline, proof topology, planned-slice controls, pre-merge interception candidates, rival explanations, and explicit non-findings.
- `data/pr-460-496-observation-ledger-v0.1.csv` — row-level working classification for PRs #460–#496. Relationship and causal fields remain provisional until source-backed adjudication.
- `analysis/pre-450-comparator-review-v0.1.md` — calibration review containing both planned pre-#450 slicing and explicit corrective descendants, including the #369→#374 chain.
- `data/pre-450-comparator-ledger-v0.1.csv` — relationship-level comparator ledger for currently verified pre-#450 cases.
- `analysis/prospective-revops-graph-evaluation-observation-v0.1.md` — prospective methodological note preserving a current RevOps/graph-evaluation framing concern before the next correction is completed. It is not evidence for or against graph value.

These files deliberately separate repository-observable evidence, working classification, uncertainty, and later causal adjudication.

## Historical analysis provenance

PR #474 previously introduced a larger exploratory analysis/extraction package. Those analysis/data files are not present on the current `main` snapshot used for this evidence pass. Historical versions may be consulted from their Git history as methodology input, but they are not silently treated as current study authority. The current protocol, definitions, hypotheses, methodology, and provenance files remain the governing study documents unless explicitly revised under the study's integrity rules.

## Contamination boundary

Research-only PRs and commits created to instrument or document this study are excluded from the Ajenda development population. This directory must not modify Ajenda runtime behavior, production dependencies, migrations, CI semantics, architecture authority, or product behavior.

`1devteam-web` is a separate repository/workstream. Website changes, including website PRs under active maintenance, are not Ajenda PR-cascade observations and must not be inserted into this study population merely because the work is contemporaneous.

PR #460 is recorded as the **provisional intervention boundary** for the first graph-assisted production correction. The treatment boundary may only be refined from contemporaneous repository evidence about graph adoption, and any refinement must be documented rather than selected based on outcome metrics. The graph/control capability trajectory beginning before #460 must be reconstructed as time-varying rather than assumed to be a binary switch.
