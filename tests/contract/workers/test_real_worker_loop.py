from backend.workers.worker_loop import WorkerLoop


def test_worker_loop_class_exists() -> None:
    assert WorkerLoop is not None
