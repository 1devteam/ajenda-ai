from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    AUTH_READ = "auth:read"
    AUTH_MANAGE = "auth:manage"
    API_KEYS_CREATE = "api_keys:create"
    API_KEYS_READ = "api_keys:read"
    API_KEYS_REVOKE = "api_keys:revoke"
    EXECUTION_VIEW = "execution:view"
    EXECUTION_QUEUE = "execution:queue"
    PROVISION_WORKFORCE = "workforce:provision"
    RUNTIME_VIEW = "runtime:view"
