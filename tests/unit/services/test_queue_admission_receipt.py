from __future__ import annotations

import uuid

from backend.services.mission_bridge.queue_admission import record_reviewed_task_admission


def test_reviewed_task_admission_updates_only_exact_task_and_is_idempotent() -> None:
    reviewed = uuid.uuid4()
    unrelated = uuid.uuid4()
    receipt = {
        "admission_status": "partially_admitted",
        "queued_execution_task_ids": [str(uuid.uuid4())],
        "admitted_execution_task_ids": [str(uuid.uuid4())],
        "pending_review_execution_task_ids": [str(reviewed), str(unrelated)],
        "blocked_execution_task_ids": [str(reviewed), str(unrelated)],
        "blockers": [
            {"task_id": str(reviewed), "code": "policy_review_required"},
            {"task_id": str(unrelated), "code": "dependency_not_ready"},
            {"code": "mission_blocker"},
        ],
        "updated_at": "old",
    }

    updated = record_reviewed_task_admission(receipt, task_id=reviewed, now="new")

    assert str(reviewed) in updated["queued_execution_task_ids"]
    assert str(reviewed) in updated["admitted_execution_task_ids"]
    assert str(reviewed) not in updated["pending_review_execution_task_ids"]
    assert str(unrelated) in updated["pending_review_execution_task_ids"]
    assert [item.get("task_id") for item in updated["blockers"]] == [str(unrelated), None]
    assert updated["blocked_execution_task_ids"] == [str(unrelated)]
    assert updated["updated_at"] == "new"

    repeated = record_reviewed_task_admission(updated, task_id=reviewed, now="newer")
    assert repeated["queued_execution_task_ids"].count(str(reviewed)) == 1
    assert repeated["admitted_execution_task_ids"].count(str(reviewed)) == 1
    assert repeated["blockers"] == updated["blockers"]
