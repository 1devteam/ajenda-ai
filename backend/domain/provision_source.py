"""Provision source authority for tenant creation."""

from __future__ import annotations

from enum import StrEnum


class ProvisionSource(StrEnum):
    """Who initiated tenant provisioning."""

    ADMIN = "admin"
    SELF_SERVE = "self_serve"
