from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.services.event_delivery_dispatcher import EventDeliveryDispatchResult
from backend.services.event_delivery_worker import EventDeliveryWorker, EventDeliveryWorkerConfig


def _dispatch_result() -> EventDeliveryDispatchResult:
    return EventDeliveryDispatchResult(
        attempted=2,
        delivered=1,
        retrying=1,
        dead_lettered=0,
    )


def test_event_delivery_worker_runs_dispatcher_once_with_config_defaults() -> None:
    session = MagicMock()
    transport = MagicMock()
    dispatcher = MagicMock()
    dispatcher.dispatch_due.return_value = _dispatch_result()

    with patch(
        "backend.services.event_delivery_worker.EventDeliveryDispatcher",
        return_value=dispatcher,
    ) as dispatcher_cls:
        worker = EventDeliveryWorker(
            session,
            transport,
            config=EventDeliveryWorkerConfig(batch_limit=25, retry_delay_seconds=45),
        )
        result = worker.run_once()

    dispatcher_cls.assert_called_once_with(session, transport, retry_delay_seconds=45)
    dispatcher.dispatch_due.assert_called_once_with(limit=25)
    assert result == _dispatch_result()


def test_event_delivery_worker_allows_per_run_limit_override() -> None:
    session = MagicMock()
    transport = MagicMock()
    dispatcher = MagicMock()
    dispatcher.dispatch_due.return_value = _dispatch_result()

    with patch(
        "backend.services.event_delivery_worker.EventDeliveryDispatcher",
        return_value=dispatcher,
    ):
        worker = EventDeliveryWorker(
            session,
            transport,
            config=EventDeliveryWorkerConfig(batch_limit=25, retry_delay_seconds=45),
        )
        result = worker.run_once(limit=5)

    dispatcher.dispatch_due.assert_called_once_with(limit=5)
    assert result == _dispatch_result()


def test_event_delivery_worker_uses_http_transport_by_default() -> None:
    session = MagicMock()
    dispatcher = MagicMock()
    dispatcher.dispatch_due.return_value = _dispatch_result()

    with (
        patch("backend.services.event_delivery_worker.HttpEventDeliveryTransport") as transport_cls,
        patch(
            "backend.services.event_delivery_worker.EventDeliveryDispatcher",
            return_value=dispatcher,
        ) as dispatcher_cls,
    ):
        transport = transport_cls.return_value
        worker = EventDeliveryWorker(session)
        result = worker.run_once()

    transport_cls.assert_called_once_with()
    dispatcher_cls.assert_called_once_with(session, transport, retry_delay_seconds=60)
    dispatcher.dispatch_due.assert_called_once_with(limit=100)
    assert result == _dispatch_result()


@pytest.mark.parametrize("limit", [0, -1])
def test_event_delivery_worker_rejects_invalid_limits(limit: int) -> None:
    worker = EventDeliveryWorker(MagicMock(), MagicMock())

    with pytest.raises(ValueError, match="limit must be >= 1"):
        worker.run_once(limit=limit)
