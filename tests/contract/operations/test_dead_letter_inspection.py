from backend.services.operations_service import OperationsService


def test_operations_service_exists() -> None:
    assert OperationsService is not None
