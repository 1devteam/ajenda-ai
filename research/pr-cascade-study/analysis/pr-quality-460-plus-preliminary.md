# Preliminary PR Quality Analysis — PR #460 onward

**Status:** exploratory analysis note; not an empirical finding  
**Analysis snapshot:** through PR #473  
**Population use:** prospective/process evidence only until sufficient downstream observation time exists

## Question

Do Ajenda PRs from the provisional graph-assisted period show a measurable change in PR quality compared with earlier corrective work, and if so, what changed?

This note does **not** equate PR quality with PR size, commit count, prose length, or CI success. It separates immediately observable engineering-process quality from realized downstream outcome quality.

## Quality dimensions used for this preliminary review

1. **Root-defect clarity** — whether the PR identifies the actual defect mechanism rather than only the symptom.
2. **Blast-radius reasoning** — whether dependencies, affected runtime paths, boundaries, or connected contracts are explicitly traced.
3. **Invariant / architecture contract** — whether the PR states the system property that must hold after repair.
4. **Scope discipline** — whether non-goals and unrelated known defects remain explicit rather than being silently absorbed or claimed closed.
5. **Proof quality** — whether proof includes adversarial, integration, concurrency, cross-boundary, or fail-closed tests appropriate to the defect.
6. **Architectural closure evidence** — whether the repair is reconciled against the canonical graph/invariant model and the targeted architectural finding disappears without erasing unrelated findings.
7. **Realized outcome quality** — later corrective descendants, cascade depth, time to closure, and rework. This dimension cannot yet be fairly scored because the post-#460 cohort is heavily right-censored.

The first six dimensions are contemporaneous process/design evidence. The seventh is the outcome measure required for the study's causal claims.

## Cohort handling

### Included production / architecture-process evidence

- #460 — authority-containment correction
- #465 — password-signup verification correction
- #468 — semantic graph hardening; instrumentation intervention
- #469 — RLS/session-boundary correction
- #470 — post-RLS graph certification
- #471 — closed-unmerged idempotency repair attempt; retained as process evidence only
- #472 — durable HTTP idempotency repair
- #473 — atomic single-use credential-transition repair

### Excluded from product-quality comparison

- #461–#464 — Dependabot maintenance PRs; unlike change class
- #466 — research instrumentation/documentation; excluded by protocol
- #467 — invalid prospective pilot / protocol execution error; excluded from treatment-effect analysis

## PR-level assessment

| PR | Root defect | Blast radius | Invariant | Proof | Graph closure | Scope discipline | Preliminary assessment |
|---|---|---|---|---|---|---|---|
| #460 | Strong | Moderate | Moderate | Strong | Not present | Strong | Major improvement in defect description, authorization boundaries, negative scope, and regression proof, but still primarily a conventional multi-surface corrective package rather than machine-reconciled architectural closure. |
| #465 | Strong | Moderate | Moderate | Strong | Not present | Strong | Strong local-contract repair. However, the post-#465 baseline still contained GF-14 verification-token concurrency. This supports incomplete closure of the broader single-use credential-transition invariant, not a claim that #465 introduced that defect. |
| #468 | Strong | Strong | Strong | Strong | Instrumentation itself | Strong | Qualitative intervention in the evidence model. It explicitly represents RLS, egress, and state-ownership/concurrency blind spots and prevents acknowledged defects from being mistaken for repaired defects. |
| #469 | Strong | Strong | Strong | Strong | Strong | Strong | First clear example in this sequence of graph-integrated remediation: migration + runtime session repair are derived from the blast radius, PostgreSQL behavior is tested directly, and graph semantics must show the repaired tables as RLS-complete. |
| #470 | N/A runtime | Strong | Strong | Strong | Strong | Strong | Closure/provenance PR. It distinguishes an intentional pre-tenant control-plane exception from an unexplained RLS gap while requiring repaired and still-open findings to remain correctly classified. |
| #471 | Strong | Strong | Strong | Strong planned | Not realized | Strong | Closed unmerged. It targeted GF-13/GF-27 with Redis ownership while leaving GF-25/GF-26/GF-28 separate. Because it never merged, it is process evidence rather than production outcome evidence. |
| #472 | Strong | Strong | Strong | Very strong | Very strong | Very strong | Root-cause cluster repair rather than independent cache patches. It unifies GF-13/GF-25/GF-26/GF-27 and adjudicates GF-28 under one operation-identity/ownership model, includes 8-way PostgreSQL contention proof, encrypted replay proof, abandoned-claim recovery, and a graph closure ratchet that removes only the targeted finding. |
| #473 | Strong | Strong | Very strong | Very strong | Very strong | Very strong | Shared-invariant repair across three credential transitions. It reuses existing durable rows as transaction ownership rather than adding parallel coordination, proves exactly-one successor under real PostgreSQL contention, and requires the graph to move three findings from violation to enforced while preserving unrelated defects. |

## Observed quality transition

The evidence suggests **two distinct stages**, not one simple before/after switch at #460.

### Stage A — #460 / #465: stronger conventional corrective PRs

These PRs are materially better specified than many earlier Ajenda corrections:

- explicit root defects;
- explicit security/authority consequences;
- extensive regression proof;
- explicit non-goals;
- deliberate merge discipline.

But they still prove closure mainly through implementation tests. They do not yet require the architecture model to show that the targeted invariant is restored while unrelated defects remain visible.

### Stage B — #468 onward: graph-integrated architectural closure

#468 is a maturity point because it explicitly hardens the graph against known blind spots in RLS, egress, and concurrency/state ownership. After that point, #469, #472, and #473 use a stronger repair pattern:

1. identify frozen defect IDs / semantic findings;
2. identify the shared architectural invariant;
3. trace the actual dependency/runtime path;
4. choose a root-level repair mechanism;
5. add proof at the failure mode's real level (PostgreSQL/RLS/concurrency, not only unit mocks);
6. update the canonical graph evidence;
7. require the targeted finding to disappear;
8. require unrelated known findings to remain visible;
9. state explicit non-goals so closure cannot be overclaimed.

That is a qualitatively different definition of "done" from earlier fix + regression-test PRs.

## Important contrast with historical corrective cascades

Earlier Ajenda history contains direct fix-the-fix / incomplete-blast-radius chains such as:

- #58 → #59
- #107 → #108
- #164 → #165 / #166
- #168 → #169
- #369 → #370 → #371 → #372

Those sequences show that passing local proof did not always imply architectural closure. The post-#468 PR pattern attempts to mechanize the missing closure condition rather than relying only on reviewer reasoning.

This is **process-quality evidence**, not yet proof that downstream cascades are reduced.

## PR size does not explain the apparent improvement

The graph-integrated PRs are not uniformly smaller:

- #460: 27 files, 28 commits, +825 / -87
- #465: 24 files, 34 commits, +838 / -572
- #468: 13 files, 21 commits, +1097 / -400
- #469: 21 files, 23 commits, +345 / -21
- #471: 6 files, 8 commits, +447 / -123, unmerged
- #472: 23 files, 17 commits, +1139 / -216
- #473: 11 files, 13 commits, +533 / -34

The observed difference is therefore not "smaller PRs are better." The stronger candidate explanation is **better alignment between reasoning scope, actual blast radius, and proof scope**. This remains a hypothesis until the prospective cohort accumulates enough downstream observation time.

## #471 → #472 as process evidence

#471 and #472 share the same base SHA. #471 was closed unmerged after proposing Redis-backed ownership for GF-13/GF-27 while explicitly deferring GF-25/GF-26/GF-28. #472 instead merged a PostgreSQL-backed durable authority that treats the broader idempotency cluster as one architectural problem.

The observable fact is that the narrower/different design did **not** enter `main`; the broader root-cause package did. This is potentially important evidence of improved pre-merge correction quality. The reason for the redesign must not be attributed to the graph unless contemporaneous review/task evidence explicitly supports that causal claim.

## #465 → #473 as incomplete-closure evidence

#465 strongly repaired password signup and email verification semantics, but the later frozen baseline still identified GF-14: concurrent verification could consume the same authority before successor bootstrap authority was safely serialized. #473 repairs that concurrency property together with GF-22 and GF-23 under one single-use credential invariant.

This should currently be coded as:

- #465: strong local behavioral/security correction;
- GF-14 after #465: broader state-transition invariant remained incomplete;
- #473: later root-level concurrency closure.

Do **not** code this as "#465 introduced GF-14" without source history proving introduction.

## Preliminary interpretation

The strongest current evidence is that PR quality has improved in **architecture reasoning and closure discipline**, especially after #468. The post-#468 PRs increasingly define one invariant, derive scope from system relationships, prove the real failure mode, reconcile the graph, and preserve negative evidence.

What is **not** yet established:

- lower corrective-descendant rate;
- lower cascade depth;
- lower rework ratio;
- shorter time to closure;
- statistically significant improvement attributable to graph assistance.

The cohort is too recent and right-censored for those outcome claims.

## Methodological implication

For the prospective analysis, a single binary `pre/post #460` treatment variable is probably insufficient. Preserve #460 as the preregistered provisional boundary, but also code graph maturity as a time-varying treatment characteristic. At minimum distinguish:

- initial graph-assisted correction period (#460 onward);
- semantic-enforcement maturity (#468 onward);
- graph-integrated remediation with explicit finding closure (#469 onward).

Any final intervention refinement must be justified from contemporaneous implementation evidence, not from favorable outcome metrics.

## Next reproducible measurement

For every prospective production PR, capture the same fields before looking at downstream outcomes:

- requested/change scope;
- graph-predicted blast radius;
- actual implementation scope;
- invariant(s) named;
- proof selected;
- graph findings before;
- graph findings after;
- unrelated findings preserved;
- PR size / files / commits;
- review-discovered corrections before merge;
- merged vs superseded/abandoned;
- corrective descendants after fixed observation windows.

Then compare first-pass architectural completeness and corrective descendants at fixed 7-, 14-, 30-, and 60-day windows, with right-censoring explicitly represented.