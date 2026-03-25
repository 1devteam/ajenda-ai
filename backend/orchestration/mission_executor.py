"""
Mission Execution Orchestrator
Coordinates agents, manages economy, and executes missions end-to-end
"""

from __future__ import annotations

import asyncio
import json
import uuid
import logging
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.factory.agent_factory import AgentFactory
from backend.agents.governance import assemble_prompt
from backend.agents.integration.governance_hooks import governance_hooks
from backend.core.event_bus.nats_bus import NATSEventBus
from backend.domain.control.services.execution_coordinator import ExecutionCoordinator
from backend.domain.control.services.workforce_provisioner import WorkforceProvisioner
from backend.models.domain.execution_task import ExecutionTask, ExecutionTaskType
from backend.economy.resource_marketplace import ResourceMarketplace, ResourceType
from backend.integrations.llm.llm_service import LLMService
from backend.integrations.observability.prometheus_metrics import get_metrics
from backend.integrations.observability.telemetry import get_meter, get_tracer

if TYPE_CHECKING:
    from backend.core.event_sourcing.event_store_impl import EventStore

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)
meter = get_meter(__name__)


class MissionComplexity(Enum):
    """Mission complexity levels."""

    SIMPLE = "simple"      # Single agent, single step
    MODERATE = "moderate"  # Multiple steps, single agent
    COMPLEX = "complex"    # Multiple agents, coordination required
    SWARM = "swarm"        # Requires dynamic swarm formation


class MissionExecutor:
    """
    Orchestrates mission execution with economy, governance, and telemetry integration.

    Important architectural rule:
    - mission execution may request workforce provisioning
    - mission execution must not create agents directly
    """

    def __init__(
        self,
        marketplace: ResourceMarketplace,
        event_bus: NATSEventBus,
        llm_service: LLMService,
        event_store: Optional["EventStore"] = None,
        execution_coordinator: Optional[ExecutionCoordinator] = None,
    ) -> None:
        self.marketplace = marketplace
        self.event_bus = event_bus
        self.llm_service = llm_service
        self.event_store = event_store

        self.agent_factory = AgentFactory(llm_service)
        self.workforce_provisioner = WorkforceProvisioner(self.agent_factory)
        self.execution_coordinator = execution_coordinator or ExecutionCoordinator()

        # Transitional compatibility seam:
        # process-local mission cache retained only until authoritative mission
        # lifecycle state is fully served from governed runtime ownership.
        self.active_missions: Dict[str, Dict[str, Any]] = {}
        self.status_callback = None

    def _record_active_mission_state(
        self,
        mission_id: str,
        status: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Transitional compatibility seam for process-local mission state.

        Purpose:
        - preserve current callback-driven status flow
        - centralize the only write path to in-memory mission state

        Replacement target:
        - coordinator/repository-backed mission status projection

        Removal condition:
        - all mission lifecycle reads come from governed runtime ownership

        Removal milestone:
        - Exit Transitional Runtime State
        """
        current_state = dict(self.active_missions.get(mission_id, {}))
        current_state.update(kwargs)
        current_state["mission_id"] = mission_id
        current_state["status"] = status
        self.active_missions[mission_id] = current_state
        return dict(current_state)

    def _get_active_mission_state(self, mission_id: str) -> Dict[str, Any]:
        """Return a copy of the current compatibility mission cache entry."""
        return dict(self.active_missions.get(mission_id, {}))

    def _list_active_mission_states(self) -> Dict[str, Dict[str, Any]]:
        """Return a copy of all compatibility mission cache entries."""
        return {
            mission_id: dict(state)
            for mission_id, state in self.active_missions.items()
        }

    def set_status_callback(self, callback) -> None:
        """
        Set callback for status updates.

        Args:
            callback: Async function(mission_id, status, **kwargs)
        """
        self.status_callback = callback

    async def _update_status(self, mission_id: str, status: str, **kwargs: Any) -> None:
        """
        Update mission status via callback and keep latest compatibility mission state.
        """
        self._record_active_mission_state(mission_id, status, **kwargs)

        if self.status_callback:
            try:
                await self.status_callback(mission_id, status, **kwargs)
            except Exception as e:
                logger.error("Status callback failed: %s", e)

    def get_mission_state(self, mission_id: str) -> Dict[str, Any]:
        """Return the latest known compatibility mission state."""
        return self._get_active_mission_state(mission_id)

    def list_active_mission_states(self) -> Dict[str, Dict[str, Any]]:
        """Return all tracked compatibility mission states."""
        return self._list_active_mission_states()

    async def execute_mission(
        self,
        mission_id: str,
        goal: str,
        tenant_id: str,
        user_id: str,
        budget: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute a mission end-to-end with full economy integration.
        """
        start_time = datetime.utcnow()

        with tracer.start_as_current_span("execute_mission") as span:
            span.set_attribute("mission_id", mission_id)
            span.set_attribute("tenant_id", tenant_id)

            try:
                await self._update_status(mission_id, "RUNNING")

                if self.event_store:
                    try:
                        await self.event_store.append(
                            aggregate_id=mission_id,
                            aggregate_type="mission",
                            event_type="mission.started",
                            data={
                                "goal": goal,
                                "tenant_id": tenant_id,
                                "user_id": user_id,
                                "budget": budget,
                                "timestamp": start_time.isoformat(),
                            },
                        )
                    except Exception as ev_err:
                        logger.warning("Event store append failed (non-fatal): %s", ev_err)

                await self._update_status(mission_id, "RUNNING", step="validation")
                validation_result = await self._validate_mission(mission_id, goal, tenant_id)

                if not validation_result["is_safe"]:
                    get_metrics().record_mission_complete(
                        status="REJECTED",
                        complexity="unknown",
                        duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                    )

                    await self._update_status(
                        mission_id,
                        "REJECTED",
                        error=validation_result["reason"],
                        risk_score=validation_result["risk_score"],
                    )
                    return {
                        "mission_id": mission_id,
                        "status": "REJECTED",
                        "reason": validation_result["reason"],
                        "risk_score": validation_result["risk_score"],
                    }

                await self._update_status(mission_id, "RUNNING", step="planning")
                plan = await self._create_execution_plan(mission_id, goal, tenant_id, budget)

                get_metrics().record_mission_start(
                    complexity=plan.get("complexity", "unknown")
                )

                await self._update_status(mission_id, "RUNNING", step="executing")
                if plan["complexity"] == MissionComplexity.SWARM.value:
                    result = await self._execute_with_swarm(mission_id, plan, tenant_id)
                else:
                    result = await self._execute_with_specialized_agents(
                        mission_id, goal, plan, tenant_id
                    )

                await self._update_status(mission_id, "RUNNING", step="archiving")
                await self._archive_mission(mission_id, goal, plan, result, tenant_id)

                if result["status"] == "SUCCESS":
                    await self._distribute_rewards(mission_id, plan, result, tenant_id)

                execution_state = (
                    self.execution_coordinator.get_authoritative_mission_execution_state(
                        mission_id
                    )
                )

                duration = (datetime.utcnow() - start_time).total_seconds()
                get_metrics().record_mission_complete(
                    status=result["status"],
                    complexity=plan.get("complexity", "unknown"),
                    duration_seconds=duration,
                )

                final_status = "COMPLETED" if result["status"] == "SUCCESS" else "FAILED"
                await self._update_status(
                    mission_id,
                    final_status,
                    result=result.get("output"),
                    cost=result.get("cost", 0.0),
                    execution_time=duration,
                    execution_state=execution_state,
                )

                if self.event_store:
                    try:
                        event_type = (
                            "mission.completed"
                            if result["status"] == "SUCCESS"
                            else "mission.failed"
                        )
                        await self.event_store.append(
                            aggregate_id=mission_id,
                            aggregate_type="mission",
                            event_type=event_type,
                            data={
                                "status": result["status"],
                                "cost": result.get("cost", 0.0),
                                "duration_seconds": duration,
                                "agents_used": result.get("agents_used", []),
                                "tenant_id": tenant_id,
                            },
                        )
                    except Exception as ev_err:
                        logger.warning("Event store append failed (non-fatal): %s", ev_err)

                primary_agent_id = plan.get("primary_agent_id", f"agent_{mission_id}")
                try:
                    asyncio.create_task(
                        governance_hooks.on_mission_completed(
                            mission_id=mission_id,
                            agent_id=primary_agent_id,
                            tenant_id=tenant_id,
                            status=result["status"],
                            result=result,
                        )
                    )
                except Exception as e:
                    logger.warning("Governance hook failed (non-blocking): %s", e)

                return {
                    "mission_id": mission_id,
                    "status": result["status"],
                    "output": result.get("output"),
                    "cost": result.get("cost", 0.0),
                    "duration_seconds": duration,
                    "agents_used": result.get("agents_used", []),
                    "execution_state": execution_state,
                }

            except Exception as e:
                span.record_exception(e)

                complexity = "unknown"
                if "plan" in locals() and isinstance(plan, dict):
                    complexity = plan.get("complexity", "unknown")

                get_metrics().record_mission_complete(
                    status="FAILED",
                    complexity=complexity,
                    duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                )

                await self._update_status(mission_id, "FAILED", error=str(e))

                if self.event_store:
                    try:
                        await self.event_store.append(
                            aggregate_id=mission_id,
                            aggregate_type="mission",
                            event_type="mission.failed",
                            data={
                                "error": str(e),
                                "tenant_id": tenant_id,
                                "duration_seconds": (
                                    datetime.utcnow() - start_time
                                ).total_seconds(),
                            },
                        )
                    except Exception as ev_err:
                        logger.warning("Event store append failed (non-fatal): %s", ev_err)

                return {"mission_id": mission_id, "status": "ERROR", "error": str(e)}

    async def _validate_mission(
        self,
        mission_id: str,
        goal: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """Guardian validates mission safety."""
        with tracer.start_as_current_span("guardian_validate"):
            get_metrics().record_agent_invocation("guardian", "gpt-4-turbo")

            llm = self.llm_service.get_llm("guardian", tenant_id)

            guardian_role = (
                "You are the Guardian, a safety validation agent. "
                "Your mandate is to protect the platform and its users by rigorously "
                "evaluating every mission before execution."
            )
            system_prompt = assemble_prompt(guardian_role)

            user_prompt = (
                f"Mission Goal: {goal}\n\n"
                "Analyze this mission for:\n"
                "1. Safety risks (harmful content, illegal activities, privacy violations)\n"
                "2. Resource requirements (computational cost, time estimate)\n"
                "3. Feasibility (can this actually be accomplished?)\n\n"
                "Respond in JSON format:\n"
                "{\n"
                '    "is_safe": true/false,\n'
                '    "risk_score": 0.0-1.0,\n'
                '    "reason": "explanation",\n'
                '    "estimated_cost": 0.0-100.0,\n'
                '    "estimated_duration_seconds": integer\n'
                "}"
            )

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]

            response = await llm.ainvoke(messages)

            try:
                result = json.loads(response.content)
            except Exception:
                result = {
                    "is_safe": True,
                    "risk_score": 0.1,
                    "reason": "Auto-approved (parsing failed)",
                    "estimated_cost": 1.0,
                    "estimated_duration_seconds": 30,
                }

            await self.event_bus.publish(
                "mission.validated",
                {
                    "mission_id": mission_id,
                    "is_safe": result["is_safe"],
                    "risk_score": result["risk_score"],
                },
            )

            return result

    async def _create_execution_plan(
        self,
        mission_id: str,
        goal: str,
        tenant_id: str,
        budget: Optional[float],
    ) -> Dict[str, Any]:
        """Commander creates execution plan."""
        with tracer.start_as_current_span("commander_plan"):
            get_metrics().record_agent_invocation("commander", "gpt-4-turbo")

            llm = self.llm_service.get_llm("commander", tenant_id)

            commander_role = (
                "You are the Commander, a strategic planning agent. "
                "Your role is to analyse mission goals and produce precise, "
                "cost-aware execution plans."
            )
            system_prompt = assemble_prompt(commander_role)

            budget_str = str(budget) if budget else "unlimited"
            user_prompt = (
                f"Mission Goal: {goal}\n"
                f"Available Budget: {budget_str} credits\n\n"
                "Create an execution plan:\n"
                "1. Break down the goal into steps\n"
                "2. Determine complexity level (simple/moderate/complex/swarm)\n"
                "3. Select which AI model to use (consider cost vs quality)\n"
                "4. Estimate total cost\n\n"
                "Respond in JSON format:\n"
                "{\n"
                '    "complexity": "simple|moderate|complex|swarm",\n'
                '    "steps": ["step 1", "step 2", ...],\n'
                '    "model_selection": "gpt-4|gpt-3.5|gemini-flash|claude-3.5",\n'
                '    "estimated_total_cost": 0.0,\n'
                '    "requires_tools": ["tool1", "tool2"]\n'
                "}"
            )

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]

            response = await llm.ainvoke(messages)

            try:
                plan = json.loads(response.content)
            except Exception:
                plan = {
                    "complexity": "simple",
                    "steps": [goal],
                    "model_selection": "gpt-3.5-turbo",
                    "estimated_total_cost": 0.5,
                    "requires_tools": [],
                }

            if "primary_agent_id" not in plan:
                plan["primary_agent_id"] = f"agent_{mission_id}"

            await self.event_bus.publish(
                "mission.planned",
                {
                    "mission_id": mission_id,
                    "complexity": plan["complexity"],
                    "estimated_cost": plan["estimated_total_cost"],
                },
            )

            return plan

    async def _execute_with_specialized_agents(
        self,
        mission_id: str,
        goal: str,
        plan: Dict[str, Any],
        tenant_id: str,
    ) -> Dict[str, Any]:
        """
        Execute mission with specialized agents.

        Architectural rule:
        - this method requests provisioning
        - this method must not create agents directly
        """
        with tracer.start_as_current_span("execute_specialized_agents"):
            try:
                plan_with_mission_id = dict(plan)
                plan_with_mission_id["mission_id"] = mission_id

                agent = await self.workforce_provisioner.provision_agent_for_mission(
                    mission_goal=goal,
                    plan=plan_with_mission_id,
                    tenant_id=tenant_id,
                )

                if agent is None:
                    logger.info(
                        "Mission %s: Using simple execution (no specialized agent needed)",
                        mission_id,
                    )
                    return await self._execute_with_agents(mission_id, plan, tenant_id)

                agent_type = agent.agent_type
                fleet_id = getattr(agent, "fleet_id", None)
                branch_id = plan.get("branch_id")

                logger.info(
                    "Mission %s: Using %s agent with reasoning workflow",
                    mission_id,
                    agent_type,
                )

                await self.marketplace.charge(
                    tenant_id=tenant_id,
                    agent_id=agent.agent_id,
                    amount=2.0,
                    resource_type=ResourceType.LLM_CALL.value,
                    mission_id=mission_id,
                    agent_type=agent_type,
                    fleet_id=fleet_id,
                    branch_id=branch_id,
                )

                if agent_type == "researcher":
                    task = ExecutionTask(
                        id=f"task_{mission_id}_{agent.agent_id}",
                        mission_id=mission_id,
                        tenant_id=tenant_id,
                        title="Research Task",
                        objective=goal,
                        task_type=ExecutionTaskType.RESEARCH,
                        fleet_id=fleet_id,
                        assigned_agent_id=agent.agent_id,
                        branch_id=branch_id,
                        input_payload={
                            "query": goal,
                            "depth": (
                                "standard"
                                if plan.get("complexity") != "complex"
                                else "deep"
                            ),
                        },
                        metadata={
                            "source": "mission_executor",
                            "agent_type": agent_type,
                        },
                    )
                elif agent_type == "analyst":
                    task = ExecutionTask(
                        id=f"task_{mission_id}_{agent.agent_id}",
                        mission_id=mission_id,
                        tenant_id=tenant_id,
                        title="Analysis Task",
                        objective=goal,
                        task_type=ExecutionTaskType.ANALYSIS,
                        fleet_id=fleet_id,
                        assigned_agent_id=agent.agent_id,
                        branch_id=branch_id,
                        input_payload={
                            "data": plan.get("data", {}),
                            "analysis_type": "descriptive",
                        },
                        metadata={
                            "source": "mission_executor",
                            "agent_type": agent_type,
                        },
                    )
                elif agent_type == "developer":
                    task = ExecutionTask(
                        id=f"task_{mission_id}_{agent.agent_id}",
                        mission_id=mission_id,
                        tenant_id=tenant_id,
                        title="Development Task",
                        objective=goal,
                        task_type=ExecutionTaskType.GENERATION,
                        fleet_id=fleet_id,
                        assigned_agent_id=agent.agent_id,
                        branch_id=branch_id,
                        input_payload={
                            "task_type": "generate",
                            "specification": goal,
                        },
                        metadata={
                            "source": "mission_executor",
                            "agent_type": agent_type,
                        },
                    )
                else:
                    task = ExecutionTask(
                        id=f"task_{mission_id}_{agent.agent_id}",
                        mission_id=mission_id,
                        tenant_id=tenant_id,
                        title="Generic Task",
                        objective=goal,
                        task_type=ExecutionTaskType.GENERIC,
                        fleet_id=fleet_id,
                        assigned_agent_id=agent.agent_id,
                        branch_id=branch_id,
                        input_payload={"query": goal},
                        metadata={
                            "source": "mission_executor",
                            "agent_type": agent_type,
                        },
                    )

                execution_context = self.execution_coordinator.build_task_execution_context(
                    mission_id=mission_id,
                    tenant_id=tenant_id,
                    objective=goal,
                    fleet=getattr(agent, "fleet", None),
                    task=task,
                    branch_id=branch_id,
                    metadata={
                        "source": "mission_executor",
                        "agent_type": agent_type,
                    },
                )

                result = await agent.execute(task.model_dump())

                base_cost = 2.0
                reasoning_cost = 1.0 * len(plan.get("steps", []))
                tool_cost = 0.5 * len(plan.get("requires_tools", []))
                total_cost = base_cost + reasoning_cost + tool_cost

                if reasoning_cost + tool_cost > 0:
                    await self.marketplace.charge(
                        tenant_id=tenant_id,
                        agent_id=agent.agent_id,
                        amount=reasoning_cost + tool_cost,
                        resource_type=ResourceType.LLM_CALL.value,
                        mission_id=mission_id,
                        agent_type=agent_type,
                        fleet_id=fleet_id,
                        task_id=task.id,
                        branch_id=branch_id,
                    )

                if result.get("success"):
                    if agent_type == "researcher":
                        output = result.get("synthesis", "")
                        sources = result.get("sources", [])
                        if sources:
                            output += "\n\nSources:\n"
                            for i, source in enumerate(sources[:5], 1):
                                output += (
                                    f"{i}. {source.get('title', 'Unknown')} - "
                                    f"{source.get('url', '')}\n"
                                )
                    elif agent_type == "analyst":
                        output = result.get("insights", "")
                        calculations = result.get("calculations", {})
                        if calculations:
                            output += "\n\nKey Metrics:\n"
                            for key, value in calculations.items():
                                output += f"- {key}: {value}\n"
                    elif agent_type == "developer":
                        output = result.get("code", result.get("analysis", ""))
                    else:
                        output = str(result)

                    return {
                        "status": "SUCCESS",
                        "output": output,
                        "cost": total_cost,
                        "agents_used": ["commander", "guardian", agent_type],
                        "agent_type": agent_type,
                        "reasoning_used": True,
                        "tools_used": plan.get("requires_tools", []),
                        "execution_context": execution_context,
                        "fleet_id": fleet_id,
                        "branch_id": branch_id,
                    }

                error_msg = result.get("error", "Unknown error")
                logger.error(
                    "Mission %s: %s agent failed: %s",
                    mission_id,
                    agent_type,
                    error_msg,
                )

                return {
                    "status": "FAILED",
                    "output": f"Agent execution failed: {error_msg}",
                    "cost": total_cost,
                    "agents_used": ["commander", "guardian", agent_type],
                    "error": error_msg,
                    "execution_context": execution_context,
                    "fleet_id": fleet_id,
                    "branch_id": branch_id,
                }

            except Exception as e:
                logger.error(
                    "Mission %s: Specialized agent execution failed: %s",
                    mission_id,
                    e,
                )
                logger.info("Mission %s: Falling back to simple execution", mission_id)
                return await self._execute_with_agents(mission_id, plan, tenant_id)

    async def _execute_with_agents(
        self,
        mission_id: str,
        plan: Dict[str, Any],
        tenant_id: str,
    ) -> Dict[str, Any]:
        """Execute mission with standard agents."""
        with tracer.start_as_current_span("execute_agents"):
            total_cost = 0.0
            outputs = []

            model_name = "gpt-3.5-turbo"
            llm = self.llm_service.get_llm_by_model(model_name, tenant_id)

            task = ExecutionTask(
                id=f"task_{mission_id}_executor",
                mission_id=mission_id,
                tenant_id=tenant_id,
                title="Standard Mission Execution",
                objective=plan.get("goal", "Execute standard mission plan"),
                task_type=ExecutionTaskType.GENERIC,
                branch_id=plan.get("branch_id"),
                input_payload={
                    "steps": plan.get("steps", []),
                    "complexity": plan.get("complexity"),
                },
                metadata={
                    "source": "mission_executor",
                    "agent_type": "executor",
                    "execution_mode": "standard",
                },
            )

            execution_context = self.execution_coordinator.build_task_execution_context(
                mission_id=mission_id,
                tenant_id=tenant_id,
                objective=task.objective,
                task=task,
                branch_id=plan.get("branch_id"),
                metadata={
                    "source": "mission_executor",
                    "execution_mode": "standard",
                },
            )

            for i, step in enumerate(plan["steps"]):
                get_metrics().record_agent_invocation("executor", model_name)

                await self.marketplace.charge(
                    tenant_id=tenant_id,
                    agent_id=f"agent_executor_{i}",
                    amount=1.0,
                    resource_type=ResourceType.LLM_CALL.value,
                    mission_id=mission_id,
                    agent_type="executor",
                    task_id=task.id,
                    branch_id=plan.get("branch_id"),
                )
                cost = 1.0

                executor_role = (
                    "You are a mission executor. Complete the assigned step "
                    "thoroughly and return a detailed result."
                )
                step_system = assemble_prompt(executor_role)
                step_messages = [
                    SystemMessage(content=step_system),
                    HumanMessage(content=step),
                ]
                response = await llm.ainvoke(step_messages)
                outputs.append(response.content)
                total_cost += cost

            return {
                "status": "SUCCESS",
                "output": "\n\n".join(outputs),
                "cost": total_cost,
                "agents_used": ["commander", "guardian", "executor"],
                "agent_type": "executor",
                "reasoning_used": False,
                "tools_used": plan.get("requires_tools", []),
                "fleet_id": None,
                "branch_id": plan.get("branch_id"),
                "execution_context": execution_context,
            }

    async def _execute_with_swarm(
        self,
        mission_id: str,
        plan: Dict[str, Any],
        tenant_id: str,
    ) -> Dict[str, Any]:
        """Execute mission with dynamic swarm."""
        with tracer.start_as_current_span("execute_swarm"):
            tasks = []
            for step in plan["steps"]:
                task = self._execute_swarm_agent(mission_id, step, tenant_id)
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            swarm_task = ExecutionTask(
                id=f"task_{mission_id}_swarm",
                mission_id=mission_id,
                tenant_id=tenant_id,
                title="Swarm Mission Execution",
                objective=plan.get("goal", "Execute swarm mission plan"),
                task_type=ExecutionTaskType.COORDINATION,
                branch_id=plan.get("branch_id"),
                input_payload={
                    "steps": plan.get("steps", []),
                    "complexity": plan.get("complexity"),
                    "execution_mode": "swarm",
                },
                metadata={
                    "source": "mission_executor",
                    "agent_type": "swarm",
                    "execution_mode": "swarm",
                },
            )

            execution_context = self.execution_coordinator.build_task_execution_context(
                mission_id=mission_id,
                tenant_id=tenant_id,
                objective=swarm_task.objective,
                task=swarm_task,
                branch_id=plan.get("branch_id"),
                metadata={
                    "source": "mission_executor",
                    "execution_mode": "swarm",
                },
            )

            total_cost = sum(
                r.get("cost", 0) for r in results if isinstance(r, dict)
            )
            outputs = [
                r.get("output", "") for r in results if isinstance(r, dict)
            ]

            return {
                "status": "SUCCESS",
                "output": "\n\n".join(outputs),
                "cost": total_cost,
                "agents_used": ["swarm"] * len(results),
                "agent_type": "swarm",
                "reasoning_used": True,
                "tools_used": plan.get("requires_tools", []),
                "fleet_id": None,
                "branch_id": plan.get("branch_id"),
                "execution_context": execution_context,
            }

    async def _execute_swarm_agent(
        self,
        mission_id: str,
        task: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """Execute a single swarm agent."""
        get_metrics().record_agent_invocation("swarm_agent", "gpt-3.5-turbo")

        llm = self.llm_service.get_llm_by_model("gpt-3.5-turbo", tenant_id)

        await self.marketplace.charge(
            tenant_id=tenant_id,
            agent_id=f"swarm_agent_{uuid.uuid4().hex[:8]}",
            amount=0.5,
            resource_type=ResourceType.LLM_CALL.value,
            mission_id=mission_id,
            agent_type="swarm_agent",
            branch_id=None,
        )
        cost = 0.5

        swarm_role = (
            "You are a swarm agent operating as part of a parallel execution team. "
            "Complete your assigned task with precision and return a clear result."
        )
        swarm_system = assemble_prompt(swarm_role)
        swarm_messages = [
            SystemMessage(content=swarm_system),
            HumanMessage(content=task),
        ]
        response = await llm.ainvoke(swarm_messages)

        return {"output": response.content, "cost": cost}

    async def _archive_mission(
        self,
        mission_id: str,
        goal: str,
        plan: Dict[str, Any],
        result: Dict[str, Any],
        tenant_id: str,
    ) -> None:
        """Archivist records mission for future learning."""
        with tracer.start_as_current_span("archivist_archive"):
            get_metrics().record_agent_invocation("archivist", "gpt-4-turbo")

            execution_state = (
                self.execution_coordinator.get_authoritative_mission_execution_state(
                    mission_id
                )
            )

            await self.event_bus.publish(
                "mission.completed",
                {
                    "mission_id": mission_id,
                    "goal": goal,
                    "status": result["status"],
                    "cost": result.get("cost", 0.0),
                    "complexity": plan["complexity"],
                    "execution_state": execution_state,
                },
            )

            logger.info("Mission %s archived: %s", mission_id, result["status"])

    async def _distribute_rewards(
        self,
        mission_id: str,
        plan: Dict[str, Any],
        result: Dict[str, Any],
        tenant_id: str,
    ) -> None:
        """Distribute rewards to successful agents."""
        with tracer.start_as_current_span("distribute_rewards"):
            complexity_multiplier = {
                "simple": 1.0,
                "moderate": 1.5,
                "complex": 2.0,
                "swarm": 3.0,
            }

            base_reward = 10.0
            multiplier = complexity_multiplier.get(plan["complexity"], 1.0)
            total_reward = base_reward * multiplier

            agents_used = result.get("agents_used", [])
            reward_per_agent = total_reward / len(agents_used) if agents_used else 0.0

            for agent_name in agents_used:
                await self.marketplace.reward(
                    tenant_id=tenant_id,
                    agent_id=agent_name,
                    amount=reward_per_agent,
                    resource_type="mission_reward",
                    mission_id=mission_id,
                    agent_type="executor",
                )

            await self.event_bus.publish(
                "rewards.distributed",
                {
                    "mission_id": mission_id,
                    "total_reward": total_reward,
                    "agents": agents_used,
                },
            )
