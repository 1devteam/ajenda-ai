from uuid import uuid4

from backend.queue.local_adapter import LocalQueueAdapter


def test_dead_letter_routing_is_recorded() -> None:
    adapter = LocalQueueAdapter()
    task_id = uuid4()
    result = adapter.move_to_dead_letter(tenant_id="tenant-a", task_id=task_id, reason="retry exhausted")
    assert result.ok is True
