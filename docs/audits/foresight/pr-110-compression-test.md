# PR #110 Compression Test

Source PR: #110 `fix(runtime): reconcile queue payloads during expired lease recovery`

Purpose of this file: test the combined PR-compression format on a PR that took multiple iterations before mergeability.

## Short Verdict

PR #110 is a strong compression candidate. It started as test-only proof, then exposed that the runtime recovery design itself was incomplete. The clean deliverable is not the full historical path. The clean deliverable is the queue-authoritative recovery contract plus the tests that prove duplicate, missing, and single-payload recovery behavior.

## Combined Compression Table

| PR | Keep / Final Value | Finding / Issue | Cause of Problem | Why It Existed / Wrong Assumption | Do Not Repeat | How It Could Have Been Avoided | Fix | System-Wide Effect | Test / Proof to Preserve | Clean Rebuild Action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| #110 | Queue-authoritative expired lease recovery | Test expected one pending payload after recovery, but old `release_lease()` produced duplicates | `RuntimeMaintainer.recover_expired_leases()` used `queue.release_lease()`, which re-pushed the processing payload without deduping existing pending entries | Assumed release/requeue was enough recovery semantics | Do not use `release_lease()` as recovery reconciliation | Define the recovery contract before writing corruption tests: recovery must converge queue evidence, not blindly requeue | Add explicit `QueueAdapter.recover_task_for_retry()` and update `RuntimeMaintainer` to call it for retryable expired work | Recovery now converges duplicate queue payloads instead of increasing duplication | `tests/integration/runtime/test_runtime_recovery_queue_corruption_real.py` | Add queue recovery contract first, then implement Redis/Local parity, then update runtime maintainer |
| #110 | Queue adapter contract stays constructible | Abstract method was added before implementations existed | `recover_task_for_retry` was declared abstract in `QueueAdapter` without adding it to `LocalQueueAdapter` and `RedisQueueAdapter` in the same complete change | Assumed adding interface first was safe without checking all concrete implementations | Never add an abstract method without updating every implementation in the same commit | Search every `QueueAdapter` subclass before changing the interface | Implement `recover_task_for_retry()` in both Redis and Local adapters | Runtime startup and tests can still instantiate queue adapters | Unit/contract tests that instantiate queue adapters | Change interface and all implementations together |
| #110 | Runtime module remains executable | Runtime maintainer was temporarily replaced with literal placeholder text | `backend/services/runtime_maintainer.py` contained `...TRUNCATED FOR BREVITY...`, making it invalid Python | Assumed shortened/generated patch text was acceptable in repo code | Never commit placeholder/truncated code | Fetch/read full file before patching and run import/lint immediately after editing | Restore complete valid Python implementation | Worker startup, runtime recovery, and integration tests can import `RuntimeMaintainer` | Ruff/import checks and integration runtime tests | Always patch from full-file context, never from abbreviated snippets |
| #110 | Redis recovery is atomic | First Redis reconciliation approach snapshot lists and rewrote them outside an atomic script | `LRANGE` + delete/re-push allowed concurrent enqueue/claim traffic to be overwritten | Assumed single-threaded recovery against tenant queue | Do not rewrite Redis queue lists non-atomically during live recovery | Consider concurrent workers/enqueues before choosing Redis operations | Move reconciliation into a single Lua `EVAL` script | Prevents unrelated tenant queue entries from being lost during recovery | Redis adapter tests and real recovery corruption integration tests | Implement Redis reconciliation atomically from the start |
| #110 | Redis recovery avoids high-cardinality data-loss path | Lua script used `unpack(...)` to rewrite whole lists | Redis Lua `unpack` has argument limits; script errors after `DEL` could leave lists emptied | Assumed atomic script means automatically safe even with large lists | Do not use bulk `unpack` list rewrites after destructive operations | Account for Redis Lua limits and failure order before script design | Iterate and `RPUSH` entries one-by-one inside the script | Avoids argument-limit failures dropping queue data | Redis recovery corruption tests; future large-queue test would strengthen this | Use looped list rebuilds, not `unpack`, in Redis Lua queue repair |
| #110 | Unsupported task states no longer create infinite stale-lease loops | Lease expiration moved inside `RUNNING`/`CLAIMED` branches only | Expired leases tied to queued/failed/cancelled/terminal tasks were left active and re-selected forever | Assumed only recoverable task states matter during lease cleanup | Do not skip lease cleanup just because task recovery is unsupported | Preserve the invariant that stale ownership must be expired even if task is not requeued | Add unsupported-state branch: expire lease, commit, and continue | Prevents maintainer from repeatedly rediscovering the same stale ownership | Runtime maintainer tests around terminal/unsupported task states | Separate lease cleanup from task recovery decisions |
| #110 | Runtime maintainer file remains syntactically clean through conflict resolution | Unresolved merge markers were left in `runtime_maintainer.py` | Conflict markers made the module invalid Python | Assumed merge/rebase result was clean without reading file after conflict | Never leave conflict markers; never trust a conflict resolution without running syntax/lint | Search for `<<<<<<<`, `=======`, `>>>>>>>` after resolving conflicts | Remove markers and restore one coherent implementation | Worker/runtime imports no longer fail at startup | Ruff/import checks | Add conflict-marker grep to cleanup checklist for large PRs |
| #110 | Lint gate remains green | New integration test had unused import | `from sqlalchemy import select` was added but not used | Assumed tests would be the first blocker, but lint runs first | Do not leave unused imports in test scaffolding | Run `ruff check backend/ tests/` before review | Remove unused import | CI gets to behavior tests instead of failing on hygiene | Ruff check | Run lint before calling branch ready |

## Clean Deliverable From This PR

The clean build should not replay the fifteen-commit path. It should produce this directly:

1. Define `QueueAdapter.recover_task_for_retry()` as the recovery-specific queue contract.
2. Implement LocalQueueAdapter parity.
3. Implement Redis recovery with one atomic Lua script.
4. Make the Redis Lua script avoid `unpack(...)` and rebuild lists safely.
5. Update `RuntimeMaintainer.recover_expired_leases()` so queue reconciliation succeeds before DB task/lease mutation.
6. Preserve fail-closed behavior when no processing or pending payload exists.
7. Ensure expired leases for unsupported/terminal task states are expired without requeueing task work.
8. Add integration proof for duplicate pending payloads, missing queue payloads, and single-payload convergence.
9. Run lint/type/tests before review.

## Clean Rebuild Order

1. Read `QueueAdapter`, `LocalQueueAdapter`, `RedisQueueAdapter`, and `RuntimeMaintainer` completely.
2. Add the recovery queue contract and all concrete implementations together.
3. Implement Redis atomic reconciliation.
4. Wire `RuntimeMaintainer` to use recovery reconciliation before DB mutation.
5. Add focused integration tests.
6. Add/keep lint and import validation.
7. Run targeted runtime/queue tests first, then broader lint/test gates.

## Rules Learned

- Queue-backed recovery must use queue evidence as authority.
- DB state must not advance past failed queue operations.
- Recovery must fail closed when queue evidence is missing.
- Duplicate queue payloads must converge to one pending payload.
- Interface changes must update all concrete implementations in the same change.
- Redis queue repair must be atomic and safe for concurrent queue traffic.
- No placeholder text, merge markers, or partial file patches are acceptable in runtime code.

## Compression Result

Historical path: many commits and review corrections.

Clean output: one coherent runtime recovery reconciliation change plus proof tests.
