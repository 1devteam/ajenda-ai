"""
Tests for compliance policy configuration system.
"""

import pytest
import tempfile
from pathlib import Path

from backend.agents.compliance.policy import (
    AgentPolicy,
    ApprovalPolicy,
    PIIPolicy,
    TenantPolicy,
    CompliancePolicy,
    PolicyLoader,
    PolicyStore,
    get_policy_store,
    set_policy_store,
)


class TestAgentPolicy:
    """Tests for AgentPolicy dataclass"""

    def test_default_values(self):
        """Test default values"""
        policy = AgentPolicy(agent_type="researcher")

        assert policy.agent_type == "researcher"
        assert policy.allowed_tools == []
        assert policy.cost_limit_usd == 10.0
        assert policy.rate_limits == {}
        assert policy.require_mission is True

    def test_custom_values(self):
        """Test custom values"""
        policy = AgentPolicy(
            agent_type="analyst",
            allowed_tools=["calculator"],
            cost_limit_usd=20.0,
            rate_limits={"calculator": 5},
            require_mission=False,
        )

        assert policy.agent_type == "analyst"
        assert policy.allowed_tools == ["calculator"]
        assert policy.cost_limit_usd == 20.0
        assert policy.rate_limits == {"calculator": 5}
        assert policy.require_mission is False


class TestPolicyLoader:
    """Tests for PolicyLoader"""

    def test_load_from_string_minimal(self):
        """Test loading minimal policy"""
        yaml_content = """
version: "1.0"
"""
        policy = PolicyLoader.load_from_string(yaml_content)

        assert policy.version == "1.0"
        assert policy.agent_policies == {}
        assert policy.approval_policy.enabled is True
        assert policy.pii_policy.enabled is True
        assert policy.tenant_policy.enabled is True

    def test_load_from_string_complete(self):
        """Test loading complete policy"""
        yaml_content = """
version: "1.0"
metadata:
  author: "test"
agent_policies:
  researcher:
    allowed_tools:
      - web_search
    cost_limit_usd: 10.0
    rate_limits:
      web_search: 10
    require_mission: true
approval_required:
  enabled: true
  tools:
    - file_writer
  paths:
    - /prod/
pii_detection:
  enabled: true
  block_on_detection: true
tenant_isolation:
  enabled: true
  strict_mode: true
"""
        policy = PolicyLoader.load_from_string(yaml_content)

        assert policy.version == "1.0"
        assert "researcher" in policy.agent_policies
        assert policy.agent_policies["researcher"].allowed_tools == ["web_search"]
        assert policy.agent_policies["researcher"].cost_limit_usd == 10.0
        assert policy.agent_policies["researcher"].rate_limits == {"web_search": 10}
        assert policy.approval_policy.tools == ["file_writer"]
        assert policy.approval_policy.paths == ["/prod/"]
        assert policy.pii_policy.enabled is True
        assert policy.tenant_policy.strict_mode is True
        assert policy.metadata["author"] == "test"

    def test_load_from_string_missing_version(self):
        """Test loading policy without version"""
        yaml_content = """
agent_policies:
  researcher:
    allowed_tools:
      - web_search
"""
        with pytest.raises(ValueError, match="must specify 'version'"):
            PolicyLoader.load_from_string(yaml_content)

    def test_load_from_string_unsupported_version(self):
        """Test loading policy with unsupported version"""
        yaml_content = """
version: "2.0"
"""
        with pytest.raises(ValueError, match="Unsupported policy version"):
            PolicyLoader.load_from_string(yaml_content)

    def test_load_from_string_invalid_yaml(self):
        """Test loading invalid YAML"""
        yaml_content = """
version: "1.0"
  invalid: yaml: syntax
"""
        with pytest.raises(ValueError, match="Invalid YAML"):
            PolicyLoader.load_from_string(yaml_content)

    def test_load_from_file(self):
        """Test loading from file"""
        yaml_content = """
version: "1.0"
agent_policies:
  researcher:
    allowed_tools:
      - web_search
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(yaml_content)
            filepath = f.name

        try:
            policy = PolicyLoader.load_from_file(filepath)

            assert policy.version == "1.0"
            assert "researcher" in policy.agent_policies
            assert policy.metadata["filepath"] == filepath
        finally:
            Path(filepath).unlink()

    def test_load_from_file_not_found(self):
        """Test loading from non-existent file"""
        with pytest.raises(FileNotFoundError):
            PolicyLoader.load_from_file("/nonexistent/policy.yml")

    def test_get_builtin_default(self):
        """Test getting built-in default policy"""
        policy = PolicyLoader.get_builtin_default()

        assert policy.version == "1.0"
        assert "researcher" in policy.agent_policies
        assert "analyst" in policy.agent_policies
        assert "developer" in policy.agent_policies
        assert policy.agent_policies["researcher"].allowed_tools == [
            "web_search",
            "calculator",
        ]
        assert policy.agent_policies["analyst"].cost_limit_usd == 20.0
        assert policy.approval_policy.tools == [
            "file_writer",
            "database_query",
            "api_caller",
        ]
        assert policy.metadata["source"] == "builtin_default"


class TestPolicyStore:
    """Tests for PolicyStore"""

    def test_init_with_default(self):
        """Test initialization with default policy"""
        store = PolicyStore()

        assert store.policy is not None
        assert store.policy.version == "1.0"

    def test_init_with_custom_policy(self):
        """Test initialization with custom policy"""
        custom_policy = CompliancePolicy(version="1.0")
        store = PolicyStore(policy=custom_policy)

        assert store.policy == custom_policy

    def test_load_from_file(self):
        """Test loading from file"""
        yaml_content = """
version: "1.0"
agent_policies:
  researcher:
    allowed_tools:
      - web_search
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(yaml_content)
            filepath = f.name

        try:
            store = PolicyStore()
            store.load_from_file(filepath)

            assert store.policy.version == "1.0"
            assert "researcher" in store.policy.agent_policies
        finally:
            Path(filepath).unlink()

    def test_reload(self):
        """Test reloading policy"""
        yaml_content_v1 = """
version: "1.0"
agent_policies:
  researcher:
    cost_limit_usd: 10.0
"""
        yaml_content_v2 = """
version: "1.0"
agent_policies:
  researcher:
    cost_limit_usd: 20.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(yaml_content_v1)
            filepath = f.name

        try:
            store = PolicyStore()
            store.load_from_file(filepath)

            assert store.policy.agent_policies["researcher"].cost_limit_usd == 10.0

            # Update file
            with open(filepath, "w") as f:
                f.write(yaml_content_v2)

            store.reload()

            assert store.policy.agent_policies["researcher"].cost_limit_usd == 20.0
        finally:
            Path(filepath).unlink()

    def test_reload_without_filepath(self):
        """Test reloading without filepath"""
        store = PolicyStore()

        with pytest.raises(ValueError, match="No filepath set"):
            store.reload()

    def test_get_agent_policy(self):
        """Test getting agent policy"""
        store = PolicyStore()

        policy = store.get_agent_policy("researcher")

        assert policy is not None
        assert policy.agent_type == "researcher"

    def test_get_agent_policy_not_found(self):
        """Test getting non-existent agent policy"""
        store = PolicyStore()

        policy = store.get_agent_policy("nonexistent")

        assert policy is None

    def test_get_approval_policy(self):
        """Test getting approval policy"""
        store = PolicyStore()

        policy = store.get_approval_policy()

        assert policy is not None
        assert isinstance(policy, ApprovalPolicy)

    def test_get_pii_policy(self):
        """Test getting PII policy"""
        store = PolicyStore()

        policy = store.get_pii_policy()

        assert policy is not None
        assert isinstance(policy, PIIPolicy)

    def test_get_tenant_policy(self):
        """Test getting tenant policy"""
        store = PolicyStore()

        policy = store.get_tenant_policy()

        assert policy is not None
        assert isinstance(policy, TenantPolicy)


class TestGlobalPolicyStore:
    """Tests for global policy store functions"""

    def test_get_policy_store(self):
        """Test getting global policy store"""
        # Reset global store
        set_policy_store(None)

        store = get_policy_store()

        assert store is not None
        assert isinstance(store, PolicyStore)

    def test_get_policy_store_singleton(self):
        """Test global policy store is singleton"""
        # Reset global store
        set_policy_store(None)

        store1 = get_policy_store()
        store2 = get_policy_store()

        assert store1 is store2

    def test_set_policy_store(self):
        """Test setting global policy store"""
        custom_store = PolicyStore()

        set_policy_store(custom_store)

        store = get_policy_store()

        assert store is custom_store
