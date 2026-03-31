import pytest

from backend.app.config import Settings
from backend.config.validator import ConfigValidator, CriticalConfigError


def test_validator_rejects_invalid_port() -> None:
    settings = Settings.model_construct(database_url="sqlite://", env="development", log_json=False, port=0)
    with pytest.raises(CriticalConfigError):
        ConfigValidator(settings).validate()
