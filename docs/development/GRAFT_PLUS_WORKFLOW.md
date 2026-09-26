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

## Relationship to other repository rules

- **Pride Protocol** supplies the discipline: read fully, search affected instances, plan, test,
  document, and review honestly.
- **UPG/LAP** establishes responsibility, authority, failure modes, invariants, and proof before
  implementation.
- **GRAFT+** joins those decisions to the dependency graph, coordinates the full build, selects and
  expands proof, and uses runtime artifacts to discover hidden blast radius.

Together they enable speed and ambiguity without replacing evidence with confidence.
