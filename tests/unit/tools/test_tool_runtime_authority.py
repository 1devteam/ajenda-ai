from __future__ import annotations

import uuid

import pytest

from backend.domain.business_profile import BusinessProfile
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.credentials.runtime_authority import (
    CredentialRecord,
    CredentialRequirement,
    CredentialRuntimeAuthority,
    InMemoryCredentialRuntimeRepository,
)
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.runtime_authority import ToolRuntimeAuthority, ToolRuntimeAuthorityError
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    RecordSearchInput,
    SideEffectClass,
    ToolInvocation,
)


class _Session:
    def execute(self, *_args: object, **_kwargs: object) -> None:
        return None

    def close(self) -> None:
        pass


class _CharterSession(_Session):
    def __init__(self, profile: BusinessProfile) -> None:
        self.profile = profile
        self.audit_events: list[object] = []
        self.commit_count = 0

    def scalar(self, _statement: object) -> BusinessProfile:
        return self.profile

    def add(self, event: object) -> None:
        self.audit_events.append(event)

    def flush(self) -> None:
        pass

    def refresh(self, _event: object) -> None:
        pass

    def commit(self) -> None:
        self.commit_count += 1


def _session_factory() -> _Session:
    return _Session()


def _handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    return ActionResult(action="unmanifested.action", provider="test", output={}, evidence=[], summary="done")


def _task(
    *,
    action: str = "record.search",
    input_payload: dict | None = None,
    metadata: dict | None = None,
    status: str = ExecutionTaskState.RUNNING.value,
) -> ExecutionTask:
    metadata_json = {"tool_invocation": {"action": action, "input": input_payload or {}}}
    if metadata:
        metadata_json.update(metadata)
    return ExecutionTask(
        id=uuid.uuid4(),
        tenant_id="tenant",
        mission_id=uuid.uuid4(),
        title="Tool task",
        description="Tool task",
        status=status,
        metadata_json=metadata_json,
    )


def _context(tenant_id: str = "tenant") -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "worker_id": "worker-1",
        "lease_id": "lease-1",
        "session_factory": _session_factory,
    }


def test_runtime_enriches_invocation_credential_reference_from_task_metadata() -> None:
    invocation = ToolInvocation(action="sales.research", input={"lead": {"company": "Acme"}})
    enriched = ToolRuntimeAuthority._enrich_invocation_from_metadata(
        invocation=invocation,
        metadata={
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "credential_type": "api_key",
            }
        },
    )

    assert enriched.credential_reference is not None
    assert enriched.credential_reference.credential_id == "hubspot-crm"


def test_runtime_authority_denies_registered_action_without_ability_manifest() -> None:
    registry = ActionRegistry()
    registry.register(
        ActionDefinition(
            name="unmanifested.action",
            handler=_handler,
            provider="test",
            side_effect_class=SideEffectClass.NONE,
        )
    )
    registry.freeze()

    with pytest.raises(ToolRuntimeAuthorityError, match="has no ability manifest"):
        ToolRuntimeAuthority(registry=registry).authorize(
            task=_task(action="unmanifested.action"),
            context=_context(),
        )


def test_runtime_authority_returns_deterministic_promotion_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.tools import runtime_authority

    class PromotionDenied(runtime_authority.CapabilityActionValidationError):
        pass

    def deny_with_capability_error(**kwargs: object) -> None:
        raise PromotionDenied("runtime promotion requires explicit capability/adapter authority")

    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", deny_with_capability_error)
    activated: list[tuple[object, str]] = []
    monkeypatch.setattr(
        runtime_authority,
        "activate_tenant_session",
        lambda session, tenant_id: activated.append((session, tenant_id)),
    )

    with pytest.raises(
        ToolRuntimeAuthorityError,
        match=r"tool\.invoke promotion denied: runtime promotion requires explicit capability/adapter authority",
    ):
        ToolRuntimeAuthority().authorize(
            task=_task(action="http.request", input_payload={"url": "https://example.com"}),
            context=_context(),
        )
    assert len(activated) == 1
    assert activated[0][1] == "tenant"


def _credential_registry() -> ActionRegistry:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        credential = context.runtime_credentials["record.search"]
        return ActionResult(
            action="record.search",
            provider="local_records",
            output={
                "credential_id": credential.reference.credential_id,
                "token": credential.secret_value,
                "message": f"neutral echo {credential.secret_value}",
            },
            evidence=[
                EvidenceItem(
                    evidence_type="action_result",
                    evidence_source="tool.invoke.record.search",
                    action_name="record.search",
                    tool_provider="local_records",
                    tenant_id=context.tenant_id,
                    task_id=str(context.task_id),
                    mission_id=str(context.mission_id) if context.mission_id else None,
                    summary=f"credential runtime path checked without leaking {credential.secret_value}",
                    structured_payload={
                        "credential_id": credential.reference.credential_id,
                        "secret": credential.secret_value,
                    },
                )
            ],
            summary=f"credential runtime path checked without leaking {credential.secret_value}",
        )

    registry.register(
        ActionDefinition(
            name="record.search",
            handler=handler,
            provider="local_records",
            input_model=RecordSearchInput,
            credential_requirement=CredentialRequirement(provider="local_records", credential_type="api_key"),
        )
    )
    registry.freeze()
    return registry


def _credential_authority(record: CredentialRecord | None = None) -> CredentialRuntimeAuthority:
    return CredentialRuntimeAuthority(repository=InMemoryCredentialRuntimeRepository([record] if record else []))


def _credential_record(**overrides: object) -> CredentialRecord:
    values = {
        "credential_id": "cred-1",
        "tenant_id": "tenant",
        "provider": "local_records",
        "credential_type": "api_key",
        "allowed_actions": ("record.search",),
        "secret_value": "sk-runtime-secret",
    }
    values.update(overrides)
    return CredentialRecord.model_validate(values)


def _credential_reference(**overrides: object) -> dict[str, object]:
    values = {"schema_version": 1, "credential_id": "cred-1", "provider": "local_records", "credential_type": "api_key"}
    values.update(overrides)
    return values


def _allow_promotion(monkeypatch: pytest.MonkeyPatch, calls: list[str] | None = None) -> None:
    from backend.services.tools import runtime_authority

    def allow(**kwargs: object) -> None:
        if calls is not None:
            calls.append("promotion")

    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", allow)


def test_runtime_injects_credential_after_promotion_and_redacts_secret_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _allow_promotion(monkeypatch, calls)
    authority = ToolRuntimeAuthority(
        registry=_credential_registry(),
        credential_authority=_credential_authority(_credential_record()),
    )

    result = authority.execute(
        task=_task(
            input_payload={"record_type": "account"}, metadata={"credential_reference": _credential_reference()}
        ),
        context=_context(),
    )

    assert calls == ["promotion"]
    assert result["output"] == {
        "credential_id": "cred-1",
        "token": "***REDACTED***",
        "message": "neutral echo ***REDACTED***",
    }
    assert result["evidence"][0]["structured_payload"] == {
        "credential_id": "cred-1",
        "secret": "***REDACTED***",
    }
    assert result["summary"] == "credential runtime path checked without leaking ***REDACTED***"
    assert "sk-runtime-secret" not in str(result)
    assert "runtime_credentials" not in result["runtime_context"]


def test_credential_existence_does_not_bypass_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.tools import runtime_authority

    def deny(**kwargs: object) -> None:
        raise runtime_authority.CapabilityActionValidationError("runtime promotion requires explicit authority")

    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", deny)
    authority = ToolRuntimeAuthority(
        registry=_credential_registry(),
        credential_authority=_credential_authority(_credential_record()),
    )

    with pytest.raises(ToolRuntimeAuthorityError, match="promotion denied"):
        authority.execute(
            task=_task(
                input_payload={"record_type": "account"}, metadata={"credential_reference": _credential_reference()}
            ),
            context=_context(),
        )


def test_runtime_denies_missing_cross_tenant_disabled_and_mismatched_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_promotion(monkeypatch)
    cases = [
        (_credential_authority(), _credential_reference(), "not visible"),
        (_credential_authority(_credential_record(tenant_id="other")), _credential_reference(), "not visible"),
        (_credential_authority(_credential_record(enabled=False)), _credential_reference(), "disabled"),
        (_credential_authority(_credential_record(revoked=True)), _credential_reference(), "revoked"),
        (_credential_authority(_credential_record(deleted=True)), _credential_reference(), "deleted"),
        (_credential_authority(_credential_record()), _credential_reference(provider="wrong"), "provider/type"),
        (
            _credential_authority(_credential_record(allowed_actions=("record.read",))),
            _credential_reference(),
            "action",
        ),
    ]
    for credential_authority, reference, message in cases:
        authority = ToolRuntimeAuthority(registry=_credential_registry(), credential_authority=credential_authority)
        with pytest.raises(ToolRuntimeAuthorityError, match=message):
            authority.execute(
                task=_task(input_payload={"record_type": "account"}, metadata={"credential_reference": reference}),
                context=_context(),
            )


def test_runtime_rejects_raw_secret_metadata_and_invocation_input(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_promotion(monkeypatch)
    authority = ToolRuntimeAuthority(
        registry=_credential_registry(),
        credential_authority=_credential_authority(_credential_record()),
    )

    with pytest.raises(ToolRuntimeAuthorityError, match="task metadata"):
        authority.authorize(task=_task(metadata={"password": "raw"}), context=_context())
    with pytest.raises(ToolRuntimeAuthorityError, match="task metadata"):
        authority.authorize(
            task=_task(
                input_payload={"filters": {"access_token": "raw"}},
                metadata={"credential_reference": _credential_reference()},
            ),
            context=_context(),
        )


def test_queued_external_write_rechecks_current_charter_before_provider_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revocation overrides prior capability approval before a provider call."""
    from backend.services.tools import runtime_authority

    provider_calls: list[str] = []

    def fake_provider(invocation: ToolInvocation, _context: ActionRuntimeContext) -> ActionResult:
        provider_calls.append(invocation.action)
        return ActionResult(
            action=invocation.action,
            provider="fake_provider",
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
            output={},
            evidence=[],
            summary="fake provider called",
        )

    registry = ActionRegistry()
    registry.register(
        ActionDefinition(
            name="web.open_write",
            handler=fake_provider,
            provider="fake_provider",
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        )
    )
    registry.freeze()
    profile = BusinessProfile(
        tenant_id="tenant",
        approved_facts={
            "operating_charter": {
                "value": {
                    "schema_version": 1,
                    "revision": 2,
                    "may_prepare": [],
                    "may_perform": [],  # permission was revoked after queue admission
                    "never_do": ["gtm.email_send", "gtm.social_publish", "webhook.dispatch"],
                    "approval_mode": "none",
                }
            }
        },
        provenance={},
    )
    session = _CharterSession(profile)
    task = _task(action="web.open_write")
    authority = ToolRuntimeAuthority(registry=registry)
    monkeypatch.setattr(runtime_authority, "activate_tenant_session", lambda *_args: None)
    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", lambda **_kwargs: None)
    monkeypatch.setattr(authority, "_validate_ability_manifest", lambda _action: None)
    monkeypatch.setattr(
        runtime_authority,
        "bind_tool_invocation_for_task",
        lambda **_kwargs: (task.metadata_json["tool_invocation"], {"skipped": True}),
    )

    with pytest.raises(ToolRuntimeAuthorityError, match="CHARTER_PERFORM_NOT_ALLOWED"):
        authority.execute(
            task=task,
            context={
                "tenant_id": "tenant",
                "worker_id": "worker-1",
                "lease_id": "lease-1",
                "session_factory": lambda: session,
            },
        )

    assert provider_calls == []
    assert session.commit_count == 1
    denial = session.audit_events[0]
    assert denial.payload_json["reason_code"] == "CHARTER_PERFORM_NOT_ALLOWED"
    assert denial.payload_json["enforcement_boundary"] == "pre_provider_invocation"


def test_side_effect_revalidation_allows_unchanged_permission_after_charter_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revision change alone does not reject work allowed by the current charter."""
    from backend.services.tools import runtime_authority

    provider_calls: list[str] = []

    def fake_provider(invocation: ToolInvocation, _context: ActionRuntimeContext) -> ActionResult:
        provider_calls.append(invocation.action)
        return ActionResult(
            action=invocation.action,
            provider="fake_provider",
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
            output={"status": "accepted"},
            evidence=[
                EvidenceItem(
                    evidence_type="provider_receipt",
                    evidence_source="fake_provider",
                    action_name=invocation.action,
                    tool_provider="fake_provider",
                    tenant_id="tenant",
                    task_id=str(_context.task_id),
                    mission_id=str(_context.mission_id) if _context.mission_id is not None else None,
                    summary="fake provider receipt",
                    side_effect_class=SideEffectClass.EXTERNAL_WRITE,
                )
            ],
            summary="fake provider called",
        )

    registry = ActionRegistry()
    registry.register(
        ActionDefinition(
            name="web.open_write",
            handler=fake_provider,
            provider="fake_provider",
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        )
    )
    registry.freeze()
    profile = BusinessProfile(
        tenant_id="tenant",
        approved_facts={
            "operating_charter": {
                "value": {
                    "schema_version": 1,
                    "revision": 7,
                    "may_prepare": [],
                    "may_perform": ["web.open_write"],
                    "never_do": ["gtm.email_send", "gtm.social_publish", "webhook.dispatch"],
                    "approval_mode": "none",
                }
            }
        },
        provenance={},
    )
    session = _CharterSession(profile)
    task = _task(action="web.open_write")
    authority = ToolRuntimeAuthority(registry=registry)
    monkeypatch.setattr(runtime_authority, "activate_tenant_session", lambda *_args: None)
    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", lambda **_kwargs: None)
    monkeypatch.setattr(authority, "_validate_ability_manifest", lambda _action: None)
    monkeypatch.setattr(
        runtime_authority,
        "bind_tool_invocation_for_task",
        lambda **_kwargs: (task.metadata_json["tool_invocation"], {"skipped": True}),
    )

    result = authority.execute(
        task=task,
        context={
            "tenant_id": "tenant",
            "worker_id": "worker-1",
            "lease_id": "lease-1",
            "session_factory": lambda: session,
        },
    )

    assert result["status"] == "completed"
    assert result["output"] == {"status": "accepted"}
    assert provider_calls == ["web.open_write"]
    assert session.audit_events == []
