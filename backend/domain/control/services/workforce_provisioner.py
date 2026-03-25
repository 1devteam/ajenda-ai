"""
Workforce Provisioner

Governed boundary for workforce creation.

Current incremental refactor stage:
- provisioning remains compatible with single-agent execution
- a WorkforceFleet is now created as the first-class execution container
- AgentFactory is still used indirectly here because we are not yet refactoring
  the lower-level spawn mechanics
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import uuid4

from backend.domain.control.services.fleet_manager import FleetManager
from backend.models.domain.agent import Agent
from backend.models.domain.workforce_fleet import WorkforceFleet


class WorkforceProvisioningResult:
    """
    Result of a governed workforce provisioning request.

    Transitional shape:
    - exposes the created fleet
    - exposes the primary agent for compatibility with existing executor logic
    """

    def __init__(
        self,
        fleet: WorkforceFleet,
        primary_agent: Agent,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.fleet = fleet
        self.primary_agent = primary_agent
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fleet": self.fleet.model_dump(),
            "primary_agent": self.primary_agent.model_dump(),
            "metadata": self.metadata,
        }


class WorkforceProvisioner:
    """
    Governs workforce provisioning for mission execution.

    Architectural rule:
    Mission execution must request workforce through this service rather than
    creating agents directly inside execution code.
    """

    def __init__(self, agent_factory: Any) -> None:
        self.agent_factory = agent_factory
        self.fleet_manager = FleetManager()

    def provision_for_mission(
        self,
        *,
        mission_id: str,
        tenant_id: str,
        objective: str,
        agent_type: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkforceProvisioningResult:
        """
        Provision a workforce fleet for a mission.

        Incremental behavior:
        - creates one fleet
        - provisions one primary agent
        - binds that agent to the fleet
        """

        metadata = metadata or {}
        agent_config = agent_config or {}

        primary_agent = self._create_primary_agent(
            tenant_id=tenant_id,
            objective=objective,
            agent_type=agent_type,
            agent_config=agent_config,
            metadata=metadata,
        )

        fleet = self.fleet_manager.create_fleet(
            mission_id=mission_id,
            tenant_id=tenant_id,
            objective=objective,
            primary_agent_id=self._get_agent_id(primary_agent),
            agent_ids=[self._get_agent_id(primary_agent)],
            metadata={
                **metadata,
                "provisioning_mode": "single_agent_transitional",
            },
        )

        self._attach_fleet_metadata(primary_agent, fleet)

        return WorkforceProvisioningResult(
            fleet=fleet,
            primary_agent=primary_agent,
            metadata={
                "mission_id": mission_id,
                "tenant_id": tenant_id,
                "fleet_id": fleet.id,
                "primary_agent_id": self._get_agent_id(primary_agent),
            },
        )

    async def provision_agent_for_mission(
        self,
        *,
        mission_goal: str,
        plan: Dict[str, Any],
        tenant_id: str,
    ) -> Optional[Agent]:
        """
        Compatibility bridge for the current MissionExecutor contract.

        Current executor expects:
        - async method
        - direct agent return
        - None when no specialized agent is needed

        This method preserves that behavior while creating a fleet underneath.
        """

        complexity = str(plan.get("complexity", "simple")).lower()

        if complexity not in {"moderate", "complex"}:
            return None

        agent_type = self._select_agent_type(mission_goal=mission_goal, plan=plan)
        mission_id = str(plan.get("mission_id") or f"mission_{uuid4().hex[:12]}")

        result = self.provision_for_mission(
            mission_id=mission_id,
            tenant_id=tenant_id,
            objective=mission_goal,
            agent_type=agent_type,
            agent_config={
                "model_selection": plan.get("model_selection"),
                "requires_tools": plan.get("requires_tools", []),
                "complexity": complexity,
            },
            metadata={
                "source": "mission_executor",
                "selected_agent_type": agent_type,
                "plan_complexity": complexity,
                "plan_steps": len(plan.get("steps", [])),
            },
        )

        agent = result.primary_agent
        self._attach_runtime_agent_aliases(agent)
        self._attach_fleet_metadata(agent, result.fleet)
        return agent

    def _select_agent_type(
        self,
        *,
        mission_goal: str,
        plan: Dict[str, Any],
    ) -> str:
        """
        Transitional agent-type selection logic.

        Keeps selection simple and explicit until FleetManager / ExecutionTask
        become first-class.
        """

        goal_text = mission_goal.lower()
        tools = [str(t).lower() for t in plan.get("requires_tools", [])]

        if any(word in goal_text for word in ["research", "investigate", "find", "search"]):
            return "researcher"

        if any(word in goal_text for word in ["analyze", "analysis", "compare", "evaluate"]):
            return "analyst"

        if any(word in goal_text for word in ["build", "code", "implement", "develop"]):
            return "developer"

        if any(tool in {"browser", "search", "retrieval"} for tool in tools):
            return "researcher"

        return "analyst"

    def _create_primary_agent(
        self,
        *,
        tenant_id: str,
        objective: str,
        agent_type: Optional[str],
        agent_config: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Agent:
        """
        Transitional adapter to existing agent factory behavior.
        """

        creation_payload = {
            "tenant_id": tenant_id,
            "objective": objective,
            "agent_type": agent_type,
            "config": agent_config,
            "metadata": metadata,
        }

        if hasattr(self.agent_factory, "create_agent"):
            return self.agent_factory.create_agent(**creation_payload)

        if hasattr(self.agent_factory, "create"):
            return self.agent_factory.create(**creation_payload)

        raise AttributeError(
            "AgentFactory does not expose a supported creation method "
            "(expected create_agent or create)."
        )

    def _get_agent_id(self, agent: Agent) -> str:
        if hasattr(agent, "id"):
            return str(agent.id)
        if hasattr(agent, "agent_id"):
            return str(agent.agent_id)
        raise AttributeError("Provisioned agent does not expose id or agent_id")

    def _attach_runtime_agent_aliases(self, agent: Agent) -> None:
        """
        Normalize agent shape for current MissionExecutor expectations.
        """

        if not hasattr(agent, "agent_id") and hasattr(agent, "id"):
            setattr(agent, "agent_id", getattr(agent, "id"))

        if not hasattr(agent, "id") and hasattr(agent, "agent_id"):
            setattr(agent, "id", getattr(agent, "agent_id"))

        if not hasattr(agent, "agent_type"):
            setattr(agent, "agent_type", "specialist")

    def _attach_fleet_metadata(self, agent: Agent, fleet: WorkforceFleet) -> None:
        """
        Expose fleet identity on the returned agent during the transition phase.
        """

        setattr(agent, "fleet_id", fleet.id)
        setattr(agent, "workforce_fleet_id", fleet.id)
        setattr(agent, "fleet", fleet)

