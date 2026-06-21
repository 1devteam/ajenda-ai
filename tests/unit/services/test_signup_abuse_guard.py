"""Unit tests for signup abuse guard."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from backend.services.signup_abuse_guard import (
    SignupAbuseGuard,
    SignupAbuseLimits,
    SignupDisabledError,
    SignupRateLimitedError,
)


def test_signup_abuse_guard_blocks_disabled_signup() -> None:
    guard = SignupAbuseGuard(MagicMock(), signup_enabled=False)
    with pytest.raises(SignupDisabledError):
        guard.assert_signup_enabled()


def test_signup_abuse_guard_blocks_email_rate_limit() -> None:
    session = MagicMock()
    guard = SignupAbuseGuard(session, limits=SignupAbuseLimits(signup_email_per_hour=3))
    guard._repo.count_for_email = MagicMock(return_value=3)  # type: ignore[method-assign]

    with pytest.raises(SignupRateLimitedError) as exc_info:
        guard.check_signup_email(email_canonical="owner@example.com", now=datetime.now(UTC))
    assert exc_info.value.dimension == "email"
    guard._repo.count_for_email.assert_called_once()
