# Ajenda-AI Agent Instructions

These instructions apply to AI agents, Codex sessions, connector-assisted edits, and local automation working in this repository.

## Mandatory context reset for Codex — closed PR #634

**PR #634 is CLOSED, UNMERGED and SUPERSEDED.** No task, worktree, branch, pending diff, code review or PR assumption originating from #634 is an active implementation instruction. The active work is **issue #635**, with the sole implementation base `origin/rebuild/public-research-evidence-first` (main-derived). The old commit `5fbc84ab5b46f7cc6358f842f55a77072efedffb` and archive branch are READ-ONLY salvage references.

**DO NOT rebase PR #634 or its original feature branch onto the recovery branch; DO NOT merge, reset, cherry-pick or port it wholesale.** A rebase of the superseded history would reincorporate unadjudicated defects. Only verified hunks from its archive may later be manually reintroduced with tests.

Before touching source: `git fetch origin`; inspect `git branch --show-current`, `git status --short`, `git rev-parse HEAD`, and `git rev-parse origin/rebuild/public-research-evidence-first`. On an old PR branch or dirty worktree, **stop and preserve changes**—do not checkout over, force reset, stash/drop, or rewrite user work automatically. Use a clean worktree at the exact recovery branch, fast-forwarding it as appropriate; verify the branch and base in writing. If the active Codex session's previous instructions refer to #634 as an open PR, those assumptions are stale: replace them with this file and `07-CODEX-EXECUTION-BRIEF.md`. The executor must affirm the correct branch before further edits.

## Public research recovery branch — handoff entry point

When working on **issue #635** or branch `rebuild/public-research-evidence-first`, first read `docs/audits/public-research-rebuild/07-CODEX-EXECUTION-BRIEF.md` **in full**. It is the **file/function-level implementation handoff** for Codex, with exact source findings, owned corrections, controlled simulation scenarios, existing-system consumers and evidence gates.

Then follow its ordered source reading list (original investigation O01–O10, causal traces T01–T06, ownership C01–C12 and simulation). Perform the UPG/LAP and GRAFT+ gates below before editing. **Do not** merge or wholesale cherry-pick archived draft PR #634. The first code changes on this branch already include a reviewer-owned `page_read.py` HTTP-status fix whose tests have **not yet been executed**.

This handoff is branch/issue scoped. It does not supersede the repository-wide safety, runtime authority, or test requirements below.

## Operating doctrine

- Treat implementation files, tests, migrations, and runtime proof as the source of truth.
- Treat `PROJECT_SPEC.md`, README files, architecture notes, and product docs as contracts to verify against implementation, not as proof that behavior exists.
- For code-aligned system maps and Mermaid flowcharts, use `docs/architecture/SYSTEM_ARCHITECTURE.md` before trusting dated assessments or remediation snapshots.
- Read relevant implementation files completely before modifying them.
- Search affected call sites, tests, migrations, validators, and docs before changing contract names or runtime behavior.
- Prefer complete, coherent fixes over narrow patches that only satisfy one failing test.
- Preserve tenant isolation, queue authority, lease ownership, fail-closed policy behavior, and evidence-backed runtime outcomes.

## UPG Layer — Universal Prompting Gate

Before any non-trivial layer, runtime, tool, networking, persistence, security, or workflow change, complete the UPG gate before implementation.

UPG prevents assumption-driven implementation by requiring the agent to identify the change responsibility, source of truth, dependencies, possible pitfalls, invariants, proof, and system-wide impact before editing.

UPG rules:

- Pride Protocol is strictly enforced: read relevant files completely, understand full context, search affected instances, plan before editing, test before claiming completion, document decisions, and review honestly.
- No assumption may be used as implementation authority. Assumptions belong only in Possible Pitfalls. Every decision must be backed by verified evidence from source files, tests, migrations, runtime output, repository history, or direct user clarification.
- Every change must identify its source of truth before implementation. If ownership or source of truth is unclear, implementation is blocked until clarified.
- Any unclear authority, ownership, state, persistence, retry behavior, tenant scope, or external effect must fail closed or be explicitly deferred.
- Before coding, consider edge cases and the system-wide impact of each addition. Identify what can fail, what can be affected, what must remain true, and how each claim will be proven.
- No synthetic completion: work is not complete because it is described. Work is complete only when the artifact, diff, test, citation, runtime proof, or explicitly documented non-goal exists.

### LAP — Layer Acceptance Protocol

For layer-level changes, tool stacks, provider changes, networking/security changes, runtime paths, or evidence/persistence changes, complete LAP before coding:

1. Responsibility — what this layer/change accepts, transforms/decides, and outputs/changes.
2. Dependencies — upstream/downstream files, routes, repositories, migrations, queues, services, configs, external systems, and tests.
3. Possible Pitfalls — wrong input, missing input, stale state, duplicate action, wrong tenant/user, wrong permissions, failed dependency, partial success, retry behavior, race/concurrency, bad output, and data not observable afterward.
4. Invariants — what must always remain true after the change.
5. Proof — tests, validation scripts, migration checks, integration proof, runtime evidence, or documented non-goals proving each invariant.

Do not implement a layer-level change until UPG/LAP is complete. If the review finds insufficient evidence, ask for clarification or narrow the scope.

## GRAFT+ workflow

GRAFT1st and GRAFT+ are distinct methods. **GRAFT1st** designs a new program or bounded system
before its first implementation line. **GRAFT+** analyzes and guides changes to an existing
program. Do not use either name as a generic synonym for the other.

GRAFT+ is the established repository workflow for non-trivial changes to this existing repository.
After UPG/LAP and before modifying implementation, use the canonical dependency graph to map the proposed or actual changed files,
their upstream consumers, downstream dependencies, semantic nodes, risk domains, invariants, and
proof obligations. For uncommitted work, run explicit changed-file impact analysis; a Git ref range
that excludes the working tree is not sufficient blast-radius evidence.

GRAFT+ does not require the smallest or most conservative patch. It may guide an ambitious or
exploratory build when the source-of-truth ownership and invariants are known. Implement the
complete coherent change supported by the graph, then run targeted, graph-selected, full, and live
runtime proof in proportion to the blast radius. Inspect runtime artifacts adversarially for hidden
failures outside the primary artifact, including shared queue state, DB/queue visibility races,
fixture or simulated truth leakage, missing safety provenance, and completion/business-outcome
conflation.

Treat graph gaps and runtime contradictions as findings. Feed them back into UPG/LAP, expand the
build or proof as needed, and update docs only after implementation and evidence agree. The
canonical procedure is `docs/development/GRAFT_PLUS_WORKFLOW.md`.

## Hard boundaries

Do not:

- Bypass `TaskDispatcher` or `WorkerRuntimeService` for runtime work.
- Let declarative capability or adapter records directly execute work.
- Add side-effecting actions without explicit side-effect classification, authorization, idempotency review, and evidence output.
- Add route mutations that skip tenant validation, policy gates, audit events, or repository/service boundaries.
- Use docs, README text, comments, or PR descriptions as implementation evidence without tracing the code path.
- Commit secrets, credentials, tokens, local `.env` values, or generated private artifacts.

## Code-first workflow

For every non-trivial change:

1. Identify the implementation entry point.
2. Trace the call chain to repositories, migrations, runtime state changes, lineage, evidence, audit, and queue effects.
3. Identify existing tests that prove the behavior.
4. Add or update tests for new behavior, failure paths, tenant boundaries, and rollback or compensation logic.
5. Update docs only after implementation and tests establish the behavior.
6. Run the required validation gates listed below.

## Runtime authority checklist

When touching mission execution, workers, queues, leases, dispatch, recovery, tool execution, or evidence, verify:

- Work enters through an `ExecutionTask` and queue-backed runtime path.
- Worker claim, start, and run requires lease ownership.
- Side-effecting work only runs from an eligible runtime state.
- DB and queue state cannot silently diverge without compensation or visible failure.
- Completion or failure emits the expected lineage, evidence, audit, and queue result.
- Retry behavior cannot duplicate external mutations.

## Ability and tool rollout checklist

Use this checklist for PRs that add or change a capability, adapter, `tool.invoke` action, provider, side-effect behavior, action schema, or evidence bridge.

- [ ] Registered action has a stable action name and provider.
- [ ] Action has a Pydantic input model or a documented no-input contract.
- [ ] Action returns `ActionResult` and emits at least one `EvidenceItem` when successful.
- [ ] Side-effect class is explicit and matches handler behavior.
- [ ] Side-effecting action requires `execution_constraints.side_effect_authorization`.
- [ ] Side-effecting action requires concrete capability and/or adapter authority.
- [ ] External writes, sends, or publishes include idempotency review and retry-safety proof.
- [ ] Capability and adapter metadata remain declarative and do not register runtime handlers directly.
- [ ] Tenant scope is validated before reads, writes, and evidence persistence.
- [ ] Tests cover happy path, blocked unauthorized path, tenant mismatch, malformed input, and relevant failure or retry behavior.
- [ ] Migration, domain, Pydantic, and schema parity is preserved when schemas or persisted contracts change.

## Required local gates

Run the narrowest targeted tests first, then the full gate before PR handoff when practical:

```bash
ruff check backend/ tests/ scripts/validation/
ruff format --check backend/ tests/ scripts/validation/
mypy backend/
python scripts/validation/contract_drift_check.py
python scripts/validation/runtime_authority_inventory_check.py
python scripts/validation/migration_seed_contract_check.py
python scripts/validation/ability_rollout_contract_check.py
python scripts/validation/graft_plus_graft1st_reconciliation_check.py
python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration"
```

When runtime, queue, lease, migration, or provider behavior changes, also run relevant integration tests and migration round-trip checks.

## PR handoff standard

Each PR summary should include:

- Implementation files changed.
- Code path traced.
- UPG/LAP review completed for non-trivial layer/runtime/tool/networking/security/persistence changes.
- Authority, tenant, side-effect, evidence, and migration impact.
- Tests and validation commands run.
- Any skipped checks and the exact reason.
- Known follow-up work as issues, not hidden assumptions.
