"""
Policy configuration system for Omnipath V2 compliance.

Allows defining compliance policies in YAML files, similar to governance_engine's
.govmesh.yml pattern. Policies are versioned, validated, and hot-reloadable.

Example policy file (.omnipath_policy.yml):
    version: "1.0"
    agent_policies:
      researcher:
        allowed_tools:
          - web_search
          - calculator
        cost_limit_usd: 10.0
        rate_limits:
          web_search: 10
      analyst:
        allowed_tools:
          - calculator
          - python_executor
        cost_limit_usd: 20.0

    approval_required:
      tools:
        - file_writer
        - database_query
      paths:
        - /prod/
        - /config/

    pii_detection:
      enabled: true
      block_on_detection: true

    tenant_isolation:
      enabled: true
      strict_mode: true
"""

import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AgentPolicy:
    """
    Policy for a specific agent type.

    Attributes:
        agent_type: Type of agent (researcher, analyst, developer)
        allowed_tools: List of tools the agent can use
        cost_limit_usd: Maximum cost per day in USD
        rate_limits: Tool-specific rate limits (calls per minute)
        require_mission: Whether mission justification is required
    """

    agent_type: str
    allowed_tools: List[str] = field(default_factory=list)
    cost_limit_usd: float = 10.0
    rate_limits: Dict[str, int] = field(default_factory=dict)
    require_mission: bool = True


@dataclass
class ApprovalPolicy:
    """
    Policy for operations requiring approval.

    Attributes:
        tools: Tools requiring approval
        paths: Path patterns requiring approval
        enabled: Whether approval workflow is enabled
    """

    tools: List[str] = field(default_factory=list)
    paths: List[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class PIIPolicy:
    """
    Policy for PII detection.

    Attributes:
        enabled: Whether PII detection is enabled
        block_on_detection: Whether to block when PII is detected
        patterns: Custom PII patterns (regex)
    """

    enabled: bool = True
    block_on_detection: bool = True
    patterns: Dict[str, str] = field(default_factory=dict)


@dataclass
class TenantPolicy:
    """
    Policy for tenant isolation.

    Attributes:
        enabled: Whether tenant isolation is enabled
        strict_mode: Whether to enforce strict isolation
        tenant_scoped_tools: Tools that are tenant-scoped
    """

    enabled: bool = True
    strict_mode: bool = True
    tenant_scoped_tools: List[str] = field(default_factory=list)


@dataclass
class CompliancePolicy:
    """
    Complete compliance policy configuration.

    Attributes:
        version: Policy version (semver)
        agent_policies: Policies for each agent type
        approval_policy: Approval workflow policy
        pii_policy: PII detection policy
        tenant_policy: Tenant isolation policy
        metadata: Policy metadata (created, updated, author)
    """

    version: str
    agent_policies: Dict[str, AgentPolicy] = field(default_factory=dict)
    approval_policy: ApprovalPolicy = field(default_factory=ApprovalPolicy)
    pii_policy: PIIPolicy = field(default_factory=PIIPolicy)
    tenant_policy: TenantPolicy = field(default_factory=TenantPolicy)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PolicyLoader:
    """
    Loads and validates compliance policies from YAML files.

    Supports:
    - Loading from file or string
    - Schema validation
    - Version checking
    - Hot reloading
    """

    SUPPORTED_VERSIONS = ["1.0"]
    DEFAULT_POLICY_FILE = ".omnipath_policy.yml"

    @classmethod
    def load_from_file(cls, filepath: str) -> CompliancePolicy:
        """
        Load policy from YAML file.

        Args:
            filepath: Path to policy file

        Returns:
            CompliancePolicy instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If policy is invalid
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Policy file not found: {filepath}")

        with open(path, "r") as f:
            content = f.read()

        return cls.load_from_string(content, filepath=str(path))

    @classmethod
    def load_from_string(
        cls, content: str, filepath: Optional[str] = None
    ) -> CompliancePolicy:
        """
        Load policy from YAML string.

        Args:
            content: YAML content
            filepath: Optional filepath for metadata

        Returns:
            CompliancePolicy instance

        Raises:
            ValueError: If policy is invalid
        """
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")

        if not isinstance(data, dict):
            raise ValueError("Policy must be a YAML dictionary")

        # Validate version
        version = data.get("version")
        if not version:
            raise ValueError("Policy must specify 'version'")

        if version not in cls.SUPPORTED_VERSIONS:
            raise ValueError(
                f"Unsupported policy version: {version}. "
                f"Supported versions: {', '.join(cls.SUPPORTED_VERSIONS)}"
            )

        # Parse agent policies
        agent_policies = {}
        for agent_type, policy_data in data.get("agent_policies", {}).items():
            agent_policies[agent_type] = AgentPolicy(
                agent_type=agent_type,
                allowed_tools=policy_data.get("allowed_tools", []),
                cost_limit_usd=policy_data.get("cost_limit_usd", 10.0),
                rate_limits=policy_data.get("rate_limits", {}),
                require_mission=policy_data.get("require_mission", True),
            )

        # Parse approval policy
        approval_data = data.get("approval_required", {})
        approval_policy = ApprovalPolicy(
            tools=approval_data.get("tools", []),
            paths=approval_data.get("paths", []),
            enabled=approval_data.get("enabled", True),
        )

        # Parse PII policy
        pii_data = data.get("pii_detection", {})
        pii_policy = PIIPolicy(
            enabled=pii_data.get("enabled", True),
            block_on_detection=pii_data.get("block_on_detection", True),
            patterns=pii_data.get("patterns", {}),
        )

        # Parse tenant policy
        tenant_data = data.get("tenant_isolation", {})
        tenant_policy = TenantPolicy(
            enabled=tenant_data.get("enabled", True),
            strict_mode=tenant_data.get("strict_mode", True),
            tenant_scoped_tools=tenant_data.get("tenant_scoped_tools", []),
        )

        # Build metadata
        metadata = {
            "loaded_at": datetime.utcnow().isoformat(),
            "filepath": filepath,
        }
        metadata.update(data.get("metadata", {}))

        return CompliancePolicy(
            version=version,
            agent_policies=agent_policies,
            approval_policy=approval_policy,
            pii_policy=pii_policy,
            tenant_policy=tenant_policy,
            metadata=metadata,
        )

    @classmethod
    def load_default(cls) -> CompliancePolicy:
        """
        Load default policy (from current directory or fallback).

        Returns:
            CompliancePolicy instance
        """
        # Try to load from current directory
        default_path = Path(cls.DEFAULT_POLICY_FILE)
        if default_path.exists():
            return cls.load_from_file(str(default_path))

        # Fallback to built-in default
        return cls.get_builtin_default()

    @classmethod
    def get_builtin_default(cls) -> CompliancePolicy:
        """
        Get built-in default policy.

        Returns:
            CompliancePolicy with sensible defaults
        """
        return CompliancePolicy(
            version="1.0",
            agent_policies={
                "researcher": AgentPolicy(
                    agent_type="researcher",
                    allowed_tools=["web_search", "calculator"],
                    cost_limit_usd=10.0,
                    rate_limits={"web_search": 10},
                    require_mission=True,
                ),
                "analyst": AgentPolicy(
                    agent_type="analyst",
                    allowed_tools=["calculator", "python_executor"],
                    cost_limit_usd=20.0,
                    rate_limits={"python_executor": 5},
                    require_mission=True,
                ),
                "developer": AgentPolicy(
                    agent_type="developer",
                    allowed_tools=["python_executor", "file_reader", "file_writer"],
                    cost_limit_usd=15.0,
                    rate_limits={"python_executor": 5},
                    require_mission=True,
                ),
            },
            approval_policy=ApprovalPolicy(
                tools=["file_writer", "database_query", "api_caller"],
                paths=["/prod/", "/production/", "/config/", ".env"],
                enabled=True,
            ),
            pii_policy=PIIPolicy(enabled=True, block_on_detection=True, patterns={}),
            tenant_policy=TenantPolicy(
                enabled=True,
                strict_mode=True,
                tenant_scoped_tools=["file_reader", "file_writer", "database_query"],
            ),
            metadata={
                "created_at": datetime.utcnow().isoformat(),
                "source": "builtin_default",
            },
        )


class PolicyStore:
    """
    Stores and manages compliance policies.

    Supports:
    - Hot reloading
    - Policy caching
    - File watching (future)
    """

    def __init__(self, policy: Optional[CompliancePolicy] = None):
        """
        Initialize policy store.

        Args:
            policy: Initial policy (defaults to built-in default)
        """
        self._policy = policy or PolicyLoader.get_builtin_default()
        self._filepath: Optional[str] = None

    @property
    def policy(self) -> CompliancePolicy:
        """Get current policy."""
        return self._policy

    def load_from_file(self, filepath: str) -> None:
        """
        Load policy from file.

        Args:
            filepath: Path to policy file
        """
        self._policy = PolicyLoader.load_from_file(filepath)
        self._filepath = filepath

    def reload(self) -> None:
        """
        Reload policy from file.

        Raises:
            ValueError: If no filepath is set
        """
        if not self._filepath:
            raise ValueError("No filepath set, cannot reload")

        self.load_from_file(self._filepath)

    def get_agent_policy(self, agent_type: str) -> Optional[AgentPolicy]:
        """
        Get policy for specific agent type.

        Args:
            agent_type: Type of agent

        Returns:
            AgentPolicy or None if not found
        """
        return self._policy.agent_policies.get(agent_type)

    def get_approval_policy(self) -> ApprovalPolicy:
        """Get approval policy."""
        return self._policy.approval_policy

    def get_pii_policy(self) -> PIIPolicy:
        """Get PII policy."""
        return self._policy.pii_policy

    def get_tenant_policy(self) -> TenantPolicy:
        """Get tenant policy."""
        return self._policy.tenant_policy


# Global policy store instance
_global_policy_store: Optional[PolicyStore] = None


def get_policy_store() -> PolicyStore:
    """
    Get global policy store instance.

    Returns:
        PolicyStore instance
    """
    global _global_policy_store
    if _global_policy_store is None:
        _global_policy_store = PolicyStore()
    return _global_policy_store


def set_policy_store(store: PolicyStore) -> None:
    """
    Set global policy store instance.

    Args:
        store: PolicyStore instance
    """
    global _global_policy_store
    _global_policy_store = store


def load_policy_from_file(filepath: str) -> None:
    """
    Load policy from file into global store.

    Args:
        filepath: Path to policy file
    """
    store = get_policy_store()
    store.load_from_file(filepath)
