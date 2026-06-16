# Tool invoke completion failure hardening

## Design note

This change separates post-action completion failures from normal handler failures for side-effecting `tool.invoke` tasks.

`TaskDispatcher.execute()` already validates and executes runtime-authoritative tool actions through `ToolRuntimeAuthority`. The remaining risk was after a side-effecting action returned a completed result: if `WorkerRuntimeService.complete()` raised while persisting completion, lineage, or evidence, the dispatcher treated the exception as a normal handler failure and called `fail()`. That could mark a successfully mutated task as failed/retryable and create replay risk.

The dispatcher now classifies completed side-effecting `tool.invoke` results before falling back to normal failure handling. If completion fails after such a result, it calls a dedicated runtime service path that blocks the task, releases the worker lease, records audit evidence, and clears the queue processing claim without re-enqueueing the task.

Risk class: runtime-authoritative side-effect replay prevention.

## Backward compatibility

The change is additive to runtime behavior. Existing handler registration, task queue claiming, normal handler failure, non-side-effecting tool invocation, and terminal queue cleanup semantics remain unchanged.

Side-effecting `tool.invoke` completion failures now become blocked operator-review cases instead of normal failed/retryable cases.

## Validation impact

Required validation focuses on dispatcher classification and runtime service state ownership:

- side-effecting `tool.invoke` completion failure is blocked instead of failed normally
- handler execution remains single-shot
- normal handler exceptions still fail normally
- non-side-effecting `tool.invoke` completion failures keep existing fail behavior
- existing tool authority and evidence bridge tests continue to pass

## Rollback strategy

Rollback by removing the dispatcher completion-failure classification helper/path and the `WorkerRuntimeService.block_completion_failure()` method, then removing the matching unit tests. This restores the previous behavior where `_complete()` failures fall through to normal `_fail()` handling.
