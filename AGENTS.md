# Ajenda-AI Agent Instructions

These instructions apply to AI agents, Codex sessions, connector-assisted edits, and local automation working in this repository.

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
python scripts/validation/migration_seed_contract_check.py
python scripts/validation/ability_rollout_contract_check.py
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
