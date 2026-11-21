# GRAFT+ Build Workflow

## Terminology boundary

- **GRAFT1st** designs a new program or a new bounded system before its first implementation line.
  Its artifacts are prospective architecture, contracts, dependency decisions, and proof plans;
  they are not observed implementation evidence.
- **GRAFT+** analyzes, changes, and verifies an existing program. It starts from implementation,
  tests, migrations, persisted state, and runtime artifacts, then uses the dependency graph to
  expose blast radius and proof obligations.

The names are not interchangeable. A GRAFT1st design may later be reconciled to its growing
implementation by GRAFT+, but that reconciliation remains GRAFT+ work.

GRAFT+ is Ajenda AI's established workflow for fast, ambitious, evidence-backed changes. It uses
the repository dependency graph to guide a build across its real contracts and blast radius. It is
not a policy of choosing the smallest change; it is a policy of knowing what a change touches,
preserving the system's invariants, and proving the resulting behavior.

Implementation, tests, migrations, persisted state, queue state, and runtime artifacts are the
source of truth. Documentation, plans, graph metadata, and generated reports are contracts and
guides that must be reconciled against that truth.

## Workflow

### 1. Establish the mission

- State the intended outcome and the artifact or behavior that will prove it.
- Identify the implementation entry point and current authority owner.
- Locate the relevant tests, migrations, validators, runtime state, and documentation contracts.
- Record unknowns as possible pitfalls; do not promote assumptions into implementation authority.

### 2. Complete UPG/LAP

Before changing a non-trivial layer, runtime, tool, network, persistence, security, evidence, or
workflow path, document:

1. **Responsibility** — accepted inputs, decisions or transformations, and outputs or effects.
2. **Dependencies** — upstream and downstream code, routes, repositories, schemas, queues,
   services, external systems, configuration, tests, and docs.
3. **Possible pitfalls** — malformed or missing input, stale state, duplicates, tenant mismatch,
   missing authority, failed dependency, partial success, retry, concurrency, incorrect output, and
   failures that would not be visible in the primary artifact.
4. **Invariants** — properties that must remain true across success, failure, and retry.
5. **Proof** — tests, validation, migrations, runtime evidence, artifact inspection, and explicit
   non-goals that prove each invariant.

If authority or source of truth cannot be verified, the affected behavior fails closed until it is
clarified. Scope may remain ambitious; unsupported authority may not be invented.

### 3. Build and inspect the graph

Build the canonical graph and analyze the actual changed files, including working-tree changes when
the commit range does not yet contain them.

```bash
python scripts/validation/build_dependency_graph.py
python scripts/validation/graph_impact_analysis.py \
  --changed-file path/to/changed_file.py \
  --json --output /tmp/graft-impact.json
python scripts/validation/graph_proof_selection.py \
  --impact-report /tmp/graft-impact.json \
  --json --output /tmp/graft-proof.json
```

Review changed nodes, upstream consumers, downstream dependencies, semantic nodes, risk domains,
relevant invariants, impacted tests, and unmapped files. A large blast radius is not an automatic
reason to retreat. It is a requirement to coordinate the build and proof across that radius.

Classify every unmapped file. An implementation, schema, migration, deployment, or validation file
that should participate in runtime impact analysis must be mapped or explicitly escalated as a
graph defect. Documentation-only and agent-governance files may remain outside the implementation
graph when manual review verifies their links and claims against source and proof; record that
classification instead of inventing runtime dependency edges for prose.

The graph is also under test. Missing mappings, incorrect edges, or proof selections contradicted
by source or runtime evidence are GRAFT+ defects and must be recorded or repaired.

### 4. Implement the coherent change

- Modify the owning layer and every affected contract needed for coherent behavior.
- Preserve tenant isolation, queue authority, lease ownership, side-effect authorization,
  idempotency, evidence lineage, and fail-closed behavior.
- Cover happy paths, denied or malformed paths, tenant mismatch, retry/concurrency, and relevant
  compensation behavior.
- Do not add a parallel execution path to avoid an existing authority boundary.

### 5. Prove from narrow to broad

Run targeted tests first, then the graph-selected and repository gates. For runtime, queue, lease,
provider, migration, or evidence work, run the applicable integration and live proof.

```bash
ruff check backend/ tests/ scripts/validation/
ruff format --check backend/ tests/ scripts/validation/
mypy backend/
python scripts/validation/contract_drift_check.py
python scripts/validation/runtime_authority_inventory_check.py
python scripts/validation/migration_seed_contract_check.py
python scripts/validation/ability_rollout_contract_check.py
python scripts/validation/graft_plus_gate.py --base-ref origin/main --head-ref HEAD
python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration"
```

For uncommitted work, the range-based GRAFT+ gate alone reports no changed files. Pair it with
explicit `--changed-file` impact analysis so the working-tree blast radius is not hidden.

### 6. Examine runtime artifacts adversarially

Do not stop at a completed task or green test. Inspect the mission lifecycle, queue and lease state,
handler output, typed artifact, evidence, lineage, audit trail, acceptance result, and assembled
deliverable. Ask:

- Does completion describe runtime delivery, business success, or both?
- Could fixture, simulated, stale, or inferred data appear real?
- Did safety and network controls survive into user-visible evidence?
- Can DB and queue visibility race or diverge?
- Can retry duplicate an external effect?
- What failed outside the mission artifact, such as a shared queue or worker loop?

Unexpected artifacts feed back into UPG/LAP and may expand the implementation. This feedback loop
is a core GRAFT+ advantage, not a failed plan.

### 7. Reconcile and hand off

- Update docs after code, tests, and runtime proof agree.
- Report changed implementation files and the traced code path.
- Report authority, tenant, side-effect, evidence, queue, and migration impacts.
- Include exact tests and validators run, skipped checks and reasons, runtime artifact locations,
  graph metrics, and known follow-up work.
- Never claim synthetic completion. Completion requires the artifact, diff, test, runtime proof, or
  explicitly documented non-goal.

### 8. Recurring controls

The weekly coherence workflow runs the admission-coverage and drift sentinels. The canonical
graph freshness check fails when generated metadata no longer matches the repository. For a
tenant-scoped runtime proof export, run:

```bash
python scripts/validation/graft_runtime_reconciliation.py \
  path/to/runtime-reconciliation-snapshot.json \
  --output artifacts/runtime-reconciliation-report.json
```

The snapshot validator compares graph expectation → selected nodes → materialized tasks → queue
execution → evidence → final deliverable. It does not synthesize missing stages. Any unexplained
contradiction remains unresolved and blocks the report until repaired or explicitly explained.

#### Locate information-flow differences

Save the JSON returned by the following tenant-authorized GETs for a single
mission. Use the same authenticated session and capture the records together.

- `/v1/missions/{id}/runtime-reconciliation-export` supplies the sealed GRAFT export.
- `/v1/missions/{id}` supplies the saved semantic snapshot when available.
- `/v1/missions/{id}/deliverable` supplies the actual user-facing artifact readback.

The flow report runs offline. Give it the export alone for a map of saved plan nodes,
task bindings, queue admission, lease IDs, worker receipts, output shapes, evidence
references and mission acceptance. Add a reviewed reference to locate the first
supported mismatch:

```bash
python scripts/validation/mission_information_flow.py runtime-export.json \
  --mission-record mission.json \
  --deliverable deliverable.json \
  --expectations reviewed-expectations.json \
  --instruction-file original-request.txt > information-flow.json
```

The mission record, deliverable, reference and Shadow input are optional. The
instruction file must contain the saved request byte for byte, including
its whitespace. Before running Shadow, the tool checks its SHA-256 against the
committed confirmation receipt or the same mission's validated semantic snapshot.
The report identifies which source supplied the fingerprint. Shadow replays the local interpreter
with its current settings. It cannot stand in for a historical event or recover
missing historical context.

`reviewed-expectations.json` can cover the outcomes, market scope, action set, exact
top-level input fields for named graph nodes, and expected deliverable artifact keys.
Include only fields the operator or a reviewed proof establishes. For example:

```json
{
  "schema_version": 1,
  "instruction_sha256": "sha256:<64 hex digits from the confirmation receipt>",
  "requested_outcomes": ["research_prospects", "synthesize_research_report"],
  "target_scope": [{"type": "company", "industry": "software development", "location": "Austin"}],
  "planned_actions": ["web.research", "research.verify_public_candidates", "research.synthesize_report"],
  "planned_inputs": {
    "ability-web-research": {"query": "software development companies in Austin", "limit": 3}
  },
  "required_artifacts": ["research_report"]
}
```

Use `--baseline prior-passing-export.json` in place of `--expectations` to compare
recorded outcomes, planned action sets and search queries from a completed mission
with satisfied acceptance. The baseline must match the observed tenant and
confirmation fingerprint. Provider results and transient runtime identifiers do
not participate in baseline comparison. Supply a reviewed reference and the
mission's deliverable for artifact-presence checks.

Read `first_supported_mismatch` alongside `earlier_unobserved_checks` and GRAFT's
`first_recorded_divergence`. The first reports a specific difference backed by the
supplied reference. The others show uncertainty earlier in the path and the
structural failure recorded at runtime. The report exits successfully when it can
render the diagnostic, including for failed missions. Input validation failures
exit with status 2. Export digests verify content consistency. Source authenticity
still depends on obtaining the export from the authorized Ajenda endpoint. Query
and scope values are summarized by default. Use `--include-values` only in a local
report intended to contain the reviewed field values.

### 9. Authority promotion boundary

GRAFT+ cannot promote itself. Any future self-management capability requires an independently
owned and reviewed capability manifest, bounded resources/actions, approval/autonomy policy,
idempotency and rollback proof, audit/evidence/read-back, a kill switch, and recurring review.

## Relationship to other repository rules

- **Pride Protocol** supplies the discipline: read fully, search affected instances, plan, test,
  document, and review honestly.
- **UPG/LAP** establishes responsibility, authority, failure modes, invariants, and proof before
  implementation.
- **GRAFT+** joins those decisions to the dependency graph, coordinates the full build, selects and
  expands proof, and uses runtime artifacts to discover hidden blast radius.

Together they enable speed and ambiguity without replacing evidence with confidence.
