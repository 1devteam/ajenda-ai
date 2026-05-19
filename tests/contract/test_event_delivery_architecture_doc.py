from pathlib import Path

EVENT_DOC = Path("docs/EVENT_DELIVERY_ARCHITECTURE.md")
SAAS_DOC = Path("docs/SAAS_ARCHITECTURE.md")
README = Path("README.md")

EVENT_REQUIRED_TERMS = (
    "durable outbox foundation",
    "EventDeliveryState",
    "EventDeliveryRepository",
    "EventDeliveryService",
    "EventDeliveryDispatcher",
    "EventDeliveryTransport",
    "EventDeliveryTransportResult",
    "EventDeliveryDispatchResult",
    "tenant_id + idempotency_key",
    "with_for_update(skip_locked=True)",
    "claim before transport",
    "transport exceptions",
    "tests/unit/events/test_event_delivery_foundation.py",
    "tests/unit/events/test_event_delivery_dispatcher.py",
    "tests/contract/test_event_delivery_contracts.py",
    "tests/integration/events/test_event_delivery_persistence_real.py",
    "tests/integration/events/test_event_delivery_dispatcher_real.py",
    "AJENDA_TEST_DATABASE_URL",
    "Not implemented yet",
    "external HTTP transport implementation",
    "retry worker loop",
)


def test_event_delivery_architecture_doc_exists_and_defines_contract() -> None:
    text = EVENT_DOC.read_text()

    for term in EVENT_REQUIRED_TERMS:
        assert term in text


def test_readme_links_event_delivery_architecture_doc() -> None:
    assert "docs/EVENT_DELIVERY_ARCHITECTURE.md" in README.read_text()


def test_saas_architecture_reflects_event_delivery_as_implemented() -> None:
    text = SAAS_DOC.read_text()

    assert "Event delivery foundation" in text
    assert "webhook/event delivery foundation" not in text
    assert "docs/EVENT_DELIVERY_ARCHITECTURE.md" in text
