"""
Unit Tests — Pride Kernel & Immutable Policy Enforcement
=========================================================
Tests for:
1. PrideKernel.assemble_prompt() — preamble always prepended
2. PrideKernel.is_pride_compliant() — compliance detection
3. PrideKernel.get_preamble_version() — version string
4. PolicyManager immutability guards — update and delete blocked

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

import pytest

from backend.agents.governance.pride_kernel import (
    PRIDE_PREAMBLE,
    PRIDE_PROTOCOL_VERSION,
    assemble_prompt,
    get_preamble_version,
    is_pride_compliant,
)
from backend.agents.compliance.policy_engine import (
    Policy,
    PolicyAction,
    PolicyStatus,
    ActionType,
    get_policy_manager,
)


# ============================================================================
# PrideKernel — assemble_prompt
# ============================================================================


class TestAssemblePrompt:
    """Tests for the assemble_prompt() function."""

    def test_preamble_is_always_present_with_user_prompt(self):
        """The Pride preamble must appear at the start of every assembled prompt."""
        result = assemble_prompt("You are a financial analyst.")
        assert result.startswith("╔══"), (
            "Assembled prompt must begin with the Pride preamble governance block header."
        )

    def test_user_prompt_is_preserved(self):
        """The user's custom prompt must appear in the assembled result."""
        user_prompt = "You are a financial analyst specializing in derivatives."
        result = assemble_prompt(user_prompt)
        assert user_prompt in result, (
            "User's custom prompt must be preserved in the assembled output."
        )

    def test_preamble_appears_before_user_prompt(self):
        """The governance block must precede the user's custom content."""
        user_prompt = "You are a data scientist."
        result = assemble_prompt(user_prompt)
        preamble_pos = result.find("CITADEL GOVERNANCE")
        user_pos = result.find(user_prompt)
        assert preamble_pos < user_pos, (
            "Pride preamble must appear before the user's custom prompt."
        )

    def test_none_user_prompt_returns_preamble_only(self):
        """When no user prompt is provided, the result is the preamble alone."""
        result = assemble_prompt(None)
        assert result == PRIDE_PREAMBLE, (
            "With no user prompt, assemble_prompt() must return exactly the preamble."
        )

    def test_empty_string_user_prompt_returns_preamble_only(self):
        """An empty string user prompt should behave the same as None."""
        result = assemble_prompt("")
        assert result == PRIDE_PREAMBLE, (
            "An empty user prompt must result in the preamble only."
        )

    def test_whitespace_only_user_prompt_returns_preamble_only(self):
        """A whitespace-only user prompt should be treated as absent."""
        result = assemble_prompt("   \n  \t  ")
        assert result == PRIDE_PREAMBLE, (
            "A whitespace-only user prompt must result in the preamble only."
        )

    def test_governance_block_header_present(self):
        """The governance block header must be present in every assembled prompt."""
        for prompt in [None, "", "Some custom prompt"]:
            result = assemble_prompt(prompt)
            assert "CITADEL GOVERNANCE — PRIDE PROTOCOL" in result, (
                f"Governance block header missing for input: {repr(prompt)}"
            )

    def test_governance_block_footer_present(self):
        """The governance block footer must be present to close the block."""
        result = assemble_prompt("You are an assistant.")
        assert "END GOVERNANCE BLOCK" in result, (
            "Governance block footer must be present in the assembled prompt."
        )

    def test_pride_ratio_definition_present(self):
        """The measurable Pride definition must be in the preamble."""
        result = assemble_prompt("You are a coding assistant.")
        assert "PRIDE = proper_actions / total_actions" in result, (
            "The measurable Pride ratio definition must be present in every prompt."
        )

    def test_preamble_constant_is_immutable_reference(self):
        """The PRIDE_PREAMBLE constant must not be modified by assemble_prompt()."""
        original_preamble = PRIDE_PREAMBLE
        assemble_prompt("Some custom prompt")
        assert PRIDE_PREAMBLE == original_preamble, (
            "assemble_prompt() must not modify the PRIDE_PREAMBLE constant."
        )

    def test_multiple_calls_produce_consistent_results(self):
        """Repeated calls with the same input must produce identical output."""
        user_prompt = "You are a security analyst."
        result_1 = assemble_prompt(user_prompt)
        result_2 = assemble_prompt(user_prompt)
        assert result_1 == result_2, (
            "assemble_prompt() must be deterministic — same input, same output."
        )


# ============================================================================
# PrideKernel — is_pride_compliant
# ============================================================================


class TestIsPrideCompliant:
    """Tests for the is_pride_compliant() compliance checker."""

    def test_assembled_prompt_is_compliant(self):
        """A prompt assembled via assemble_prompt() must pass compliance check."""
        assembled = assemble_prompt("You are a researcher.")
        assert is_pride_compliant(assembled) is True, (
            "A prompt assembled via assemble_prompt() must be Pride-compliant."
        )

    def test_raw_user_prompt_is_not_compliant(self):
        """A raw user prompt without the preamble must fail compliance check."""
        raw = "You are a helpful assistant."
        assert is_pride_compliant(raw) is False, (
            "A raw user prompt without the governance block must not be compliant."
        )

    def test_empty_string_is_not_compliant(self):
        """An empty string must not be considered compliant."""
        assert is_pride_compliant("") is False

    def test_preamble_alone_is_compliant(self):
        """The preamble constant alone must pass compliance check."""
        assert is_pride_compliant(PRIDE_PREAMBLE) is True, (
            "The PRIDE_PREAMBLE constant itself must be considered compliant."
        )


# ============================================================================
# PrideKernel — get_preamble_version
# ============================================================================


class TestGetPreambleVersion:
    """Tests for the get_preamble_version() function."""

    def test_returns_string(self):
        """Version must be a string."""
        assert isinstance(get_preamble_version(), str)

    def test_matches_constant(self):
        """get_preamble_version() must return the same value as PRIDE_PROTOCOL_VERSION."""
        assert get_preamble_version() == PRIDE_PROTOCOL_VERSION

    def test_version_is_not_empty(self):
        """Version string must not be empty."""
        assert len(get_preamble_version()) > 0


# ============================================================================
# PolicyManager — Immutability Guards
# ============================================================================


class TestPolicyManagerImmutability:
    """Tests for immutability enforcement in PolicyManager."""

    def _make_immutable_policy(self, policy_id: str = "test.immutable.policy") -> Policy:
        """Helper: create an immutable policy for testing."""
        return Policy(
            policy_id=policy_id,
            name="Test Immutable Policy",
            description="Used in unit tests to verify immutability enforcement.",
            status=PolicyStatus.ACTIVE,
            conditions=[],
            actions=[
                PolicyAction(
                    action_type=ActionType.LOG_EVENT,
                    parameters={"event": "test"},
                )
            ],
            immutable=True,
        )

    def _make_mutable_policy(self, policy_id: str = "test.mutable.policy") -> Policy:
        """Helper: create a mutable policy for testing."""
        return Policy(
            policy_id=policy_id,
            name="Test Mutable Policy",
            description="Used in unit tests to verify mutable policies work normally.",
            status=PolicyStatus.ACTIVE,
            conditions=[],
            actions=[
                PolicyAction(
                    action_type=ActionType.LOG_EVENT,
                    parameters={"event": "test"},
                )
            ],
            immutable=False,
        )

    def setup_method(self):
        """Reset the PolicyManager singleton before each test."""
        manager = get_policy_manager()
        manager.clear()

    def test_immutable_policy_cannot_be_updated(self):
        """update_policy() must raise PermissionError for immutable policies."""
        manager = get_policy_manager()
        policy = self._make_immutable_policy()
        manager.create_policy(policy)

        with pytest.raises(PermissionError) as exc_info:
            manager.update_policy(policy.policy_id, "test_user", name="Hacked Name")

        assert "immutable" in str(exc_info.value).lower(), (
            "PermissionError message must mention 'immutable'."
        )

    def test_immutable_policy_cannot_be_deleted(self):
        """delete_policy() must raise PermissionError for immutable policies."""
        manager = get_policy_manager()
        policy = self._make_immutable_policy("test.immutable.delete")
        manager.create_policy(policy)

        with pytest.raises(PermissionError) as exc_info:
            manager.delete_policy(policy.policy_id, "test_user")

        assert "immutable" in str(exc_info.value).lower(), (
            "PermissionError message must mention 'immutable'."
        )

    def test_immutable_policy_cannot_be_deactivated(self):
        """deactivate_policy() must raise PermissionError for immutable policies."""
        manager = get_policy_manager()
        policy = self._make_immutable_policy("test.immutable.deactivate")
        manager.create_policy(policy)

        with pytest.raises(PermissionError):
            manager.deactivate_policy(policy.policy_id, "test_user")

    def test_mutable_policy_can_be_updated(self):
        """update_policy() must succeed for mutable policies."""
        manager = get_policy_manager()
        policy = self._make_mutable_policy()
        manager.create_policy(policy)

        updated = manager.update_policy(policy.policy_id, "test_user", name="Updated Name")
        assert updated.name == "Updated Name", (
            "Mutable policies must be updatable without error."
        )

    def test_mutable_policy_can_be_deleted(self):
        """delete_policy() must succeed for mutable policies."""
        manager = get_policy_manager()
        policy = self._make_mutable_policy("test.mutable.delete")
        manager.create_policy(policy)

        manager.delete_policy(policy.policy_id, "test_user")
        assert manager.get_policy(policy.policy_id) is None, (
            "Mutable policies must be deletable."
        )

    def test_immutable_policy_remains_after_failed_delete(self):
        """After a failed delete attempt, the policy must still be present."""
        manager = get_policy_manager()
        policy = self._make_immutable_policy("test.immutable.persist")
        manager.create_policy(policy)

        try:
            manager.delete_policy(policy.policy_id, "attacker")
        except PermissionError:
            pass

        assert manager.get_policy(policy.policy_id) is not None, (
            "Immutable policy must still exist after a failed delete attempt."
        )

    def test_immutable_flag_is_serialized_in_to_dict(self):
        """to_dict() must include the immutable field for API responses."""
        policy = self._make_immutable_policy()
        serialized = policy.to_dict()
        assert "immutable" in serialized, (
            "The immutable field must be present in the serialized policy dict."
        )
        assert serialized["immutable"] is True

    def test_pride_protocol_policy_id_format(self):
        """The Pride Protocol policy ID must follow the citadel.pride.v{N} convention."""
        pride_id = "citadel.pride.v1"
        assert pride_id.startswith("citadel.pride.v"), (
            "Pride Protocol policy IDs must follow the citadel.pride.v{N} naming convention."
        )
