from __future__ import annotations

from typing import Any

import httpx

from backend.auth.permissions import Permission
from backend.auth.principal import Principal
from backend.policy.pdp import PolicyDecision


class OpaPolicyDecisionPoint:
    """Policy Decision Point backed by an OPA HTTP API.

    Contract:
      POST {base_url}/v1/data/ajenda/authz/allow
      body: {"input": { ... }}
      response result may be:
        - bool
        - {"allow": bool, "reason": str}
    """

    def __init__(
        self,
        *,
        base_url: str,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client(timeout=timeout_seconds)

    def authorize(self, *, principal: Principal, permission: Permission, tenant_id: str) -> PolicyDecision:
        payload: dict[str, Any] = {
            "input": {
                "principal": {
                    "subject_id": principal.subject_id,
                    "tenant_id": principal.tenant_id,
                    "type": principal.principal_type.value,
                    "roles": sorted(principal.roles),
                    "permissions": sorted(p.value for p in principal.permissions),
                },
                "permission": permission.value,
                "tenant_id": tenant_id,
            }
        }
        try:
            response = self._http.post(f"{self._base_url}/v1/data/ajenda/authz/allow", json=payload)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            return PolicyDecision(
                allowed=False,
                reason=f"OPA decision failed: {exc}",
                policy_source="opa",
            )

        result = body.get("result")
        if isinstance(result, bool):
            return PolicyDecision(
                allowed=result,
                reason="opa_allow" if result else "opa_deny",
                policy_source="opa",
            )

        if isinstance(result, dict):
            allowed = bool(result.get("allow", False))
            reason = str(result.get("reason", "opa_allow" if allowed else "opa_deny"))
            return PolicyDecision(
                allowed=allowed,
                reason=reason,
                policy_source="opa",
            )

        return PolicyDecision(
            allowed=False,
            reason="OPA returned invalid decision payload",
            policy_source="opa",
        )
