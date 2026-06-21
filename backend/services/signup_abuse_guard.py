"""Signup abuse prevention guard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from backend.repositories.signup_attempt_log_repository import SignupAttemptLogRepository


class SignupDisabledError(RuntimeError):
    """Raised when signup is globally disabled."""


class SignupRateLimitedError(RuntimeError):
    """Raised when signup or verification ingress exceeds abuse limits."""

    def __init__(self, *, dimension: str, route: str) -> None:
        super().__init__(f"rate limited on {dimension} for {route}")
        self.dimension = dimension
        self.route = route


@dataclass(frozen=True, slots=True)
class SignupAbuseLimits:
    signup_email_per_hour: int = 3
    resend_email_per_hour: int = 2
    verify_failures_per_hour: int = 10


class SignupAbuseGuard:
    """Service-layer per-email abuse enforcement."""

    ROUTE_SIGNUP = "/v1/onboarding/signup"
    ROUTE_RESEND = "/v1/onboarding/resend-verification"
    ROUTE_VERIFY = "/v1/onboarding/verify-email"

    def __init__(
        self,
        session: Session,
        *,
        limits: SignupAbuseLimits | None = None,
        signup_enabled: bool = True,
    ) -> None:
        self._repo = SignupAttemptLogRepository(session)
        self._limits = limits or SignupAbuseLimits()
        self._signup_enabled = signup_enabled

    def assert_signup_enabled(self) -> None:
        if not self._signup_enabled:
            raise SignupDisabledError("signup is temporarily unavailable")

    def check_signup_email(self, *, email_canonical: str, now: datetime | None = None) -> None:
        since = SignupAttemptLogRepository.window_start(hours=1, now=now)
        count = self._repo.count_for_email(
            email_canonical=email_canonical,
            route=self.ROUTE_SIGNUP,
            since=since,
            outcomes=frozenset({"accepted"}),
        )
        if count >= self._limits.signup_email_per_hour:
            raise SignupRateLimitedError(dimension="email", route=self.ROUTE_SIGNUP)

    def check_resend_email(self, *, email_canonical: str, now: datetime | None = None) -> None:
        since = SignupAttemptLogRepository.window_start(hours=1, now=now)
        count = self._repo.count_for_email(
            email_canonical=email_canonical,
            route=self.ROUTE_RESEND,
            since=since,
            outcomes=frozenset({"accepted", "delivery_failed"}),
        )
        if count >= self._limits.resend_email_per_hour:
            raise SignupRateLimitedError(dimension="email", route=self.ROUTE_RESEND)

    def check_verify_failures(self, *, email_canonical: str, now: datetime | None = None) -> None:
        since = SignupAttemptLogRepository.window_start(hours=1, now=now)
        count = self._repo.count_for_email(
            email_canonical=email_canonical,
            route=self.ROUTE_VERIFY,
            since=since,
            outcomes=frozenset({"invalid_input", "error"}),
        )
        if count >= self._limits.verify_failures_per_hour:
            raise SignupRateLimitedError(dimension="email", route=self.ROUTE_VERIFY)

    def record_attempt(
        self,
        *,
        email_canonical: str | None,
        client_ip_hash: str,
        route: str,
        outcome: str,
    ) -> None:
        self._repo.append(
            email_canonical=email_canonical,
            client_ip_hash=client_ip_hash,
            route=route,
            outcome=outcome,
        )
