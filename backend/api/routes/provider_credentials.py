from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.tenant_repository import (
    TenantDeletedError,
    TenantNotFoundError,
    TenantSuspendedError,
)
from backend.services.credentials.github_oauth_connect import (
    GitHubOAuthConnectError,
    exchange_github_oauth_code,
    issue_github_oauth_authorization,
    verify_github_oauth_state,
)
from backend.services.credentials.gmail_oauth_connect import (
    GmailOAuthConnectError,
    exchange_gmail_oauth_code,
    issue_gmail_oauth_authorization,
    verify_gmail_oauth_state,
)
from backend.services.credentials.google_calendar_oauth_connect import (
    GoogleCalendarOAuthConnectError,
    exchange_google_calendar_oauth_code,
    issue_google_calendar_oauth_authorization,
    verify_google_calendar_oauth_state,
)
from backend.services.credentials.google_contacts_oauth_connect import (
    GoogleContactsOAuthConnectError,
    exchange_google_contacts_oauth_code,
    issue_google_contacts_oauth_authorization,
    verify_google_contacts_oauth_state,
)
from backend.services.credentials.google_docs_oauth_connect import (
    GoogleDocsOAuthConnectError,
    exchange_google_docs_oauth_code,
    issue_google_docs_oauth_authorization,
    verify_google_docs_oauth_state,
)
from backend.services.credentials.linkedin_oauth_connect import (
    LinkedInOAuthConnectError,
    exchange_linkedin_oauth_code,
    issue_linkedin_oauth_authorization,
    verify_linkedin_oauth_state,
)
from backend.services.credentials.management_service import (
    ProviderCredentialManagementError,
    ProviderCredentialManagementService,
    ProviderCredentialSummary,
)
from backend.services.credentials.salesforce_oauth_connect import (
    SalesforceOAuthConnectError,
    exchange_salesforce_oauth_code,
    issue_salesforce_oauth_authorization,
    verify_salesforce_oauth_state,
)
from backend.services.ui_runtime_causal_trace import (
    LINKEDIN_OAUTH_ACTION_ID,
    BrowserInteractionEvent,
    UIInteractionReceipt,
    UIInteractionTraceError,
    UIInteractionTraceService,
)
from backend.services.ui_runtime_interaction_projection import (
    UIInteractionRuntimeEvidenceProjection,
    build_ui_runtime_interaction_projection,
)

router = APIRouter(tags=["account-credentials"])


class ProviderCredentialCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=120)
    integration: Literal[
        "hubspot",
        "gmail",
        "smtp",
        "linkedin",
        "salesforce",
        "google_calendar",
        "google_contacts",
        "google_docs",
        "github",
        "social",
        "generic",
    ] = "hubspot"
    secret_value: str | None = Field(default=None, max_length=4000)
    use_platform_master_key: bool = False
    allowed_actions: list[str] = Field(default_factory=list)
    allowed_side_effect_classes: list[str] = Field(default_factory=list)
    trusted_destination_hosts: list[str] = Field(default_factory=list)

    @field_validator("secret_value")
    @classmethod
    def strip_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ProviderCredentialResponse(BaseModel):
    credential_id: str
    tenant_id: str
    provider: str
    integration: str
    credential_type: str
    enabled: bool
    revoked: bool
    allowed_actions: list[str]
    allowed_side_effect_classes: list[str]
    trusted_destination_hosts: list[str]
    uses_platform_master_key: bool
    platform_master_warning: str | None = None
    created_at: str
    updated_at: str


class ProviderCredentialCreateResponse(BaseModel):
    credential: ProviderCredentialResponse
    warning: str | None = None


class ProviderCredentialListResponse(BaseModel):
    credentials: list[ProviderCredentialResponse]


class GmailOAuthAuthorizeUrlResponse(BaseModel):
    authorization_url: str
    state: str
    redirect_uri: str


class GmailOAuthConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=4000)
    state: str = Field(min_length=1, max_length=4000)
    credential_id: str = Field(default="gmail-email", min_length=1, max_length=160)


class OAuthConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=4000)
    state: str = Field(min_length=1, max_length=4000)
    credential_id: str = Field(min_length=1, max_length=160)


def _optional_interaction_id(request: Request, header: str) -> UUID | None:
    raw = request.headers.get(header, "").strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _linkedin_interaction_ids(request: Request) -> tuple[UUID | None, UUID | None]:
    return (
        _optional_interaction_id(request, "X-Ajenda-UI-Local-Interaction-Id"),
        _optional_interaction_id(request, "X-Ajenda-UI-Interaction-Id"),
    )


def _linkedin_trace_context(
    *,
    request: Request,
    db: Session,
    tenant_id: UUID,
    actor_id: str,
) -> tuple[UIInteractionTraceService, UUID, UUID | None]:
    local_interaction_id, supplied_server_interaction_id = _linkedin_interaction_ids(request)
    trace = UIInteractionTraceService(db)
    try:
        interaction_id = trace.resolve_server_interaction(
            tenant_id=str(tenant_id),
            local_interaction_id=local_interaction_id,
            server_interaction_id=supplied_server_interaction_id,
        )
    except UIInteractionTraceError:
        # Telemetry correlation is never authority. Preserve OAuth behavior
        # while recording the server path under an independently issued ID.
        interaction_id = uuid4()
    trace.append_server_event(
        tenant_id=str(tenant_id),
        actor_id=actor_id,
        interaction_id=interaction_id,
        local_interaction_id=local_interaction_id,
        action_id=LINKEDIN_OAUTH_ACTION_ID,
        phase="api.request_received",
        outcome_code="ROUTE_MATCHED",
    )
    trace.append_server_event(
        tenant_id=str(tenant_id),
        actor_id=actor_id,
        interaction_id=interaction_id,
        local_interaction_id=local_interaction_id,
        action_id=LINKEDIN_OAUTH_ACTION_ID,
        phase="api.authentication_checked",
        outcome_code="AUTHENTICATED",
    )
    return trace, interaction_id, local_interaction_id


def _require_linkedin_oauth_permission(
    *,
    request: Request,
    db: Session,
    tenant_id: UUID,
    trace: UIInteractionTraceService,
    interaction_id: UUID,
    local_interaction_id: UUID | None,
    actor_id: str,
) -> None:
    try:
        require_route_permission(
            request=request,
            db=db,
            permission=Permission.CREDENTIALS_MANAGE,
            tenant_id=tenant_id,
        )
    except HTTPException:
        trace.append_server_event(
            tenant_id=str(tenant_id),
            actor_id=actor_id,
            interaction_id=interaction_id,
            local_interaction_id=local_interaction_id,
            action_id=LINKEDIN_OAUTH_ACTION_ID,
            phase="api.authorization_denied",
            outcome_code="CREDENTIALS_MANAGE_DENIED",
        )
        db.commit()
        raise
    trace.append_server_event(
        tenant_id=str(tenant_id),
        actor_id=actor_id,
        interaction_id=interaction_id,
        local_interaction_id=local_interaction_id,
        action_id=LINKEDIN_OAUTH_ACTION_ID,
        phase="api.authorization_checked",
        outcome_code="CREDENTIALS_MANAGE_ALLOWED",
    )


def _structured_oauth_error(
    *,
    code: str,
    message: str,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _oauth_connect_http_error(exc: Exception) -> HTTPException:
    return _structured_oauth_error(code="OAUTH_CONNECT_FAILED", message=str(exc))


def _oauth_state_claim_mismatch(code: str, message: str) -> HTTPException:
    return _structured_oauth_error(code=code, message=message)


def _map_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, ProviderCredentialManagementError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, TenantNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (TenantSuspendedError, TenantDeletedError)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    raise exc


def _actor_id(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        from backend.api.errors import authentication_required_http

        raise authentication_required_http()
    return str(principal.subject_id)


def _to_response(summary: ProviderCredentialSummary) -> ProviderCredentialResponse:
    return ProviderCredentialResponse(
        credential_id=summary.credential_id,
        tenant_id=summary.tenant_id,
        provider=summary.provider,
        integration=summary.integration,
        credential_type=summary.credential_type,
        enabled=summary.enabled,
        revoked=summary.revoked,
        allowed_actions=list(summary.allowed_actions),
        allowed_side_effect_classes=list(summary.allowed_side_effect_classes),
        trusted_destination_hosts=list(summary.trusted_destination_hosts),
        uses_platform_master_key=summary.uses_platform_master_key,
        platform_master_warning=summary.platform_master_warning,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


@router.post(
    "/provider-credentials",
    response_model=ProviderCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_provider_credential(
    body: ProviderCredentialCreateRequest,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialCreateResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    service = ProviderCredentialManagementService(db)
    try:
        result = service.register(
            tenant_id=str(tenant_id),
            credential_id=body.credential_id,
            provider=body.provider,
            integration=body.integration,
            secret_value=body.secret_value,
            use_platform_master_key=body.use_platform_master_key,
            allowed_actions=body.allowed_actions or None,
            allowed_side_effect_classes=body.allowed_side_effect_classes or None,
            trusted_destination_hosts=body.trusted_destination_hosts or None,
            actor_id=actor_id,
        )
    except (ProviderCredentialManagementError, TenantNotFoundError, TenantSuspendedError, TenantDeletedError) as exc:
        raise _map_errors(exc) from exc
    return ProviderCredentialCreateResponse(
        credential=_to_response(result.summary),
        warning=result.warning,
    )


@router.get(
    "/provider-credentials/gmail/oauth/authorize-url",
    response_model=GmailOAuthAuthorizeUrlResponse,
)
def gmail_oauth_authorize_url(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    credential_id: str = "gmail-email",
) -> GmailOAuthAuthorizeUrlResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        result = issue_gmail_oauth_authorization(
            tenant_id=str(tenant_id),
            credential_id=credential_id,
            actor_id=actor_id,
        )
    except GmailOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    return GmailOAuthAuthorizeUrlResponse(
        authorization_url=result.authorization_url,
        state=result.state,
        redirect_uri=result.redirect_uri,
    )


@router.post(
    "/provider-credentials/gmail/oauth/connect",
    response_model=ProviderCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def gmail_oauth_connect(
    body: GmailOAuthConnectRequest,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialCreateResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        claims = verify_gmail_oauth_state(body.state)
    except GmailOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    if claims.tenant_id != str(tenant_id):
        raise _oauth_state_claim_mismatch("OAUTH_STATE_TENANT_MISMATCH", "oauth state tenant mismatch") from None
    if claims.credential_id != body.credential_id.strip():
        raise _oauth_state_claim_mismatch(
            "OAUTH_STATE_CREDENTIAL_MISMATCH", "oauth state credential mismatch"
        ) from None
    if claims.actor_id != actor_id:
        raise _oauth_state_claim_mismatch("OAUTH_STATE_ACTOR_MISMATCH", "oauth state actor mismatch") from None

    try:
        secret_value = exchange_gmail_oauth_code(code=body.code, state=body.state)
        result = ProviderCredentialManagementService(db).register(
            tenant_id=str(tenant_id),
            credential_id=body.credential_id,
            provider="external_email",
            integration="gmail",
            secret_value=secret_value,
            actor_id=actor_id,
        )
    except GmailOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    except ProviderCredentialManagementError as exc:
        raise _structured_oauth_error(code="CREDENTIAL_REGISTER_FAILED", message=str(exc)) from exc
    return ProviderCredentialCreateResponse(
        credential=_to_response(result.summary),
        warning=result.warning,
    )


def _oauth_connect_response(
    *,
    service: ProviderCredentialManagementService,
    tenant_id: str,
    actor_id: str,
    credential_id: str,
    provider: str,
    integration: Literal["linkedin", "salesforce", "google_calendar", "google_contacts", "google_docs", "github"],
    secret_value: str,
    trusted_destination_hosts: list[str] | None = None,
) -> ProviderCredentialCreateResponse:
    result = service.register(
        tenant_id=tenant_id,
        credential_id=credential_id,
        provider=provider,
        integration=integration,
        secret_value=secret_value,
        trusted_destination_hosts=trusted_destination_hosts,
        actor_id=actor_id,
    )
    return ProviderCredentialCreateResponse(
        credential=_to_response(result.summary),
        warning=result.warning,
    )


@router.post(
    "/provider-credentials/runtime-interactions/events",
    response_model=UIInteractionReceipt,
    status_code=status.HTTP_201_CREATED,
)
def persist_ui_runtime_interaction_event(
    body: BrowserInteractionEvent,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> UIInteractionReceipt:
    """Persist one bounded browser observation after authentication/authorization.

    The receipt means the audit-ledger transaction committed.  It is not an
    execution grant and it contains no provider/OAuth material.
    """

    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    try:
        return UIInteractionTraceService(db).accept_browser_event(
            tenant_id=str(tenant_id),
            actor_id=_actor_id(request),
            event=body,
        )
    except UIInteractionTraceError as exc:
        raise _structured_oauth_error(
            code="UI_INTERACTION_REJECTED", message=str(exc), status_code=status.HTTP_409_CONFLICT
        ) from exc


@router.get(
    "/provider-credentials/linkedin/oauth/runtime-evidence/{interaction_id}",
    response_model=UIInteractionRuntimeEvidenceProjection,
)
def get_linkedin_oauth_runtime_evidence(
    interaction_id: UUID,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> UIInteractionRuntimeEvidenceProjection:
    """Read-only, tenant-scoped projection of one LinkedIn OAuth interaction."""

    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    events = AuditEventRepository(db).list_for_runtime_interaction_for_tenant(
        tenant_id=str(tenant_id), interaction_id=str(interaction_id)
    )
    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime interaction evidence not found")
    return build_ui_runtime_interaction_projection(
        interaction_id=interaction_id,
        tenant_id=str(tenant_id),
        audit_events=events,
    )


@router.get(
    "/provider-credentials/linkedin/oauth/authorize-url",
    response_model=GmailOAuthAuthorizeUrlResponse,
)
def linkedin_oauth_authorize_url(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    credential_id: str = "linkedin-read",
) -> GmailOAuthAuthorizeUrlResponse:
    actor_id = _actor_id(request)
    trace, interaction_id, local_interaction_id = _linkedin_trace_context(
        request=request,
        db=db,
        tenant_id=tenant_id,
        actor_id=actor_id,
    )
    _require_linkedin_oauth_permission(
        request=request,
        db=db,
        tenant_id=tenant_id,
        trace=trace,
        interaction_id=interaction_id,
        local_interaction_id=local_interaction_id,
        actor_id=actor_id,
    )
    try:
        result = issue_linkedin_oauth_authorization(
            tenant_id=str(tenant_id),
            credential_id=credential_id,
            actor_id=actor_id,
            interaction_id=str(interaction_id),
        )
    except LinkedInOAuthConnectError as exc:
        trace.append_server_event(
            tenant_id=str(tenant_id),
            actor_id=actor_id,
            interaction_id=interaction_id,
            local_interaction_id=local_interaction_id,
            action_id=LINKEDIN_OAUTH_ACTION_ID,
            phase="oauth.authorization_failed",
            outcome_code="OAUTH_AUTHORIZE_CONFIGURATION_FAILED",
        )
        db.commit()
        raise _oauth_connect_http_error(exc) from exc
    trace.append_server_event(
        tenant_id=str(tenant_id),
        actor_id=actor_id,
        interaction_id=interaction_id,
        local_interaction_id=local_interaction_id,
        action_id=LINKEDIN_OAUTH_ACTION_ID,
        phase="oauth.authorization_url_issued",
        outcome_code="OAUTH_AUTHORIZE_URL_ISSUED",
    )
    # A returned authorization URL is paired with durable API-side evidence.
    db.commit()
    return GmailOAuthAuthorizeUrlResponse(
        authorization_url=result.authorization_url,
        state=result.state,
        redirect_uri=result.redirect_uri,
    )


@router.post(
    "/provider-credentials/linkedin/oauth/connect",
    response_model=ProviderCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def linkedin_oauth_connect(
    body: OAuthConnectRequest,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialCreateResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        claims = verify_linkedin_oauth_state(body.state)
    except LinkedInOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    if claims.tenant_id != str(tenant_id):
        raise _oauth_state_claim_mismatch("OAUTH_STATE_TENANT_MISMATCH", "oauth state tenant mismatch") from None
    if claims.credential_id != body.credential_id.strip():
        raise _oauth_state_claim_mismatch(
            "OAUTH_STATE_CREDENTIAL_MISMATCH", "oauth state credential mismatch"
        ) from None
    if claims.actor_id != actor_id:
        raise _oauth_state_claim_mismatch("OAUTH_STATE_ACTOR_MISMATCH", "oauth state actor mismatch") from None

    try:
        interaction_id = UUID(claims.interaction_id) if claims.interaction_id else None
    except ValueError:
        interaction_id = None
    # Callback requests do not carry browser headers.  The signed state only
    # carries an opaque interaction identifier, never OAuth material.
    trace = UIInteractionTraceService(db)
    if interaction_id is not None:
        trace.append_server_event(
            tenant_id=str(tenant_id),
            actor_id=actor_id,
            interaction_id=interaction_id,
            local_interaction_id=None,
            action_id=LINKEDIN_OAUTH_ACTION_ID,
            phase="api.callback_received",
            outcome_code="OAUTH_CALLBACK_VALIDATED",
        )
        trace.append_server_event(
            tenant_id=str(tenant_id),
            actor_id=actor_id,
            interaction_id=interaction_id,
            local_interaction_id=None,
            action_id=LINKEDIN_OAUTH_ACTION_ID,
            phase="api.authorization_checked",
            outcome_code="CREDENTIALS_MANAGE_ALLOWED",
        )

    try:
        secret_value = exchange_linkedin_oauth_code(code=body.code, state=body.state)
        response = _oauth_connect_response(
            service=ProviderCredentialManagementService(db),
            tenant_id=str(tenant_id),
            actor_id=actor_id,
            credential_id=body.credential_id,
            provider="external_read_provider",
            integration="linkedin",
            secret_value=secret_value,
        )
        if interaction_id is not None:
            trace.append_server_event(
                tenant_id=str(tenant_id),
                actor_id=actor_id,
                interaction_id=interaction_id,
                local_interaction_id=None,
                action_id=LINKEDIN_OAUTH_ACTION_ID,
                phase="oauth.credential_persisted",
                outcome_code="CREDENTIAL_REGISTERED",
            )
        db.commit()
        return response
    except LinkedInOAuthConnectError as exc:
        if interaction_id is not None:
            trace.append_server_event(
                tenant_id=str(tenant_id),
                actor_id=actor_id,
                interaction_id=interaction_id,
                local_interaction_id=None,
                action_id=LINKEDIN_OAUTH_ACTION_ID,
                phase="oauth.exchange_failed",
                outcome_code="OAUTH_CODE_EXCHANGE_FAILED",
            )
            db.commit()
        raise _oauth_connect_http_error(exc) from exc
    except ProviderCredentialManagementError as exc:
        if interaction_id is not None:
            trace.append_server_event(
                tenant_id=str(tenant_id),
                actor_id=actor_id,
                interaction_id=interaction_id,
                local_interaction_id=None,
                action_id=LINKEDIN_OAUTH_ACTION_ID,
                phase="oauth.exchange_failed",
                outcome_code="CREDENTIAL_REGISTER_FAILED",
            )
            db.commit()
        raise _structured_oauth_error(code="CREDENTIAL_REGISTER_FAILED", message=str(exc)) from exc


@router.get(
    "/provider-credentials/salesforce/oauth/authorize-url",
    response_model=GmailOAuthAuthorizeUrlResponse,
)
def salesforce_oauth_authorize_url(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    credential_id: str = "salesforce-read",
) -> GmailOAuthAuthorizeUrlResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        result = issue_salesforce_oauth_authorization(
            tenant_id=str(tenant_id),
            credential_id=credential_id,
            actor_id=actor_id,
        )
    except SalesforceOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    return GmailOAuthAuthorizeUrlResponse(
        authorization_url=result.authorization_url,
        state=result.state,
        redirect_uri=result.redirect_uri,
    )


@router.post(
    "/provider-credentials/salesforce/oauth/connect",
    response_model=ProviderCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def salesforce_oauth_connect(
    body: OAuthConnectRequest,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialCreateResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        claims = verify_salesforce_oauth_state(body.state)
    except SalesforceOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    if claims.tenant_id != str(tenant_id):
        raise _oauth_state_claim_mismatch("OAUTH_STATE_TENANT_MISMATCH", "oauth state tenant mismatch") from None
    if claims.credential_id != body.credential_id.strip():
        raise _oauth_state_claim_mismatch(
            "OAUTH_STATE_CREDENTIAL_MISMATCH", "oauth state credential mismatch"
        ) from None
    if claims.actor_id != actor_id:
        raise _oauth_state_claim_mismatch("OAUTH_STATE_ACTOR_MISMATCH", "oauth state actor mismatch") from None

    try:
        connect_secret = exchange_salesforce_oauth_code(code=body.code, state=body.state)
        return _oauth_connect_response(
            service=ProviderCredentialManagementService(db),
            tenant_id=str(tenant_id),
            actor_id=actor_id,
            credential_id=body.credential_id,
            provider="external_read_provider",
            integration="salesforce",
            secret_value=connect_secret.secret_value,
            trusted_destination_hosts=list(connect_secret.trusted_destination_hosts),
        )
    except SalesforceOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    except ProviderCredentialManagementError as exc:
        raise _structured_oauth_error(code="CREDENTIAL_REGISTER_FAILED", message=str(exc)) from exc


@router.get(
    "/provider-credentials/google-calendar/oauth/authorize-url",
    response_model=GmailOAuthAuthorizeUrlResponse,
)
def google_calendar_oauth_authorize_url(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    credential_id: str = "google-calendar-read",
) -> GmailOAuthAuthorizeUrlResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        result = issue_google_calendar_oauth_authorization(
            tenant_id=str(tenant_id),
            credential_id=credential_id,
            actor_id=actor_id,
        )
    except GoogleCalendarOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    return GmailOAuthAuthorizeUrlResponse(
        authorization_url=result.authorization_url,
        state=result.state,
        redirect_uri=result.redirect_uri,
    )


@router.post(
    "/provider-credentials/google-calendar/oauth/connect",
    response_model=ProviderCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def google_calendar_oauth_connect(
    body: OAuthConnectRequest,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialCreateResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        claims = verify_google_calendar_oauth_state(body.state)
    except GoogleCalendarOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    if claims.tenant_id != str(tenant_id):
        raise _oauth_state_claim_mismatch("OAUTH_STATE_TENANT_MISMATCH", "oauth state tenant mismatch") from None
    if claims.credential_id != body.credential_id.strip():
        raise _oauth_state_claim_mismatch(
            "OAUTH_STATE_CREDENTIAL_MISMATCH", "oauth state credential mismatch"
        ) from None
    if claims.actor_id != actor_id:
        raise _oauth_state_claim_mismatch("OAUTH_STATE_ACTOR_MISMATCH", "oauth state actor mismatch") from None

    try:
        secret_value = exchange_google_calendar_oauth_code(code=body.code, state=body.state)
        return _oauth_connect_response(
            service=ProviderCredentialManagementService(db),
            tenant_id=str(tenant_id),
            actor_id=actor_id,
            credential_id=body.credential_id,
            provider="external_read_provider",
            integration="google_calendar",
            secret_value=secret_value,
        )
    except GoogleCalendarOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    except ProviderCredentialManagementError as exc:
        raise _structured_oauth_error(code="CREDENTIAL_REGISTER_FAILED", message=str(exc)) from exc


@router.get(
    "/provider-credentials/google-contacts/oauth/authorize-url",
    response_model=GmailOAuthAuthorizeUrlResponse,
)
def google_contacts_oauth_authorize_url(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    credential_id: str = "google-contacts-read",
) -> GmailOAuthAuthorizeUrlResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        result = issue_google_contacts_oauth_authorization(
            tenant_id=str(tenant_id),
            credential_id=credential_id,
            actor_id=actor_id,
        )
    except GoogleContactsOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    return GmailOAuthAuthorizeUrlResponse(
        authorization_url=result.authorization_url,
        state=result.state,
        redirect_uri=result.redirect_uri,
    )


@router.post(
    "/provider-credentials/google-contacts/oauth/connect",
    response_model=ProviderCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def google_contacts_oauth_connect(
    body: OAuthConnectRequest,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialCreateResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        claims = verify_google_contacts_oauth_state(body.state)
    except GoogleContactsOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    if claims.tenant_id != str(tenant_id):
        raise _oauth_state_claim_mismatch("OAUTH_STATE_TENANT_MISMATCH", "oauth state tenant mismatch") from None
    if claims.credential_id != body.credential_id.strip():
        raise _oauth_state_claim_mismatch(
            "OAUTH_STATE_CREDENTIAL_MISMATCH", "oauth state credential mismatch"
        ) from None
    if claims.actor_id != actor_id:
        raise _oauth_state_claim_mismatch("OAUTH_STATE_ACTOR_MISMATCH", "oauth state actor mismatch") from None

    try:
        secret_value = exchange_google_contacts_oauth_code(code=body.code, state=body.state)
        return _oauth_connect_response(
            service=ProviderCredentialManagementService(db),
            tenant_id=str(tenant_id),
            actor_id=actor_id,
            credential_id=body.credential_id,
            provider="external_read_provider",
            integration="google_contacts",
            secret_value=secret_value,
        )
    except GoogleContactsOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    except ProviderCredentialManagementError as exc:
        raise _structured_oauth_error(code="CREDENTIAL_REGISTER_FAILED", message=str(exc)) from exc


@router.get(
    "/provider-credentials/google-docs/oauth/authorize-url",
    response_model=GmailOAuthAuthorizeUrlResponse,
)
def google_docs_oauth_authorize_url(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    credential_id: str = "google-docs",
) -> GmailOAuthAuthorizeUrlResponse:
    require_route_permission(request=request, db=db, permission=Permission.CREDENTIALS_MANAGE, tenant_id=tenant_id)
    actor_id = _actor_id(request)
    try:
        result = issue_google_docs_oauth_authorization(
            tenant_id=str(tenant_id), credential_id=credential_id, actor_id=actor_id
        )
    except GoogleDocsOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    return GmailOAuthAuthorizeUrlResponse(
        authorization_url=result.authorization_url, state=result.state, redirect_uri=result.redirect_uri
    )


@router.post(
    "/provider-credentials/google-docs/oauth/connect",
    response_model=ProviderCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def google_docs_oauth_connect(
    body: OAuthConnectRequest,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialCreateResponse:
    require_route_permission(request=request, db=db, permission=Permission.CREDENTIALS_MANAGE, tenant_id=tenant_id)
    actor_id = _actor_id(request)
    try:
        claims = verify_google_docs_oauth_state(body.state)
    except GoogleDocsOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    if claims.tenant_id != str(tenant_id):
        raise _oauth_state_claim_mismatch("OAUTH_STATE_TENANT_MISMATCH", "oauth state tenant mismatch") from None
    if claims.credential_id != body.credential_id.strip():
        raise _oauth_state_claim_mismatch(
            "OAUTH_STATE_CREDENTIAL_MISMATCH", "oauth state credential mismatch"
        ) from None
    if claims.actor_id != actor_id:
        raise _oauth_state_claim_mismatch("OAUTH_STATE_ACTOR_MISMATCH", "oauth state actor mismatch") from None
    try:
        secret_value = exchange_google_docs_oauth_code(code=body.code, state=body.state)
        return _oauth_connect_response(
            service=ProviderCredentialManagementService(db),
            tenant_id=str(tenant_id),
            actor_id=actor_id,
            credential_id=body.credential_id,
            provider="external_read_provider",
            integration="google_docs",
            secret_value=secret_value,
        )
    except GoogleDocsOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    except ProviderCredentialManagementError as exc:
        raise _structured_oauth_error(code="CREDENTIAL_REGISTER_FAILED", message=str(exc)) from exc


@router.get(
    "/provider-credentials/github/oauth/authorize-url",
    response_model=GmailOAuthAuthorizeUrlResponse,
)
def github_oauth_authorize_url(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    credential_id: str = "github-read",
) -> GmailOAuthAuthorizeUrlResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        result = issue_github_oauth_authorization(
            tenant_id=str(tenant_id),
            credential_id=credential_id,
            actor_id=actor_id,
        )
    except GitHubOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    return GmailOAuthAuthorizeUrlResponse(
        authorization_url=result.authorization_url,
        state=result.state,
        redirect_uri=result.redirect_uri,
    )


@router.post(
    "/provider-credentials/github/oauth/connect",
    response_model=ProviderCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def github_oauth_connect(
    body: OAuthConnectRequest,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialCreateResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        claims = verify_github_oauth_state(body.state)
    except GitHubOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    if claims.tenant_id != str(tenant_id):
        raise _oauth_state_claim_mismatch("OAUTH_STATE_TENANT_MISMATCH", "oauth state tenant mismatch") from None
    if claims.credential_id != body.credential_id.strip():
        raise _oauth_state_claim_mismatch(
            "OAUTH_STATE_CREDENTIAL_MISMATCH", "oauth state credential mismatch"
        ) from None
    if claims.actor_id != actor_id:
        raise _oauth_state_claim_mismatch("OAUTH_STATE_ACTOR_MISMATCH", "oauth state actor mismatch") from None

    try:
        secret_value = exchange_github_oauth_code(code=body.code, state=body.state)
        return _oauth_connect_response(
            service=ProviderCredentialManagementService(db),
            tenant_id=str(tenant_id),
            actor_id=actor_id,
            credential_id=body.credential_id,
            provider="external_read_provider",
            integration="github",
            secret_value=secret_value,
        )
    except GitHubOAuthConnectError as exc:
        raise _oauth_connect_http_error(exc) from exc
    except ProviderCredentialManagementError as exc:
        raise _structured_oauth_error(code="CREDENTIAL_REGISTER_FAILED", message=str(exc)) from exc


@router.get("/provider-credentials", response_model=ProviderCredentialListResponse)
def list_provider_credentials(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialListResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_READ,
        tenant_id=tenant_id,
    )
    _actor_id(request)
    summaries = ProviderCredentialManagementService(db).list_credentials(tenant_id=str(tenant_id))
    return ProviderCredentialListResponse(credentials=[_to_response(item) for item in summaries])


@router.post(
    "/provider-credentials/{credential_id}/revoke",
    response_model=ProviderCredentialResponse,
)
def revoke_provider_credential(
    credential_id: str,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        summary = ProviderCredentialManagementService(db).revoke(
            tenant_id=str(tenant_id),
            credential_id=credential_id,
            actor_id=actor_id,
        )
    except (ProviderCredentialManagementError, ValueError) as exc:
        raise _map_errors(exc) from exc
    return _to_response(summary)


@router.delete(
    "/provider-credentials/{credential_id}",
    response_model=ProviderCredentialResponse,
)
def delete_provider_credential(
    credential_id: str,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProviderCredentialResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.CREDENTIALS_MANAGE,
        tenant_id=tenant_id,
    )
    actor_id = _actor_id(request)
    try:
        summary = ProviderCredentialManagementService(db).delete(
            tenant_id=str(tenant_id),
            credential_id=credential_id,
            actor_id=actor_id,
        )
    except (ProviderCredentialManagementError, ValueError) as exc:
        raise _map_errors(exc) from exc
    return _to_response(summary)
