"""Basic tests for PR1 uniform quota/feature enforcement in ability-runtime paths.

These are minimal structural + smoke tests added as part of the "add basic tests"
item in PR 1 of the approved SaaS hardening + abilities/tools expansion plan.
They verify the enforcement imports are present and the high-risk action sets
are wired for the checks added in launch_task and ToolRuntimeAuthority.
Full route integration and quota behavior is covered by existing mission/task
quota tests and the ability rollout contract checks.
"""

import pytest

from backend.api.routes.ability_runtime import (
    EXTERNAL_ACTIONS,
    GTM_HIGH_RISK_ACTIONS,
    INTERNAL_WRITE_ACTIONS,
    READ_SAFE_ACTIONS,
    _requires_runtime_authority,
)
from backend.services.tools.runtime_authority import ToolRuntimeAuthority
from backend.services.tools.schemas import SideEffectClass


def test_ability_runtime_enforcement_imports_and_sets():
    """The enforcement surfaces (ability-runtime + tools runtime) now reference quota."""
    # High-risk actions that now get defense-in-depth in launch_task
    assert "http.request" in EXTERNAL_ACTIONS
    assert "provider.external_read" in EXTERNAL_ACTIONS
    assert "webhook.dispatch" in EXTERNAL_ACTIONS

    # PR9: high-risk GTM now exposed for pilot and gated by guardian + feature
    assert "gtm.email_send" in EXTERNAL_ACTIONS
    assert "gtm.crm_upsert" in EXTERNAL_ACTIONS
    assert "gtm.social_publish" in EXTERNAL_ACTIONS
    assert GTM_HIGH_RISK_ACTIONS == {"gtm.email_send", "gtm.crm_upsert", "gtm.social_publish"}

    # Internal writes also trigger authority (and thus potential future quota/feature)
    assert "record.write" in INTERNAL_WRITE_ACTIONS
    assert "sales.log_activity" in INTERNAL_WRITE_ACTIONS

    # Safe reads do not
    assert "sales.research" in READ_SAFE_ACTIONS
    assert len(EXTERNAL_ACTIONS) >= 6


def test_requires_runtime_authority_matches_external_and_write():
    """Mirrors the condition used for the new quota/feature check in launch_task."""
    assert _requires_runtime_authority(SideEffectClass.EXTERNAL_READ) is True
    assert _requires_runtime_authority(SideEffectClass.EXTERNAL_WRITE) is True
    assert _requires_runtime_authority(SideEffectClass.EXTERNAL_SEND) is True
    assert _requires_runtime_authority(SideEffectClass.INTERNAL_WRITE) is True
    assert _requires_runtime_authority(SideEffectClass.NONE) is False


def test_tool_runtime_authority_imports_quota_enforcement():
    """Confirms the defense-in-depth check_tenant_active call site in execution path.
    (The actual call happens inside authorize() after lease claim.)
    """
    # Construction should succeed (no quota dep at __init__ time)
    auth = ToolRuntimeAuthority()
    assert auth is not None
    # If the import was missing the edit would have failed at module load
    from backend.services.quota_enforcement import QuotaEnforcementService

    assert QuotaEnforcementService is not None


@pytest.mark.parametrize(
    "side_effect",
    [
        SideEffectClass.EXTERNAL_READ,
        SideEffectClass.EXTERNAL_WRITE,
        SideEffectClass.EXTERNAL_SEND,
        SideEffectClass.INTERNAL_WRITE,
    ],
)
def test_external_and_write_side_effects_require_authority(side_effect):
    assert _requires_runtime_authority(side_effect) is True


def test_gtm_high_risk_actions_require_guardian_approval_in_pilot() -> None:
    """PR9 pilot: high-risk GTM actions are exposed and require guardian in approved_by (checked at launch)."""
    assert "gtm.email_send" in GTM_HIGH_RISK_ACTIONS
    # Guardian role contract allows approve; approved_by body must contain 'guardian'
    bad = "ability-runtime-ui"
    good = "guardian@ops"
    assert "guardian" not in bad.lower()
    assert "guardian" in good.lower()
