from __future__ import annotations

from backend.app.config import Settings, get_settings


class PlatformMasterNotConfiguredError(ValueError):
    """Raised when a platform master credential cannot be resolved."""


def resolve_platform_master_secret(
    *,
    provider: str,
    integration: str,
    settings: Settings | None = None,
) -> str:
    resolved_settings = settings or get_settings()
    normalized_provider = provider.strip().lower()
    normalized_integration = integration.strip().lower()

    if normalized_provider == "external_crm":
        if not resolved_settings.hubspot_platform_master_ready:
            raise PlatformMasterNotConfiguredError("platform master HubSpot key is not configured")
        return str(resolved_settings.hubspot_platform_master_key).strip()

    if normalized_provider == "external_email" and normalized_integration == "smtp":
        if not resolved_settings.email_platform_master_ready:
            raise PlatformMasterNotConfiguredError("platform master email SMTP secret is not configured")
        return str(resolved_settings.email_platform_smtp_secret).strip()

    raise PlatformMasterNotConfiguredError(
        f"platform master resolution is not supported for provider={provider!r} integration={integration!r}"
    )


def platform_master_ready_for(
    *,
    provider: str,
    integration: str,
    settings: Settings | None = None,
) -> bool:
    try:
        resolve_platform_master_secret(provider=provider, integration=integration, settings=settings)
    except PlatformMasterNotConfiguredError:
        return False
    return True
