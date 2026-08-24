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

## Contamination boundary

Research-only PRs and commits created to instrument or document this study are excluded from the Ajenda development population. This directory must not modify Ajenda runtime behavior, production dependencies, migrations, CI semantics, architecture authority, or product behavior.

PR #460 is recorded as the **provisional intervention boundary** for the first graph-assisted production correction. The treatment boundary may only be refined from contemporaneous repository evidence about graph adoption, and any refinement must be documented rather than selected based on outcome metrics.
