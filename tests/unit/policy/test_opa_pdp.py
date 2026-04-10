from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from backend.auth.permissions import Permission
from backend.auth.principal import Principal, PrincipalType
from backend.policy.opa_pdp import OpaPolicyDecisionPoint


def _principal() -> Principal:
    return Principal(
        "user-1",
        "tenant-a",
        PrincipalType.USER,
        roles=frozenset({"admin"}),
        permissions=frozenset({Permission.RUNTIME_VIEW}),
    )


def test_opa_pdp_accepts_boolean_result_payload() -> None:
    mock_http = MagicMock(spec=httpx.Client)
    mock_response = MagicMock()
    mock_response.json.return_value = {"result": True}
    mock_response.raise_for_status.return_value = None
    mock_http.post.return_value = mock_response

    pdp = OpaPolicyDecisionPoint(base_url="http://opa:8181", http_client=mock_http)
    decision = pdp.authorize(principal=_principal(), permission=Permission.RUNTIME_VIEW, tenant_id="tenant-a")

    assert decision.allowed is True
    assert decision.policy_source == "opa"


def test_opa_pdp_parses_structured_result_payload() -> None:
    mock_http = MagicMock(spec=httpx.Client)
    mock_response = MagicMock()
    mock_response.json.return_value = {"result": {"allow": False, "reason": "missing_claim"}}
    mock_response.raise_for_status.return_value = None
    mock_http.post.return_value = mock_response

    pdp = OpaPolicyDecisionPoint(base_url="http://opa:8181", http_client=mock_http)
    decision = pdp.authorize(principal=_principal(), permission=Permission.RUNTIME_VIEW, tenant_id="tenant-a")

    assert decision.allowed is False
    assert decision.reason == "missing_claim"


def test_opa_pdp_fails_closed_on_transport_error() -> None:
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.post.side_effect = httpx.ConnectError("refused")

    pdp = OpaPolicyDecisionPoint(base_url="http://opa:8181", http_client=mock_http)
    decision = pdp.authorize(principal=_principal(), permission=Permission.RUNTIME_VIEW, tenant_id="tenant-a")

    assert decision.allowed is False
    assert "OPA decision failed" in decision.reason
