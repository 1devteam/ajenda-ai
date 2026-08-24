# 1DevTeam PR Cascade Study — Initial Research Protocol

**Protocol version:** 0.1  
**Recorded:** 2026-08-24  
**Research organization:** 1DevTeam  
**Primary longitudinal system:** Ajenda AI

## Purpose

Measure whether AI-assisted software changes performed over a locally bounded reasoning scope generate downstream corrective work when the true architectural blast radius is larger than the scope considered during the original change, and evaluate whether graph-assisted architecture reasoning changes that behavior.

This protocol is recorded before exhaustive PR classification. It is intentionally phrased as questions and falsifiable hypotheses rather than conclusions.

## Primary research question

Does mismatch between the reasoning/change scope of a software PR and its actual architectural blast radius predict subsequent corrective PR cascades?

## Secondary research questions

1. How frequently does one merged change introduce a defect or incomplete contract that requires a later corrective PR?
2. How frequently does a change expose a pre-existing defect rather than introduce it?
3. What are the depth, width, duration, and engineering cost of corrective cascades?
4. Which architectural nodes, edges, contracts, and boundaries disproportionately participate in cascades?
5. Does dependency centrality predict corrective-cascade probability or severity?
6. Are cross-boundary changes more cascade-prone than changes contained within one architectural boundary?
7. How often do original PR tests pass even though later evidence demonstrates system-level incompleteness?
8. Are failures better explained by poor local code generation or by incorrectly bounded system context?
9. What fraction of engineering activity is corrective rework rather than new capability or intentional evolution?
10. Does increasing architectural explicitness reduce cascade frequency or depth?
11. Does graph-assisted development increase first-pass architectural completeness?
12. Can dependency information predict a minimum sufficient reasoning boundary for an AI-assisted software change?
13. Do procedural instructions to reason system-wide compensate for the absence of an explicit structural system representation?

## Population

The initial retrospective population is the merged Ajenda AI pull-request history prior to the graph-assisted intervention period. Closed-but-unmerged PRs are excluded from production-causality counts but may be retained separately as process evidence.

The prospective population begins at the graph-assisted period and uses the same classification and outcome definitions wherever possible.

Research-only instrumentation/documentation PRs for this study are excluded from both populations.

## Provisional intervention boundary

PR #460 is provisionally designated as the first graph-assisted production correction for before/after comparison. PRs #450–459 and their actual diffs/history must be inspected to establish graph introduction and capability maturation. The boundary may be refined only from contemporaneous implementation evidence and must be documented before outcome comparison.

## Unit of analysis

Primary unit: merged pull request.

Secondary units:
- causal PR-to-PR edge;
- corrective cascade;
- architectural component/boundary;
- changed file/module/contract;
- proof/test surface.

## Evidence hierarchy for causal edges

### Grade A — direct causal evidence
A later PR, review, issue, commit, or test explicitly identifies an earlier merged PR/change as introducing the behavior being corrected.

### Grade B — strong causal inference
No explicit statement is present, but merge ancestry, diff evidence, contract history, and affected implementation establish that the earlier change introduced the behavior corrected later.

### Grade C — exposure
The earlier change did not create the underlying defect but exposed, activated, or made observable a pre-existing weakness.

### Excluded from corrective causality
- planned feature sequencing;
- intentional requirement changes;
- ordinary extension of a capability;
- documentation-only follow-up without behavioral correction;
- coincidental file overlap;
- dependency/tool upgrades unrelated to an earlier Ajenda behavioral change.

Ambiguous relationships must remain unclassified rather than forced into a causal category.

## Core measurements

- corrective descendant count;
- cascade depth;
- cascade width;
- time to architectural closure;
- PR distance to correction;
- first-pass architectural completeness;
- corrective-rework ratio;
- repeated-boundary recurrence;
- subsystem cascade rate;
- code/dependency centrality;
- change centrality;
- failure/cascade centrality;
- graph-selected blast-radius coverage;
- test/proof coverage of eventual affected surface.

Where line counts or elapsed time are used, they are descriptive proxies and must not be equated directly with engineering effort without qualification.

## Architectural hotspot definition

A hotspot is not merely frequently changed code. Candidate hotspots are architectural nodes/boundaries showing a combination of high dependency centrality, change centrality, and corrective/failure centrality. Thresholds must be defined from the dataset rather than selected to highlight preferred components.

## Confounders and alternative explanations

The analysis must account for, or explicitly discuss:
- normal product evolution;
- rapid intentional iterative delivery;
- increasing system size and complexity over time;
- changing test maturity;
- changing AI/model capability;
- changing development instructions and review practices;
- security hardening that intentionally discovers latent defects;
- large PRs creating more opportunities for defects simply because they change more surface;
- temporal proximity causing false causal attribution;
- PR descriptions that retrospectively overstate causation.

## Falsification / disconfirmation conditions

The central hypothesis would be weakened if one or more of the following are observed:
- corrective cascades are rare after exhaustive classification;
- cascade probability is not associated with architectural blast-radius mismatch;
- most apparent cascades are planned evolution rather than corrective rework;
- graph-assisted changes do not improve first-pass closure or reduce corrective descendants after accounting for change size and complexity;
- larger architecture-aware scopes increase regressions or rework enough to offset expected benefits;
- procedural system-wide reasoning performs comparably to explicit graph-assisted reasoning.

Negative or mixed results must be retained and reported.

## Research integrity rules

1. Preserve raw evidence separately from interpretation.
2. Never classify causation from PR adjacency alone.
3. Record uncertainty and evidence grade.
4. Distinguish introduced defects from exposed latent defects.
5. Distinguish corrective work from intentional evolution.
6. Keep retrospective and prospective analyses comparable.
7. Do not move the intervention boundary based on favorable outcome metrics.
8. Version changes to definitions and report their effect on results.
9. Research-generated PRs are excluded from the development population.
10. Findings belong in `findings/` only after reproducible analysis.
