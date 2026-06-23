"""Rate limiting for customer OIDC login ingress."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from backend.repositories.signup_attempt_log_repository import SignupAttemptLogRepository


class AuthLoginRateLimitedError(RuntimeError):
    def __init__(self, *, dimension: str, route: str) -> None:
        super().__init__(f"rate limited on {dimension} for {route}")
        self.dimension = dimension
        self.route = route


@dataclass(frozen=True, slots=True)
class AuthLoginAbuseLimits:
    start_ip_per_hour: int = 30
    callback_ip_per_hour: int = 30
    callback_email_per_hour: int = 20


class AuthLoginAbuseGuard:
    ROUTE_START = "/v1/auth/oidc/start"
    ROUTE_CALLBACK = "/v1/auth/oidc/callback"
    ROUTE_REFRESH = "/v1/auth/session/refresh"

    def __init__(
        self,
        session: Session,
        *,
        limits: AuthLoginAbuseLimits | None = None,
    ) -> None:
        self._repo = SignupAttemptLogRepository(session)
        self._limits = limits or AuthLoginAbuseLimits()

    def check_start_ip(self, *, client_ip_hash: str, now: datetime | None = None) -> None:
        since = SignupAttemptLogRepository.window_start(hours=1, now=now)
        count = self._repo.count_for_ip(
            client_ip_hash=client_ip_hash,
            route=self.ROUTE_START,
            since=since,
        )
        if count >= self._limits.start_ip_per_hour:
            raise AuthLoginRateLimitedError(dimension="ip", route=self.ROUTE_START)

    def check_callback_ip(self, *, client_ip_hash: str, now: datetime | None = None) -> None:
        since = SignupAttemptLogRepository.window_start(hours=1, now=now)
        count = self._repo.count_for_ip(
            client_ip_hash=client_ip_hash,
            route=self.ROUTE_CALLBACK,
            since=since,
        )
        if count >= self._limits.callback_ip_per_hour:
            raise AuthLoginRateLimitedError(dimension="ip", route=self.ROUTE_CALLBACK)

    def check_callback_email(self, *, email_canonical: str, now: datetime | None = None) -> None:
        since = SignupAttemptLogRepository.window_start(hours=1, now=now)
        count = self._repo.count_for_email(
            email_canonical=email_canonical,
            route=self.ROUTE_CALLBACK,
            since=since,
        )
        if count >= self._limits.callback_email_per_hour:
            raise AuthLoginRateLimitedError(dimension="email", route=self.ROUTE_CALLBACK)

    def record(
        self,
        *,
        client_ip_hash: str,
        route: str,
        outcome: str,
        email_canonical: str | None = None,
    ) -> None:
        self._repo.append(
            email_canonical=email_canonical,
            client_ip_hash=client_ip_hash,
            route=route,
            outcome=outcome,
        )
