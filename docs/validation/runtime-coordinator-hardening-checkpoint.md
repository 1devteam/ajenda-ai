# Runtime Coordinator Hardening Checkpoint

## Purpose

This checkpoint records runtime coordinator hardening completed after the deployment hardening checkpoint.

The goal of this wave was to make runtime execution contracts explicit, tested, and resistant to DB/queue split-brain failures.

This document is evidence only. It does not replace current test output, live runtime proof output, or release-gate validation.

## Completed scope

Checkpoint head:

```text
0b1908075666f80879189b8bfd2940cffd0752c8
```

Completed pull requests:

| PR | Area | Result |
|---|---|---|
| `#91` | Worker runtime transaction-boundary contract | merged |
| `#92` | ExecutionCoordinator queue enqueue rollback contract | merged |
| `#93` | ExecutionCoordinator runtime-governor non-execution contract | merged |
| `#94` | ExecutionCoordinator policy-review-required contract | merged |
| `#95` | Dead-letter queue movement rollback fix and regression test | merged |
| `#96` | Dead-letter success-path contract | merged |

## Runtime contracts now guarded

### WorkerRuntimeService transaction boundary

`WorkerRuntimeService` owns the session commit boundary for runtime state mutations used by worker loop and dispatcher flows.

Primary test:

```text
tests/unit/services/test_worker_runtime_service_transaction_contract.py
```

### Queue admission rollback

`ExecutionCoordinator.queue_task()` transitions a task to `queued` before enqueueing.

If queue enqueue fails, the task must be restored to its previous state before the error is raised.

Primary test:

```text
tests/unit/services/test_execution_coordinator.py
```

### Runtime governor non-execution path

If `RuntimeGovernor` blocks execution, `ExecutionCoordinator.queue_task()` must not enqueue the task.

Primary test:

```text
tests/unit/services/test_execution_coordinator_policy_denial_contract.py
```

### Policy review required

If `PolicyGuardian` requires human review, `ExecutionCoordinator.queue_task()` must transition the task to `pending_review` instead of enqueueing it.

Primary test:

```text
tests/unit/services/test_execution_coordinator_policy_review_contract.py
```

### Dead-letter queue rollback

`ExecutionCoordinator.mark_dead_letter()` transitions the task to `dead_lettered` before moving it into the queue dead-letter structure.

A real defect was found in this checkpoint: if queue dead-letter movement failed, task state remained `dead_lettered` even though queue movement failed.

The fix restores the previous task state before raising the queue movement error.

Primary files:

```text
backend/services/execution_coordinator.py
tests/unit/services/test_execution_coordinator.py
```

### Dead-letter success path

Successful dead-letter movement now has explicit contract coverage.

Primary test:

```text
tests/unit/services/test_execution_coordinator.py
```

## Split-brain rule

The runtime coordinator must not leave database state ahead of queue state.

Required behavior:

```text
If queue mutation fails, restore the previous DB task state before raising.
```

This protects queue-backed execution authority.

## Validation evidence

Checkpoint validation completed with:

```text
pytest -q tests/unit/services/test_execution_coordinator.py \
  tests/unit/services/test_execution_coordinator_policy_denial_contract.py \
  tests/unit/services/test_execution_coordinator_policy_review_contract.py \
  tests/unit/services/test_worker_runtime_service_transaction_contract.py

ruff check backend/ tests/
ruff format --check backend/ tests/
```

Observed result:

```text
All checks passed!
274 files already formatted
```

A broader unit services/workers/runtime sweep also passed:

```text
pytest -q tests/unit/services/ tests/unit/workers/ tests/unit/runtime/
```

Contract runtime and queue sweep was also reported as passing after this wave:

```text
pytest -q tests/contract/runtime/ tests/contract/queue/
```

## Codex review handling

Codex feedback was inspected and addressed during this wave.

Accepted findings included:

- Dedent method source before AST parsing.
- Account for postponed string annotations.
- Prove queue rollback happens inside the rejection branch before raising.
- Distinguish lineage and audit appends.
- Use valid state-machine source states in queue admission tests.
- Mock governance repository assertions in dead-letter rollback tests.

## Release-gate interpretation

This checkpoint means the runtime coordinator unit contract layer is green.

It does not mean the entire runtime is fully hardened.

Before release-critical promotion, still run:

```text
pytest -q tests/integration/runtime/
pytest -q tests/contract/runtime/ tests/contract/queue/
./deploy/scripts/live-runtime-proof.sh
```

## Maintenance rules

When `ExecutionCoordinator` queue, policy, runtime governor, or dead-letter behavior changes, update or extend the coordinator contract tests.

When `WorkerRuntimeService` changes transaction-boundary behavior, update or extend the transaction-boundary contract tests.

Do not document a runtime responsibility here unless a test, integration proof, or live proof validates it.

Do not treat this checkpoint as a substitute for current validation output.
