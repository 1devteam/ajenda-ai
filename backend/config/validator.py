from __future__ import annotations

from dataclasses import dataclass

from backend.app.config import Settings


class CriticalConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ConfigValidator:
    settings: Settings

    def validate(self) -> None:
        if not self.settings.database_url.strip():
            raise CriticalConfigError("database_url is required")
        if self.settings.env == "production" and not self.settings.log_json:
            raise CriticalConfigError("production requires structured logging")
        if self.settings.port <= 0:
            raise CriticalConfigError("port must be positive")
