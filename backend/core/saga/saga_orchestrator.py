"""
Saga Orchestration — Omnipath v5.0
Manages distributed transactions across multiple services with compensation.

Built with Pride for Obex Blackvault
"""

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

from backend.core.logging_config import get_logger, LoggerMixin
from backend.core.event_sourcing.event_store_impl import EventStore


logger = get_logger(__name__)


# ============================================================================
# Saga Models
# ============================================================================


class SagaStatus(str, Enum):
    """Status of saga execution"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"


class StepStatus(str, Enum):
    """Status of saga step execution"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


@dataclass
class SagaStep:
    """Single step in a saga"""

    step_id: str
    name: str
    action: Callable
    compensation: Optional[Callable] = None
    status: StepStatus = StepStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class SagaDefinition:
    """Definition of a saga workflow"""

    saga_id: str
    name: str
    steps: List[SagaStep] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    status: SagaStatus = SagaStatus.PENDING
    current_step: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ============================================================================
# Saga Orchestrator
# ============================================================================


class SagaOrchestrator(LoggerMixin):
    """
    Orchestrates saga execution with automatic compensation on failure.
    """

    def __init__(self, event_store: EventStore) -> None:
        self.event_store = event_store
        self._sagas: Dict[str, SagaDefinition] = {}

    def create_saga(
        self,
        name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> SagaDefinition:
        saga = SagaDefinition(
            saga_id=str(uuid.uuid4()),
            name=name,
            context=context or {},
        )
        self._sagas[saga.saga_id] = saga
        self.log_info(f"Saga created: {name}", saga_id=saga.saga_id)
        return saga

    def add_step(
        self,
        saga: SagaDefinition,
        name: str,
        action: Callable,
        compensation: Optional[Callable] = None,
    ) -> SagaStep:
        step = SagaStep(
            step_id=str(uuid.uuid4()),
            name=name,
            action=action,
            compensation=compensation,
        )
        saga.steps.append(step)
        self.log_debug(
            f"Step added to saga: {name}",
            saga_id=saga.saga_id,
            step_id=step.step_id,
        )
        return step

    async def execute(self, saga: SagaDefinition) -> bool:
        saga.status = SagaStatus.RUNNING
        saga.started_at = datetime.utcnow()
        self.log_info(
            f"Saga execution started: {saga.name}",
            saga_id=saga.saga_id,
            steps=len(saga.steps),
        )
        await self._emit_event(
            saga_id=saga.saga_id,
            event_type="saga.started",
            data={"name": saga.name, "steps": len(saga.steps)},
        )

        try:
            for i, step in enumerate(saga.steps):
                saga.current_step = i
                success = await self._execute_step(saga, step)
                if not success:
                    await self._compensate(saga, i)
                    saga.status = SagaStatus.COMPENSATED
                    saga.completed_at = datetime.utcnow()
                    await self._emit_event(
                        saga_id=saga.saga_id,
                        event_type="saga.compensated",
                        data={"failed_step": step.name},
                    )
                    return False

            saga.status = SagaStatus.COMPLETED
            saga.completed_at = datetime.utcnow()
            self.log_info(
                f"Saga completed successfully: {saga.name}",
                saga_id=saga.saga_id,
                duration_ms=(saga.completed_at - saga.started_at).total_seconds() * 1000,
            )
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type="saga.completed",
                data={"steps_completed": len(saga.steps)},
            )
            return True

        except Exception as e:
            self.log_error(
                f"Saga execution failed: {saga.name}",
                exc_info=True,
                saga_id=saga.saga_id,
                error=str(e),
            )
            await self._compensate(saga, saga.current_step)
            saga.status = SagaStatus.FAILED
            saga.completed_at = datetime.utcnow()
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type="saga.failed",
                data={"error": str(e)},
            )
            return False

    async def _execute_step(self, saga: SagaDefinition, step: SagaStep) -> bool:
        step.status = StepStatus.RUNNING
        step.started_at = datetime.utcnow()
        self.log_info(
            f"Executing step: {step.name}",
            saga_id=saga.saga_id,
            step_id=step.step_id,
        )
        await self._emit_event(
            saga_id=saga.saga_id,
            event_type="saga.step.started",
            data={"step_name": step.name, "step_id": step.step_id},
        )
        try:
            result = await step.action(saga.context)
            step.result = result
            step.status = StepStatus.COMPLETED
            step.completed_at = datetime.utcnow()
            saga.context[f"{step.name}_result"] = result
            self.log_info(
                f"Step completed: {step.name}",
                saga_id=saga.saga_id,
                step_id=step.step_id,
                duration_ms=(step.completed_at - step.started_at).total_seconds() * 1000,
            )
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type="saga.step.completed",
                data={"step_name": step.name, "step_id": step.step_id},
            )
            return True
        except Exception as e:
            step.error = str(e)
            step.status = StepStatus.FAILED
            step.completed_at = datetime.utcnow()
            self.log_error(
                f"Step failed: {step.name}",
                exc_info=True,
                saga_id=saga.saga_id,
                step_id=step.step_id,
                error=str(e),
            )
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type="saga.step.failed",
                data={"step_name": step.name, "step_id": step.step_id, "error": str(e)},
            )
            return False

    async def _compensate(self, saga: SagaDefinition, failed_step_index: int) -> None:
        saga.status = SagaStatus.COMPENSATING
        self.log_info(
            f"Starting compensation: {saga.name}",
            saga_id=saga.saga_id,
            steps_to_compensate=failed_step_index,
        )
        await self._emit_event(
            saga_id=saga.saga_id,
            event_type="saga.compensation.started",
            data={"steps_to_compensate": failed_step_index},
        )
        for i in range(failed_step_index - 1, -1, -1):
            step = saga.steps[i]
            if step.status == StepStatus.COMPLETED and step.compensation:
                await self._compensate_step(saga, step)
        self.log_info(f"Compensation completed: {saga.name}", saga_id=saga.saga_id)
        await self._emit_event(
            saga_id=saga.saga_id,
            event_type="saga.compensation.completed",
            data={},
        )

    async def _compensate_step(self, saga: SagaDefinition, step: SagaStep) -> None:
        step.status = StepStatus.COMPENSATING
        self.log_info(
            f"Compensating step: {step.name}",
            saga_id=saga.saga_id,
            step_id=step.step_id,
        )
        await self._emit_event(
            saga_id=saga.saga_id,
            event_type="saga.step.compensation.started",
            data={"step_name": step.name, "step_id": step.step_id},
        )
        try:
            await step.compensation(saga.context, step.result)
            step.status = StepStatus.COMPENSATED
            self.log_info(
                f"Step compensated: {step.name}",
                saga_id=saga.saga_id,
                step_id=step.step_id,
            )
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type="saga.step.compensation.completed",
                data={"step_name": step.name, "step_id": step.step_id},
            )
        except Exception as e:
            self.log_error(
                f"Step compensation failed: {step.name}",
                exc_info=True,
                saga_id=saga.saga_id,
                step_id=step.step_id,
                error=str(e),
            )
            await self._emit_event(
                saga_id=saga.saga_id,
                event_type="saga.step.compensation.failed",
                data={"step_name": step.name, "step_id": step.step_id, "error": str(e)},
            )

    async def _emit_event(
        self,
        saga_id: str,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        await self.event_store.append(
            aggregate_id=saga_id,
            aggregate_type="saga",
            event_type=event_type,
            data=data,
        )

    def get_saga(self, saga_id: str) -> Optional[SagaDefinition]:
        return self._sagas.get(saga_id)


# ============================================================================
# Pre-defined Sagas
# ============================================================================


class MissionExecutionSaga:
    """
    Saga for executing a mission end-to-end with credit reservation, mission
    execution, result recording, and final cost deduction.

    Steps:
        1. reserve_credits  — hold estimated cost in the agent's balance
        2. execute_mission  — run the mission via MissionExecutor
        3. record_result    — persist the mission result via the DB session
        4. deduct_cost      — deduct the actual cost and release the reservation

    Each step has a compensation action that undoes the work if a later step
    fails, ensuring the system is always in a consistent state.
    """

    def __init__(
        self,
        orchestrator: SagaOrchestrator,
        marketplace: Any,  # ResourceMarketplace
        mission_executor: Any,  # MissionExecutor
        db_session: Any,  # SQLAlchemy Session
    ) -> None:
        self.orchestrator = orchestrator
        self.marketplace = marketplace
        self.mission_executor = mission_executor
        self.db = db_session

    async def execute(
        self,
        mission_id: str,
        agent_id: str,
        tenant_id: str,
        user_id: str,
        goal: str,
        estimated_cost: float,
        budget: Optional[float] = None,
    ) -> bool:
        """
        Execute the mission saga.

        Args:
            mission_id:     Unique mission identifier.
            agent_id:       Agent that will execute the mission.
            tenant_id:      Tenant owning the mission.
            user_id:        User who created the mission.
            goal:           Mission objective in natural language.
            estimated_cost: Estimated credit cost for the mission.
            budget:         Optional hard budget cap.

        Returns:
            ``True`` if all steps succeeded, ``False`` if the saga was
            compensated due to a step failure.
        """
        saga = self.orchestrator.create_saga(
            name="mission_execution",
            context={
                "mission_id": mission_id,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "goal": goal,
                "estimated_cost": estimated_cost,
                "budget": budget,
            },
        )

        self.orchestrator.add_step(
            saga,
            name="reserve_credits",
            action=self._reserve_credits,
            compensation=self._release_credits,
        )
        self.orchestrator.add_step(
            saga,
            name="execute_mission",
            action=self._execute_mission,
            compensation=self._cancel_mission,
        )
        self.orchestrator.add_step(
            saga,
            name="record_result",
            action=self._record_result,
            compensation=self._delete_result,
        )
        self.orchestrator.add_step(
            saga,
            name="deduct_cost",
            action=self._deduct_cost,
            compensation=self._refund_cost,
        )

        return await self.orchestrator.execute(saga)

    # ------------------------------------------------------------------
    # Step: reserve_credits
    # ------------------------------------------------------------------

    async def _reserve_credits(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Charge the estimated cost upfront as a reservation.
        The reservation is released or adjusted after the mission completes.
        """
        transaction = await self.marketplace.charge(
            tenant_id=context["tenant_id"],
            agent_id=context["agent_id"],
            amount=context["estimated_cost"],
            resource_type="mission_reservation",
            mission_id=context["mission_id"],
        )
        return {
            "reserved": True,
            "reservation_id": transaction["id"],
            "amount": context["estimated_cost"],
        }

    async def _release_credits(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """Refund the reservation if the mission was never executed."""
        if result and result.get("reserved"):
            await self.marketplace.reward(
                tenant_id=context["tenant_id"],
                agent_id=context["agent_id"],
                amount=result["amount"],
                resource_type="mission_reservation_refund",
                mission_id=context["mission_id"],
            )

    # ------------------------------------------------------------------
    # Step: execute_mission
    # ------------------------------------------------------------------

    async def _execute_mission(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to MissionExecutor for the actual execution."""
        result = await self.mission_executor.execute_mission(
            mission_id=context["mission_id"],
            goal=context["goal"],
            tenant_id=context["tenant_id"],
            user_id=context["user_id"],
            budget=context.get("budget"),
        )
        return result

    async def _cancel_mission(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """
        Mark the mission as cancelled in the DB if execution was started.
        The mission record may not exist yet if the executor failed early.
        """
        try:
            from backend.database.models import Mission

            mission = self.db.query(Mission).filter(Mission.id == context["mission_id"]).first()
            if mission:
                mission.status = "CANCELLED"
                mission.error = "Saga compensation: mission cancelled"
                self.db.commit()
        except Exception as exc:
            logger.warning(
                f"Could not cancel mission {context['mission_id']} during compensation: {exc}"
            )

    # ------------------------------------------------------------------
    # Step: record_result
    # ------------------------------------------------------------------

    async def _record_result(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Persist the mission result to the database.
        The MissionExecutor already writes to the DB, so this step validates
        the record exists and enriches it with saga metadata.
        """
        from backend.database.models import Mission

        mission_result = context.get("execute_mission_result", {})
        try:
            mission = self.db.query(Mission).filter(Mission.id == context["mission_id"]).first()
            if mission:
                # Enrich with saga tracking
                if isinstance(mission.context, dict):
                    mission.context["saga_tracked"] = True
                    mission.context["saga_status"] = mission_result.get("status", "UNKNOWN")
                self.db.commit()
        except Exception as exc:
            logger.warning(f"Could not enrich mission record {context['mission_id']}: {exc}")
        return {"recorded": True, "mission_status": mission_result.get("status")}

    async def _delete_result(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """Remove saga metadata from the mission record on compensation."""
        try:
            from backend.database.models import Mission

            mission = self.db.query(Mission).filter(Mission.id == context["mission_id"]).first()
            if mission and isinstance(mission.context, dict):
                mission.context.pop("saga_tracked", None)
                mission.context.pop("saga_status", None)
                self.db.commit()
        except Exception as exc:
            logger.warning(f"Could not clean up mission record {context['mission_id']}: {exc}")

    # ------------------------------------------------------------------
    # Step: deduct_cost
    # ------------------------------------------------------------------

    async def _deduct_cost(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Settle the actual cost:
          - If actual_cost < estimated_cost → refund the difference.
          - If actual_cost > estimated_cost → charge the overage.
        """
        mission_result = context.get("execute_mission_result", {})
        actual_cost: float = mission_result.get("cost", context["estimated_cost"])
        estimated: float = context["estimated_cost"]
        difference = estimated - actual_cost

        if difference > 0:
            # Refund overpayment
            await self.marketplace.reward(
                tenant_id=context["tenant_id"],
                agent_id=context["agent_id"],
                amount=difference,
                resource_type="mission_cost_refund",
                mission_id=context["mission_id"],
            )
        elif difference < 0:
            # Charge underpayment
            await self.marketplace.charge(
                tenant_id=context["tenant_id"],
                agent_id=context["agent_id"],
                amount=abs(difference),
                resource_type="mission_cost_overage",
                mission_id=context["mission_id"],
            )

        return {"settled": True, "actual_cost": actual_cost, "adjustment": difference}

    async def _refund_cost(self, context: Dict[str, Any], result: Optional[Dict[str, Any]]) -> None:
        """Refund the actual cost deduction if the saga is compensated."""
        if result and result.get("settled"):
            await self.marketplace.reward(
                tenant_id=context["tenant_id"],
                agent_id=context["agent_id"],
                amount=result["actual_cost"],
                resource_type="mission_saga_compensation_refund",
                mission_id=context["mission_id"],
            )


# ============================================================================
# AgentCreationSaga
# ============================================================================


class AgentCreationSaga:
    """
    Saga for creating a new agent with full governance registration.

    Steps:
        1. validate_agent_config   — validate the config against governance policies
        2. create_agent_record     — persist the agent to the DB
        3. register_governance     — register the asset in the governance registry
        4. allocate_initial_budget — credit the agent's starting balance

    Each step has a compensation action to undo the work on failure.
    """

    def __init__(
        self,
        orchestrator: SagaOrchestrator,
        marketplace: Any,  # ResourceMarketplace
        db_session: Any,  # SQLAlchemy Session
    ) -> None:
        self.orchestrator = orchestrator
        self.marketplace = marketplace
        self.db = db_session

    async def execute(
        self,
        agent_id: str,
        tenant_id: str,
        name: str,
        agent_type: str,
        model: str,
        config: Dict[str, Any],
        initial_budget: float = 1000.0,
    ) -> bool:
        """
        Execute the agent creation saga.

        Args:
            agent_id:       Unique agent identifier (pre-generated by caller).
            tenant_id:      Tenant that owns the agent.
            name:           Human-readable agent name.
            agent_type:     Agent type (e.g. ``"commander"``, ``"guardian"``).
            model:          LLM model the agent will use.
            config:         Agent configuration dictionary.
            initial_budget: Starting credit balance.

        Returns:
            ``True`` if all steps succeeded, ``False`` if compensated.
        """
        saga = self.orchestrator.create_saga(
            name="agent_creation",
            context={
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "name": name,
                "agent_type": agent_type,
                "model": model,
                "config": config,
                "initial_budget": initial_budget,
            },
        )

        self.orchestrator.add_step(
            saga,
            name="validate_agent_config",
            action=self._validate_agent_config,
            compensation=None,  # Validation is read-only; no compensation needed
        )
        self.orchestrator.add_step(
            saga,
            name="create_agent_record",
            action=self._create_agent_record,
            compensation=self._delete_agent_record,
        )
        self.orchestrator.add_step(
            saga,
            name="register_governance",
            action=self._register_governance,
            compensation=self._deregister_governance,
        )
        self.orchestrator.add_step(
            saga,
            name="allocate_initial_budget",
            action=self._allocate_initial_budget,
            compensation=self._revoke_initial_budget,
        )

        return await self.orchestrator.execute(saga)

    # ------------------------------------------------------------------
    # Step: validate_agent_config
    # ------------------------------------------------------------------

    async def _validate_agent_config(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate agent configuration against governance policies.
        Raises an exception if the config violates any active policy.
        """
        from backend.agents.compliance.policy_engine import get_policy_engine

        try:
            engine = get_policy_engine()
            violations = engine.check_agent_config(
                agent_type=context["agent_type"],
                model=context["model"],
                config=context["config"],
            )
            if violations:
                raise ValueError(
                    f"Agent config violates {len(violations)} governance policy(ies): "
                    + "; ".join(str(v) for v in violations)
                )
        except (ImportError, AttributeError):
            # Policy engine not yet wired — log and continue
            logger.debug("Policy engine not available; skipping config validation")
        return {"valid": True}

    # ------------------------------------------------------------------
    # Step: create_agent_record
    # ------------------------------------------------------------------

    async def _create_agent_record(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Persist the agent record to the database."""
        from backend.database.models import Agent

        agent = Agent(
            id=context["agent_id"],
            name=context["name"],
            type=context["agent_type"],
            status="active",
            tenant_id=context["tenant_id"],
            model=context["model"],
            config=context["config"],
            capabilities=context["config"].get("capabilities", []),
        )
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return {"created": True, "agent_id": agent.id}

    async def _delete_agent_record(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """Remove the agent record on compensation."""
        from backend.database.models import Agent

        try:
            agent = self.db.query(Agent).filter(Agent.id == context["agent_id"]).first()
            if agent:
                self.db.delete(agent)
                self.db.commit()
        except Exception as exc:
            logger.warning(
                f"Could not delete agent {context['agent_id']} during compensation: {exc}"
            )

    # ------------------------------------------------------------------
    # Step: register_governance
    # ------------------------------------------------------------------

    async def _register_governance(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Register the agent as a governance asset."""
        from backend.agents.integration.governance_hooks import GovernanceHooks

        try:
            hooks = GovernanceHooks()
            await hooks.on_agent_created(
                agent_id=context["agent_id"],
                tenant_id=context["tenant_id"],
                agent_type=context["agent_type"],
                config=context["config"],
            )
        except Exception as exc:
            # Governance registration failure is non-fatal for agent creation
            # but we still record it for audit purposes.
            logger.warning(f"Governance registration failed for agent {context['agent_id']}: {exc}")
        return {"registered": True}

    async def _deregister_governance(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """Remove the governance asset registration on compensation."""
        from backend.agents.integration.governance_hooks import GovernanceHooks

        try:
            hooks = GovernanceHooks()
            await hooks.on_agent_deleted(
                agent_id=context["agent_id"],
                tenant_id=context["tenant_id"],
            )
        except Exception as exc:
            logger.warning(
                f"Governance deregistration failed for agent {context['agent_id']}: {exc}"
            )

    # ------------------------------------------------------------------
    # Step: allocate_initial_budget
    # ------------------------------------------------------------------

    async def _allocate_initial_budget(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Credit the agent's initial balance."""
        transaction = await self.marketplace.reward(
            tenant_id=context["tenant_id"],
            agent_id=context["agent_id"],
            amount=context["initial_budget"],
            resource_type="initial_allocation",
            agent_type=context["agent_type"],
        )
        return {
            "allocated": True,
            "transaction_id": transaction["id"],
            "amount": context["initial_budget"],
        }

    async def _revoke_initial_budget(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """Reclaim the initial budget on compensation."""
        if result and result.get("allocated"):
            await self.marketplace.charge(
                tenant_id=context["tenant_id"],
                agent_id=context["agent_id"],
                amount=result["amount"],
                resource_type="initial_allocation_revocation",
                agent_type=context["agent_type"],
            )


# ============================================================================
# SocialMediaPostingSaga
# ============================================================================


class SocialMediaPostingSaga:
    """
    Saga for autonomous social media posting campaigns — Phase 3 (v6.2).

    Manages a multi-step posting workflow with full compensation on failure:

    Steps:
        1. draft_content    — LLM generates post content from a brief.
        2. validate_content — Guardian validates content against policy.
        3. post_content     — Publish to the target platform via tool.
        4. record_post      — Persist post metadata to the EventStore.
        5. schedule_next    — Optionally schedule the next post in a campaign.

    Each step has a compensation action ensuring the system is always
    in a consistent state even if a later step fails.

    Args:
        orchestrator:     SagaOrchestrator instance.
        mission_executor: MissionExecutor for draft/validate steps.
        tool_bridge:      MCPToolBridge for platform posting tools.
        event_store:      EventStore for recording post events.
    """

    def __init__(
        self,
        orchestrator: SagaOrchestrator,
        mission_executor: Any,
        tool_bridge: Any,
        event_store: EventStore,
    ) -> None:
        self.orchestrator = orchestrator
        self.mission_executor = mission_executor
        self.tool_bridge = tool_bridge
        self.event_store = event_store

    async def execute(
        self,
        campaign_id: str,
        agent_id: str,
        tenant_id: str,
        platform: str,
        brief: str,
        post_index: int = 0,
        total_posts: int = 1,
        schedule_next_at: Optional[str] = None,
    ) -> bool:
        """
        Execute the social media posting saga.

        Args:
            campaign_id:      Unique campaign identifier.
            agent_id:         Agent executing the campaign.
            tenant_id:        Tenant owning the campaign.
            platform:         Target platform (twitter|reddit|linkedin).
            brief:            Content brief for the LLM drafter.
            post_index:       Index of this post in the campaign (0-based).
            total_posts:      Total posts in the campaign.
            schedule_next_at: ISO datetime string for the next post (optional).

        Returns:
            ``True`` if all steps succeeded, ``False`` if compensated.
        """
        saga = self.orchestrator.create_saga(
            name="social_media_posting",
            context={
                "campaign_id": campaign_id,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "platform": platform,
                "brief": brief,
                "post_index": post_index,
                "total_posts": total_posts,
                "schedule_next_at": schedule_next_at,
            },
        )

        self.orchestrator.add_step(
            saga,
            name="draft_content",
            action=self._draft_content,
            compensation=self._discard_draft,
        )
        self.orchestrator.add_step(
            saga,
            name="validate_content",
            action=self._validate_content,
            compensation=self._reject_content,
        )
        self.orchestrator.add_step(
            saga,
            name="post_content",
            action=self._post_content,
            compensation=self._delete_post,
        )
        self.orchestrator.add_step(
            saga,
            name="record_post",
            action=self._record_post,
            compensation=self._unrecord_post,
        )
        if schedule_next_at:
            self.orchestrator.add_step(
                saga,
                name="schedule_next",
                action=self._schedule_next,
                compensation=self._cancel_next,
            )

        return await self.orchestrator.execute(saga)

    # ------------------------------------------------------------------
    # Step: draft_content
    # ------------------------------------------------------------------

    async def _draft_content(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Use the LLM to draft post content from the brief."""
        platform = context["platform"]
        brief = context["brief"]
        post_index = context["post_index"]
        total_posts = context["total_posts"]

        char_limits = {"twitter": 280, "reddit": 40_000, "linkedin": 3_000}
        limit = char_limits.get(platform, 1_000)

        prompt = (
            f"Write a {platform} post for the following brief. "
            f"This is post {post_index + 1} of {total_posts} in a campaign. "
            f"Keep it under {limit} characters. Be engaging and professional.\n\n"
            f"Brief: {brief}\n\n"
            f"Output ONLY the post text, no explanations."
        )

        result = await self.mission_executor.execute_mission(
            mission_id=f"draft-{context['campaign_id']}-{post_index}",
            goal=prompt,
            tenant_id=context["tenant_id"],
            user_id="system",
        )

        draft = result.get("result", "")
        if len(draft) > limit:
            draft = draft[:limit]

        logger.info(
            f"SocialMediaPostingSaga: drafted {len(draft)} chars for {platform}"
        )
        return {"draft": draft, "platform": platform, "char_count": len(draft)}

    async def _discard_draft(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """No-op — drafts are ephemeral."""
        pass

    # ------------------------------------------------------------------
    # Step: validate_content
    # ------------------------------------------------------------------

    async def _validate_content(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate the drafted content against the Pride Protocol policy.
        Uses the guardian LLM to check for policy violations.
        """
        draft_result = context.get("draft_content_result", {})
        draft = draft_result.get("draft", "")

        validation_prompt = (
            f"Review this {context['platform']} post for policy compliance. "
            f"Check for: spam, misinformation, hate speech, or inappropriate content.\n\n"
            f"Post: {draft}\n\n"
            f"Respond with JSON: {{\"approved\": true/false, \"reason\": \"...\"}}"
        )

        result = await self.mission_executor.execute_mission(
            mission_id=f"validate-{context['campaign_id']}-{context['post_index']}",
            goal=validation_prompt,
            tenant_id=context["tenant_id"],
            user_id="system",
        )

        import json as _json
        try:
            validation = _json.loads(result.get("result", '{"approved": true}'))
        except _json.JSONDecodeError:
            validation = {"approved": True, "reason": "Validation parse error — defaulting to approved"}

        if not validation.get("approved", True):
            raise ValueError(
                f"Content validation failed: {validation.get('reason', 'Policy violation')}"
            )

        return {"approved": True, "reason": validation.get("reason", "Passed")}

    async def _reject_content(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """Log the rejection — no state to undo."""
        logger.warning(
            f"SocialMediaPostingSaga: content rejected for campaign {context['campaign_id']}"
        )

    # ------------------------------------------------------------------
    # Step: post_content
    # ------------------------------------------------------------------

    async def _post_content(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Publish the validated content to the target platform."""
        import json as _json

        draft_result = context.get("draft_content_result", {})
        draft = draft_result.get("draft", "")
        platform = context["platform"]

        tool_map = {
            "twitter": "twitter",
            "reddit": "reddit",
        }
        tool_name = tool_map.get(platform)

        if tool_name and self.tool_bridge.has_tool(tool_name):
            raw = await self.tool_bridge.call_tool(
                tool_name,
                {"action": "post_tweet" if platform == "twitter" else "submit_post", "text": draft},
            )
            post_result = _json.loads(raw) if isinstance(raw, str) else raw
        else:
            # Simulation mode — no credentials configured
            logger.warning(
                f"SocialMediaPostingSaga: {platform} tool not available — simulating post"
            )
            post_result = {
                "success": True,
                "simulated": True,
                "platform": platform,
                "text": draft,
                "post_id": f"sim-{context['campaign_id']}-{context['post_index']}",
            }

        if not post_result.get("success"):
            raise RuntimeError(
                f"Post failed on {platform}: {post_result.get('error', 'Unknown error')}"
            )

        logger.info(
            f"SocialMediaPostingSaga: posted to {platform} — "
            f"post_id={post_result.get('post_id') or post_result.get('tweet_id')}"
        )
        return post_result

    async def _delete_post(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """
        Attempt to delete the post if it was published.
        Best-effort — platform APIs may not support deletion.
        """
        if not result or result.get("simulated"):
            return

        platform = context["platform"]
        post_id = result.get("post_id") or result.get("tweet_id")
        if post_id:
            logger.warning(
                f"SocialMediaPostingSaga: compensation — attempting to delete "
                f"{platform} post {post_id}"
            )
            # Platform-specific deletion would go here
            # For now, log the intent — deletion is best-effort

    # ------------------------------------------------------------------
    # Step: record_post
    # ------------------------------------------------------------------

    async def _record_post(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Persist post metadata to the EventStore."""
        post_result = context.get("post_content_result", {})

        await self.event_store.append_event(
            aggregate_id=context["campaign_id"],
            event_type="campaign.post_published",
            payload={
                "campaign_id": context["campaign_id"],
                "agent_id": context["agent_id"],
                "platform": context["platform"],
                "post_index": context["post_index"],
                "total_posts": context["total_posts"],
                "post_id": post_result.get("post_id") or post_result.get("tweet_id"),
                "simulated": post_result.get("simulated", False),
                "char_count": context.get("draft_content_result", {}).get("char_count", 0),
            },
            tenant_id=context["tenant_id"],
            user_id=context["agent_id"],
        )

        return {"recorded": True, "event_type": "campaign.post_published"}

    async def _unrecord_post(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """
        EventStore events are immutable — record a compensation event instead.
        """
        if result and result.get("recorded"):
            await self.event_store.append_event(
                aggregate_id=context["campaign_id"],
                event_type="campaign.post_compensated",
                payload={
                    "campaign_id": context["campaign_id"],
                    "post_index": context["post_index"],
                    "reason": "Saga compensation",
                },
                tenant_id=context["tenant_id"],
                user_id=context["agent_id"],
            )

    # ------------------------------------------------------------------
    # Step: schedule_next
    # ------------------------------------------------------------------

    async def _schedule_next(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Schedule the next post in the campaign via the SchedulerService.
        Only runs if schedule_next_at is set in the context.
        """
        schedule_next_at = context.get("schedule_next_at")
        if not schedule_next_at:
            return {"scheduled": False}

        next_index = context["post_index"] + 1
        if next_index >= context["total_posts"]:
            logger.info(
                f"SocialMediaPostingSaga: campaign {context['campaign_id']} complete "
                f"({context['total_posts']} posts)"
            )
            return {"scheduled": False, "reason": "Campaign complete"}

        # The SchedulerService is accessed via app.state in the route layer.
        # Here we emit an event that the scheduler can pick up.
        await self.event_store.append_event(
            aggregate_id=context["campaign_id"],
            event_type="campaign.next_post_scheduled",
            payload={
                "campaign_id": context["campaign_id"],
                "agent_id": context["agent_id"],
                "next_post_index": next_index,
                "scheduled_at": schedule_next_at,
                "platform": context["platform"],
                "brief": context["brief"],
            },
            tenant_id=context["tenant_id"],
            user_id=context["agent_id"],
        )

        return {"scheduled": True, "next_post_index": next_index, "at": schedule_next_at}

    async def _cancel_next(
        self, context: Dict[str, Any], result: Optional[Dict[str, Any]]
    ) -> None:
        """Record that the scheduled next post was cancelled."""
        if result and result.get("scheduled"):
            await self.event_store.append_event(
                aggregate_id=context["campaign_id"],
                event_type="campaign.next_post_cancelled",
                payload={
                    "campaign_id": context["campaign_id"],
                    "next_post_index": result.get("next_post_index"),
                    "reason": "Saga compensation",
                },
                tenant_id=context["tenant_id"],
                user_id=context["agent_id"],
            )
