"""Governed public page, browser-session, and open-write handlers."""

from typing import Any

from backend.services.internet import InternetAccessMode, fetch_public_page
from backend.services.internet.browser_session import browser_session_as_dict, run_browser_session
from backend.services.internet.open_write import execute_open_write
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
    WebBrowserSessionInput,
    WebOpenWriteInput,
    WebPageReadInput,
)


def web_page_read(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = WebPageReadInput.model_validate(invocation.input)
    snapshot = fetch_public_page(
        url_or_domain=payload.url,
        timeout_seconds=payload.timeout_seconds,
        action_name="web.page_read",
    )
    output = snapshot.as_dict()
    output["access_mode"] = InternetAccessMode.PAGE_READ.value
    output["related_modes"] = {
        "browser_session": "web.browser_session (flag AJENDA_BROWSER_SESSION_ENABLED)",
        "open_write": "web.open_write (flag AJENDA_OPEN_WRITE_ENABLED)",
    }
    real = bool(output.get("real"))
    title = output.get("title") or ""
    summary = (
        f"Read public page {output.get('url')} (status={output.get('status_code')}, title={title[:80]!r}, real={real})."
        if real
        else f"Public page read failed for {payload.url}: {output.get('error') or 'unknown error'}."
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.web.page_read",
        action_name="web.page_read",
        tool_provider="ajenda_internet",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={
            "url": output.get("url"),
            "status_code": output.get("status_code"),
            "title": output.get("title"),
            "real": real,
            "access_mode": InternetAccessMode.PAGE_READ.value,
            "browser_ready": False,
        },
        confidence=0.9 if real else 0.4,
        limitations=[
            "single HTTPS GET only — no JavaScript execution",
            "redirects disabled by NetworkEgressAuthority",
            "response body bounded; HTML extraction is best-effort",
        ],
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ToolRuntimeAuthority -> ActionRegistry",
            "network_egress_authority": "backend.services.network_egress.NetworkEgressAuthority",
            "internet_access": "backend.services.internet.page_read",
            "access_mode": InternetAccessMode.PAGE_READ.value,
        },
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action="web.page_read",
        provider="ajenda_internet",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=0.9 if real else 0.4,
    )

def web_browser_session(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = WebBrowserSessionInput.model_validate(invocation.input)
    snapshot = run_browser_session(
        url_or_domain=payload.url,
        timeout_seconds=payload.timeout_seconds,
        wait_until=payload.wait_until,
        extract_text=payload.extract_text,
        allowed_origins=payload.allowed_origins,
        commands=[command.model_dump(exclude_none=True) for command in payload.commands],
        observation_requirements=[item.model_dump(exclude_none=True) for item in payload.observation_requirements],
    )
    output = browser_session_as_dict(snapshot)
    real = bool(output.get("real"))
    title = output.get("title") or ""
    raw_extraction: object = output.get("extraction")
    extraction: dict[str, Any] = raw_extraction if isinstance(raw_extraction, dict) else {}
    output["web_page_observation"] = {
        "source_url": payload.url,
        "final_url": output.get("url") if real else None,
        "title": title or None,
        "extracted_observations": extraction.get("observation_requirements") or [],
        "observation_timestamp": extraction.get("observation_timestamp"),
        "browser_trace": extraction.get("steps") or [],
        "blocked_requests": extraction.get("blocked_samples") or [],
        "observation_satisfied": extraction.get("observation_satisfied") is True,
        "network_provenance": {
            "request_vetting": extraction.get("request_vetting"),
            "dns_pin": extraction.get("dns_pin"),
            "dns_pinned_hosts": extraction.get("dns_pinned_hosts") or [],
            "allowed_hosts": extraction.get("allowed_hosts") or [],
            "engine": extraction.get("engine"),
            "ephemeral_context": extraction.get("ephemeral_context") is True,
        },
    }
    if output.get("error"):
        output["web_page_observation"]["error"] = output["error"]
    summary = (
        f"Browser session {output.get('url')} (status={output.get('status_code')}, title={title[:80]!r}, real={real})."
        if real
        else f"Browser session failed for {payload.url}: {output.get('error') or 'unknown error'}."
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.web.browser_session",
        action_name="web.browser_session",
        tool_provider="ajenda_internet",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={
            "url": output.get("url"),
            "status_code": output.get("status_code"),
            "title": output.get("title"),
            "real": real,
            "access_mode": InternetAccessMode.BROWSER_SESSION.value,
            "ephemeral": True,
            "browser_ready": output.get("browser_ready"),
            "observation_requirements": extraction.get("observation_requirements", []),
            "observation_satisfied": extraction.get("observation_satisfied", False),
            "browser_trace": extraction.get("steps", []),
            "blocked_requests": extraction.get("blocked_samples", []),
            "network_provenance": output["web_page_observation"]["network_provenance"],
        },
        confidence=0.85 if real else 0.35,
        limitations=[
            "requires AJENDA_BROWSER_SESSION_ENABLED=true",
            "ephemeral Playwright context destroyed after each call",
            "URL vetted by NetworkEgressAuthority before navigation",
            "bounded read-only browser contract; no authentication or external writes",
        ],
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ToolRuntimeAuthority -> ActionRegistry",
            "internet_access": "backend.services.internet.browser_session",
            "access_mode": InternetAccessMode.BROWSER_SESSION.value,
            "tenant_isolation": "single_use_context",
        },
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action="web.browser_session",
        provider="ajenda_internet",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=0.85 if real else 0.35,
    )

def web_open_write(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = WebOpenWriteInput.model_validate(invocation.input)
    # Rate limit is tenant-scoped inside execute_open_write (never worker_id).
    result = execute_open_write(
        tenant_id=context.tenant_id,
        url=payload.url,
        method=payload.method,
        idempotency_key=payload.idempotency_key,
        json_body=payload.json_body,
        body_text=payload.body_text,
        headers=payload.headers,
        timeout_seconds=payload.timeout_seconds,
        session_factory=context.session_factory,
    )
    output = result.as_dict()
    output["idempotency_key_present"] = True
    real = bool(output.get("real"))
    summary = (
        f"Open write {payload.method} {payload.url} status={output.get('status_code')} real={real}."
        if real
        else f"Open write blocked/failed for {payload.url}: {output.get('error') or 'unknown error'}."
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.web.open_write",
        action_name="web.open_write",
        tool_provider="ajenda_internet",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={
            "url": output.get("url"),
            "method": output.get("method"),
            "status_code": output.get("status_code"),
            "real": real,
            "access_mode": InternetAccessMode.OPEN_WRITE.value,
            "rate_limit_remaining": output.get("rate_limit_remaining"),
        },
        confidence=0.8 if real else 0.3,
        limitations=[
            "requires AJENDA_OPEN_WRITE_ENABLED=true",
            "per-tenant hourly rate limit (AJENDA_OPEN_WRITE_MAX_PER_HOUR)",
            "idempotency_key required",
            "HTTPS-only via NetworkEgressAuthority; no credential headers",
        ],
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ToolRuntimeAuthority -> ActionRegistry",
            "network_egress_authority": "backend.services.network_egress.NetworkEgressAuthority",
            "internet_access": "backend.services.internet.open_write",
            "access_mode": InternetAccessMode.OPEN_WRITE.value,
        },
        side_effect_class=SideEffectClass.EXTERNAL_WRITE,
    )
    return ActionResult(
        action="web.open_write",
        provider="ajenda_internet",
        side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=0.8 if real else 0.3,
    )
