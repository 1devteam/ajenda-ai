from __future__ import annotations

import uuid
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from backend.services.security.redaction import contains_sensitive_key

TOOL_INVOCATION_SCHEMA_VERSION = 1
ACTION_RESULT_SCHEMA_VERSION = 1


class SideEffectClass(StrEnum):
    NONE = "none"
    INTERNAL_READ = "internal_read"
    INTERNAL_WRITE = "internal_write"
    EXTERNAL_READ = "external_read"
    EXTERNAL_WRITE = "external_write"
    EXTERNAL_SEND = "external_send"
    EXTERNAL_PUBLISH = "external_publish"

    @property
    def has_side_effect(self) -> bool:
        return self in {
            SideEffectClass.INTERNAL_WRITE,
            SideEffectClass.EXTERNAL_WRITE,
            SideEffectClass.EXTERNAL_SEND,
            SideEffectClass.EXTERNAL_PUBLISH,
        }
