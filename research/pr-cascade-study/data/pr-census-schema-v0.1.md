# PR Census Schema v0.1

**Status:** working extraction schema; revisable  
**Study:** 1DevTeam Architectural Scope & PR Cascade Study  
**Population snapshot target:** Ajenda pull-request history through PR #474  

## Purpose

Define the fields collected for the full Ajenda PR population before causal adjudication. This schema deliberately separates directly observable repository facts, machine-generated candidate signals, and human/research adjudication. Automated signals are discovery aids only and must not become causal findings without evidence review under the study protocol.

## Layer 1 — repository-observable census fields

These fields are populated directly from GitHub PR metadata or deterministic transformations of that metadata.

| Field | Type | Meaning |
|---|---|---|
| `pr_number` | integer | Repository PR number. |
| `title` | string | PR title at extraction time. |
| `state` | enum | `open` / `closed`. |
| `merged` | boolean | Whether GitHub reports the PR as merged. |
| `created_at` | datetime | GitHub creation timestamp. |
| `updated_at` | datetime | GitHub update timestamp. |
| `closed_at` | datetime/null | Close timestamp. |
| `merged_at` | datetime/null | Merge timestamp. |
| `author` | string/null | GitHub login. |
| `base_ref` | string | Target branch. |
| `head_ref` | string | Source branch. |
| `base_sha` | SHA/null | Base commit recorded by the PR. |
| `head_sha` | SHA/null | Head commit recorded by the PR. |
| `merge_sha` | SHA/null | Merge commit SHA when present. |
| `commits` | integer/null | Number of PR commits. |
| `changed_files` | integer/null | GitHub changed-file count. |
| `additions` | integer/null | GitHub additions count. |
| `deletions` | integer/null | GitHub deletions count. |
| `body_sha256` | hex | SHA-256 of the exact PR body returned at extraction. |
| `referenced_prs` | list[int] | Conservatively parsed explicit `PR #N` / `pull request #N` references. |
| `snapshot_max_pr` | integer | Frozen upper PR boundary for the extraction run. |
| `extracted_at_utc` | datetime | Extraction timestamp. |

## Layer 1b — deterministic text/process signals

These are heuristic flags. They are not classifications.

- `signal_fix_title`
- `signal_hardening_title`
- `signal_revert`
- `signal_followup`
- `signal_supersession`
- `signal_root_cause_language`
- `signal_scope_or_non_goals`
- `signal_invariant_language`
- `signal_validation_or_proof`
- `signal_graph_language`
- `signal_review_feedback`
- `signal_failure_language`
- `signal_dependabot`
- `signal_research_only`

Each flag is reproducible from title/body text and exists only to prioritize later review.

## Population-role field

`population_role_raw` is a machine-assigned routing label, not a study outcome. Initial values:

- `product_candidate`
- `dependency_maintenance_candidate`
- `research_candidate`
- `process_or_docs_candidate`
- `unknown`

Final inclusion/exclusion remains adjudicated under the protocol. In particular, research PR #466 and research instrumentation such as #474 are excluded from the measured product-development population, while closed-unmerged design attempts may still be retained as process evidence.

## Layer 2 — semantic/change variables

These fields are **not** populated by simple keyword inference. They require source-backed adjudication or a separately documented high-confidence extraction rule.

### Change / defect mechanism

`change_mechanism` values may include:

- `introduced_defect`
- `incomplete_original_change`
- `regression`
- `exposed_latent_defect`
- `required_hardening`
- `planned_extension`
- `requirements_change`
- `architecture_instrumentation`
- `correction_of_correction`
- `revert`
- `supersession`
- `unrelated`
- `uncertain`

### Semantic scope dimensions

Boolean/multiselect fields should capture at minimum:

- authority / permissions
- identity / principal binding
- state ownership
- state transition / ordering
- concurrency / single-use
- idempotency
- tenancy / RLS
- persistence / transaction boundary
- external side effects / egress
- contract / payload shape
- runtime scheduling / leases
- configuration / fail-fast
- recovery / compensation
- frontend/backend contract
- proof obligation

### Boundary variables

- `boundaries_changed`
- `boundaries_depended_on`
- `graph_selected_boundaries`
- `boundaries_explicitly_proven`
- `later_corrective_boundaries`

### Invariant variables

- `invariant_named`
- `invariant_id_or_text`
- `local_contract_closed`
- `governing_invariant_closed`
- `target_findings_before`
- `target_findings_after`
- `unrelated_findings_preserved`

### Repair mechanism

- `repair_mechanism_class`
- `authoritative_control_point`
- `shared_authority_reused`
- `new_parallel_coordination_added`
- `duplicate_control_path_removed`

### Proof topology

Separate flags/records for:

- unit
- contract
- integration
- real database
- real concurrency/contention
- provider/runtime
- fail-closed/adversarial
- migration
- graph semantic closure
- negative-evidence preservation

### Process interception

- `review_discovered_material_defect`
- `material_revisions_before_merge`
- `superseded_before_merge`
- `closed_unmerged_process_evidence`
- `premerge_severity_intercepted`

### Graph maturity vector

Record graph capability actually available/used for each PR rather than only a binary date:

- static dependency visibility
- transitive blast radius
- graph-derived impacted tests
- proof selection
- semantic boundary modeling
- invariant modeling
- state/concurrency modeling
- semantic finding generation
- negative-evidence ratchet
- remediation closure reconciliation
- architecture decision manifest

## Layer 3 — causal PR-to-PR edges

Causal relationships live in a separate edge table. Candidate extraction never assigns a final grade automatically.

Required fields:

- `source_pr`
- `target_pr`
- `candidate_reason`
- `explicit_reference`
- `evidence_excerpt_or_locator`
- `relationship_class`
- `evidence_grade`
- `adjudication_status`
- `adjudication_notes`
- `semantic_dimensions`
- `same_invariant_cluster`
- `severity_source`
- `severity_target`
- `boundary_movement`

`adjudication_status` begins as `unadjudicated` even for seemingly obvious references; direct evidence can then be upgraded to Grade A during review.

## Derived measures — compute only after component fields are validated

Candidate constructs currently under study:

- Reasoning-Scope Coverage (RSC)
- Invariant Closure Ratio (ICR)
- Residual Visibility Rate (RVR)
- Repair Cluster Coherence (RCC)
- Proof Layer Coverage (PLC)
- Pre-Merge Interception Rate (PMI)
- Corrective Propagation Rate (CPR)
- Semantic Fragmentation Depth (SFD)
- Symptom-to-Invariant Compression (SIC)
- Architecture Adjudication Debt (AAD)

No composite `PR quality score` is authorized by this schema. These constructs must be validated separately before inferential use.
