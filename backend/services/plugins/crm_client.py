from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from backend.services.network_egress import get_default_network_egress_authority
from backend.services.plugins.contracts import STANDARD_CRM_CONTRACT, CrmContractPaths
from backend.services.tools.record_store import resolve_record_store
from backend.services.tools.schemas import ActionRuntimeContext, RuntimeCredentialMaterial, ToolInvocation


@dataclass(slots=True)
class CrmSearchResult:
    results: list[dict[str, Any]]
    count: int
    source: str
    real: bool
    status_code: int | None = None
    error: str | None = None


@dataclass(slots=True)
class CrmUpsertResult:
    record_type: str
    record_id: str
    data: dict[str, Any]
    source: str
    real: bool
    status: str
    status_code: int | None = None
    error: str | None = None
    # Legacy/unit callers that construct a successful result represent an
    # already-verified provider result. Live external upserts set this
    # explicitly only after the adapter read-back succeeds.
    effect_verified: bool = True
    readback: dict[str, Any] | None = None


@dataclass(slots=True)
class CrmReadbackResult:
    record_type: str
    record_id: str
    data: dict[str, Any]
    source: str
    real: bool
    effect_verified: bool
    status_code: int | None = None
    error: str | None = None


def _credential_secret(cred: RuntimeCredentialMaterial | dict[str, Any] | None) -> str | None:
    if cred is None:
        return None
    if isinstance(cred, dict):
        secret = cred.get("secret_value")
        return str(secret) if isinstance(secret, str) and secret else None
    return cred.secret_value or None


def _trusted_hosts(
    cred: RuntimeCredentialMaterial | dict[str, Any] | None,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if cred is None:
        return default
    if isinstance(cred, dict):
        raw_hosts = cred.get("trusted_destination_hosts")
        if raw_hosts:
            return tuple(str(host) for host in raw_hosts)
        return default
    if cred.trusted_destination_hosts:
        return cred.trusted_destination_hosts
    return default


def _http_success(status_code: int) -> bool:
    return 200 <= status_code < 300


def is_live_external_crm_result(*, source: str, real: bool, error: str | None = None) -> bool:
    """True when CRM search/upsert came from a live adapter, not Ajenda brain fallback."""
    return real and not error and source != "ajenda_brain"


def _parse_trusted_endpoint(raw_host: str) -> tuple[str, int | None]:
    stripped = raw_host.strip().lower().rstrip(".")
    if not stripped:
        raise ValueError("trusted destination host must be non-empty")
    if ":" in stripped and not stripped.startswith("["):
        host, _, port_text = stripped.partition(":")
        if port_text.isdigit():
            return host, int(port_text)
    return stripped, None


def _adapter_base_url(raw_host: str) -> str:
    host, port = _parse_trusted_endpoint(raw_host)
    if port is None or port == 443:
        return f"https://{host}"
    return f"https://{host}:{port}"


def _allowed_adapter_hosts(raw_hosts: tuple[str, ...]) -> list[str]:
    return [_parse_trusted_endpoint(item)[0] for item in raw_hosts]


class StandardCrmClient:
    """Routes CRM operations to external adapter contract or internal brain store."""

    def __init__(self, *, contract_paths: CrmContractPaths = STANDARD_CRM_CONTRACT) -> None:
        self._search_path = contract_paths.search_path
        self._upsert_path = contract_paths.upsert_path

    def search(
        self,
        *,
        context: ActionRuntimeContext,
        company: str = "",
        domain: str = "",
        credential: RuntimeCredentialMaterial | dict[str, Any] | None,
        invocation: ToolInvocation | None = None,
        action_name: str = "crm.research",
    ) -> CrmSearchResult:
        secret = _credential_secret(credential)
        if secret:
            try:
                trusted = _trusted_hosts(credential, default=("api.crm.example.com",))
                query = urlencode(
                    {
                        key: value
                        for key, value in (("company", company), ("domain", domain))
                        if isinstance(value, str) and value.strip()
                    }
                )
                search_url = f"{_adapter_base_url(trusted[0])}{self._search_path}?{query}"
                headers = {"Authorization": f"Bearer {secret}"}
                if invocation and invocation.idempotency_key and invocation.idempotency_key.strip():
                    headers["Idempotency-Key"] = invocation.idempotency_key.strip()
                _dest, resp = get_default_network_egress_authority().request(
                    method="GET",
                    url=search_url,
                    headers=headers,
                    allowed_hosts=_allowed_adapter_hosts(trusted),
                    action_name=action_name,
                    timeout_seconds=10.0,
                )
                if not _http_success(resp.status_code):
                    return self._internal_search_fallback(
                        context=context,
                        company=company,
                        domain=domain,
                        error=f"CRM search returned HTTP {resp.status_code}",
                        status_code=resp.status_code,
                    )
                payload = json.loads(resp.body_text or "{}")
                results = payload.get("results", [])
                if not isinstance(results, list):
                    results = []
                return CrmSearchResult(
                    results=results,
                    count=int(payload.get("count", len(results))),
                    source=str(payload.get("source", "external_crm")),
                    real=True,
                    status_code=resp.status_code,
                )
            except Exception as exc:
                return self._internal_search_fallback(
                    context=context,
                    company=company,
                    domain=domain,
                    error=str(exc),
                )

        return self._internal_search(context=context, company=company, domain=domain)

    def _internal_search(
        self,
        *,
        context: ActionRuntimeContext,
        company: str,
        domain: str,
    ) -> CrmSearchResult:
        store = resolve_record_store(context)
        matches = store.search_records(
            tenant_id=context.tenant_id,
            record_type="contact",
            query=company or domain,
            limit=10,
        )
        if not matches and company:
            matches = store.search_records(
                tenant_id=context.tenant_id,
                record_type="account",
                query=company,
                limit=5,
            )
        return CrmSearchResult(
            results=matches,
            count=len(matches),
            source="ajenda_brain",
            real=True,
        )

    def _internal_search_fallback(
        self,
        *,
        context: ActionRuntimeContext,
        company: str,
        domain: str,
        error: str,
        status_code: int | None = None,
    ) -> CrmSearchResult:
        fallback = self._internal_search(context=context, company=company, domain=domain)
        return CrmSearchResult(
            results=fallback.results,
            count=fallback.count,
            source="ajenda_brain",
            real=True,
            status_code=status_code,
            error=error,
        )

    def upsert(
        self,
        *,
        context: ActionRuntimeContext,
        record_type: str,
        data: dict[str, Any],
        credential: RuntimeCredentialMaterial | dict[str, Any] | None,
        invocation: ToolInvocation | None = None,
        action_name: str = "gtm.crm_upsert",
    ) -> CrmUpsertResult:
        secret = _credential_secret(credential)
        if secret:
            try:
                trusted = _trusted_hosts(credential, default=("api.crm.example.com",))
                upsert_url = f"{_adapter_base_url(trusted[0])}{self._upsert_path}"
                headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
                body: dict[str, Any] = {"record_type": record_type, "data": data}
                if invocation and invocation.idempotency_key and invocation.idempotency_key.strip():
                    headers["Idempotency-Key"] = invocation.idempotency_key.strip()
                    body["idempotency_key"] = invocation.idempotency_key.strip()
                _dest, resp = get_default_network_egress_authority().request(
                    method="POST",
                    url=upsert_url,
                    headers=headers,
                    json_body=body,
                    allowed_hosts=_allowed_adapter_hosts(trusted),
                    action_name=action_name,
                    timeout_seconds=10.0,
                )
                if not _http_success(resp.status_code):
                    return CrmUpsertResult(
                        record_type=record_type,
                        record_id="",
                        data=data,
                        source="external_crm",
                        real=False,
                        status="error",
                        status_code=resp.status_code,
                        error=f"CRM upsert returned HTTP {resp.status_code}",
                        effect_verified=False,
                    )
                payload = json.loads(resp.body_text or "{}")
                record_id = str(payload.get("id", ""))
                if not record_id:
                    return CrmUpsertResult(
                        record_type=record_type,
                        record_id="",
                        data=data,
                        source="external_crm",
                        real=False,
                        status="effect_unverified",
                        status_code=resp.status_code,
                        error="CRM upsert response missing provider record id",
                        effect_verified=False,
                    )
                requested_properties = payload.get("requested_properties")
                provider_properties = payload.get("properties")
                if isinstance(requested_properties, dict):
                    expected_properties = requested_properties
                elif isinstance(provider_properties, dict):
                    expected_properties = provider_properties
                else:
                    expected_properties = {}
                readback = self.readback(
                    context=context,
                    record_type=record_type,
                    record_id=record_id,
                    credential=credential,
                    expected_properties=expected_properties,
                    action_name=action_name,
                )
                if not readback.effect_verified:
                    return CrmUpsertResult(
                        record_type=record_type,
                        record_id=record_id,
                        data=data,
                        source=str(payload.get("source", "external_crm")),
                        real=False,
                        status="effect_unverified",
                        status_code=readback.status_code or resp.status_code,
                        error=readback.error or "CRM provider effect read-back did not verify",
                        effect_verified=False,
                        readback=readback.data,
                    )
                return CrmUpsertResult(
                    record_type=record_type,
                    record_id=record_id,
                    data=data,
                    source=str(payload.get("source", "external_crm")),
                    real=True,
                    status="upserted_real",
                    status_code=resp.status_code,
                    effect_verified=True,
                    readback=readback.data,
                )
            except Exception as exc:
                return CrmUpsertResult(
                    record_type=record_type,
                    record_id="",
                    data=data,
                    source="external_crm",
                    real=False,
                    status="error",
                    error=str(exc),
                    effect_verified=False,
                )

        normalized_type = _normalize_record_type(record_type)
        if context.session_factory is not None:
            from backend.services.light_crm.workflow import complete_internal_crm_upsert

            session = context.session_factory()
            try:
                saved = complete_internal_crm_upsert(
                    session=session,
                    tenant_id=context.tenant_id,
                    record_type=normalized_type,
                    data=data,
                    mission_id=str(context.mission_id) if context.mission_id else None,
                    task_id=str(context.task_id) if context.task_id else None,
                    commit=True,
                )
            finally:
                session.close()
        else:
            raise ValueError("gtm.crm_upsert internal write requires session_factory for governed CRM workflow hooks")
        return CrmUpsertResult(
            record_type=normalized_type,
            record_id=str(saved.get("id", "")),
            data=saved,
            source="ajenda_brain",
            real=True,
            status="upserted_internal",
        )

    def readback(
        self,
        *,
        context: ActionRuntimeContext,
        record_type: str,
        record_id: str,
        credential: RuntimeCredentialMaterial | dict[str, Any] | None,
        expected_properties: dict[str, Any] | None = None,
        action_name: str = "crm.verify_effect",
    ) -> CrmReadbackResult:
        """Read provider state through the same governed adapter boundary."""

        secret = _credential_secret(credential)
        if not secret:
            return CrmReadbackResult(
                record_type=record_type,
                record_id=record_id,
                data={},
                source="external_crm",
                real=False,
                effect_verified=False,
                error="CRM read-back requires a runtime credential",
            )
        try:
            trusted = _trusted_hosts(credential, default=("api.crm.example.com",))
            read_url = f"{_adapter_base_url(trusted[0])}{self._read_path(record_type, record_id)}"
            _dest, resp = get_default_network_egress_authority().request(
                method="GET",
                url=read_url,
                headers={"Authorization": f"Bearer {secret}"},
                allowed_hosts=_allowed_adapter_hosts(trusted),
                action_name=action_name,
                timeout_seconds=10.0,
            )
            if not _http_success(resp.status_code):
                return CrmReadbackResult(
                    record_type=record_type,
                    record_id=record_id,
                    data={},
                    source="external_crm",
                    real=False,
                    effect_verified=False,
                    status_code=resp.status_code,
                    error=f"CRM read-back returned HTTP {resp.status_code}",
                )
            payload = json.loads(resp.body_text or "{}")
            actual_id = str(payload.get("id", ""))
            properties = payload.get("properties", {})
            if actual_id != record_id or not isinstance(properties, dict):
                return CrmReadbackResult(
                    record_type=record_type,
                    record_id=record_id,
                    data=payload if isinstance(payload, dict) else {},
                    source=str(payload.get("source", "external_crm")) if isinstance(payload, dict) else "external_crm",
                    real=True,
                    effect_verified=False,
                    status_code=resp.status_code,
                    error="CRM read-back identity or properties were invalid",
                )
            expected = expected_properties or {}
            mismatched_keys = sorted(
                key
                for key, expected_value in expected.items()
                if key not in properties or properties.get(key) != expected_value
            )
            if mismatched_keys:
                return CrmReadbackResult(
                    record_type=record_type,
                    record_id=record_id,
                    data=payload,
                    source=str(payload.get("source", "external_crm")),
                    real=True,
                    effect_verified=False,
                    status_code=resp.status_code,
                    error="CRM read-back did not match requested provider properties: " + ", ".join(mismatched_keys),
                )
            return CrmReadbackResult(
                record_type=record_type,
                record_id=record_id,
                data=payload,
                source=str(payload.get("source", "external_crm")),
                real=True,
                effect_verified=True,
                status_code=resp.status_code,
            )
        except Exception as exc:
            return CrmReadbackResult(
                record_type=record_type,
                record_id=record_id,
                data={},
                source="external_crm",
                real=False,
                effect_verified=False,
                error=str(exc),
            )

    @staticmethod
    def _read_path(record_type: str, record_id: str) -> str:
        from urllib.parse import quote

        return f"/v1/records/{quote(record_type.strip(), safe='')}/{quote(record_id.strip(), safe='')}"


def _normalize_record_type(record_type: str) -> str:
    normalized = record_type.strip().lower()
    mapping = {
        "lead": "contact",
        "leads": "contact",
        "company": "account",
        "companies": "account",
        "deal": "opportunity",
        "deals": "opportunity",
    }
    return mapping.get(normalized, normalized)


_default_crm_client: StandardCrmClient | None = None


def default_crm_client() -> StandardCrmClient:
    global _default_crm_client
    if _default_crm_client is None:
        _default_crm_client = StandardCrmClient()
    return _default_crm_client
