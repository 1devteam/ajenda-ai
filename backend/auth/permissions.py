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
    MISSION_CREATE = "mission:create"
    MISSION_MANAGE = "mission:manage"
    RUNTIME_OPERATE = "runtime:operate"
    PROVISION_WORKFORCE = "workforce:provision"
    RUNTIME_VIEW = "runtime:view"
    CAPABILITY_MANAGE = "capability:manage"
    EVIDENCE_MANAGE = "evidence:manage"
    OUTCOME_REVIEW_MANAGE = "outcome_review:manage"
    RETRIEVAL_MANAGE = "retrieval:manage"
    BUSINESS_PROFILE_READ = "business_profile:read"
    BUSINESS_PROFILE_MANAGE = "business_profile:manage"
    ACCOUNT_READ = "account:read"
    BILLING_READ = "billing:read"
    BILLING_MANAGE = "billing:manage"
