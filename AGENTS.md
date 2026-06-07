# Ajenda-AI Agent Instructions

These instructions apply to AI agents, Codex sessions, connector-assisted edits, and local automation working in this repository.

## Operating doctrine

- Treat implementation files, tests, migrations, and runtime proof as the source of truth.
- Treat `PROJECT_SPEC.md`, README files, architecture notes, and product docs as contracts to verify against implementation, not as proof that behavior exists.
- Read the relevant implementation files completely before modifying them.
- Search for all affected call sites, tests, migrations, validators, and docs before changing a contract name or runtime behavior.
- Prefer complete, coherent fixes over narrow patches that only satisfy one failing test.
- Preserve tenant isolation, queue authority, lease ownership, fail-closed policy behavior, and evidence-backed runtime outcomes.

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
4. Add or update tests for new behavior, failure paths, tenant boundaries, and rollback/compensation logic.
5. Update docs only after implementation and tests establish the behavior.
6. Run the required validation gates listed below.

## Runtime authority checklist

When touching mission execution, workers, queues, leases, dispatch, recovery, tool execution, or evidence, verify:

- Work enters through an `ExecutionTask` and queue-backed runtime path.
- Worker claim/start/run requires lease ownership.
- Side-effecting work only runs from an eligible runtime state.
- DB and queue state cannot silently diverge without compensation or visible failure.
- Completion/failure emits the expected lineage, evidence, audit, and queue result.
- Retry behavior cannot duplicate external mutations.

## Ability and tool rollout checklist

Use this checklist for PRs that add or change a capability, adapter, `tool.invoke` action, provider, side-effect behavior, action schema, or evidence bridge.

- [ ] Registered action has a stable action name and provider.
- [ ] Action has a Pydantic input model or a documented no-input contract.
- [ ] Action returns `ActionResult` and emits at least one `EvidenceItem` when successful.
- [ ] Side-effect class is explicit and matches handler behavior.
- [ ] Side-effecting action requires `execution_constraints.side_effect_authorization`.
- [ ] Side-effecting action requires concrete capability and/or adapter authority.
- [ ] External writes/sends/publishes include idempotency review and retry-safety proof.
- [ ] Capability and adapter metadata remain declarative and do not register runtime handlers directly.
- [ ] Tenant scope is validated before reads, writes, and evidence persistence.
- [ ] Tests cover happy path, blocked unauthorized path, tenant mismatch, malformed input, and relevant failure/retry behavior.
- [ ] Migration/domain/Pydantic/schema parity is preserved when schemas or persisted contracts change.

## Required local gates

Run the narrowest targeted tests first, then the full gate before PR handoff when practical:

```bash
ruff check backend/ tests/ scripts/validation/
ruff format --check backend/ tests/ scripts/validation/
mypy backend/
python scripts/validation/contract_drift_check.py
python scripts/validation/migration_seed_contract_check.py
python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration"
```

When runtime, queue, lease, migration, or provider behavior changes, also run the relevant integration tests and migration round-trip:

```bash
python -m pytest tests/integration/ -m "integration" --timeout=60
alembic upgrade head
alembic downgrade base
alembic upgrade head
```

## PR handoff standard

Each PR summary should include:

- Implementation files changed.
- Code path traced.
- Authority, tenant, side-effect, evidence, and migration impact.
- Tests and validation commands run.
- Any skipped checks and the exact reason.
- Known follow-up work as issues, not hidden assumptions.
