from backend.queue.adapters.nats_adapter import NatsQueueAdapter
from backend.queue.adapters.redis_adapter import RedisQueueAdapter
from backend.queue.adapters.sqs_adapter import SqsQueueAdapter


def test_queue_adapter_classes_exist() -> None:
    assert RedisQueueAdapter is not None
    assert NatsQueueAdapter is not None
    assert SqsQueueAdapter is not None
