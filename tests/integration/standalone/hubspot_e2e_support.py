from __future__ import annotations

import os


def resolve_hubspot_access_token() -> str | None:
    """Return an explicitly supplied, durable HubSpot CRM bearer credential.

    HubSpot CLI Personal Access Keys and its local OAuth cache are intentionally
    excluded: neither is a reliable credential source for a CRM integration proof.
    """

    token = os.environ.get("AJENDA_E2E_HUBSPOT_CRM_TOKEN", "").strip()
    return token or None
