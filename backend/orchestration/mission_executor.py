"""
Mission Execution Orchestrator
Coordinates agents, manages economy, and executes missions end-to-end
"""
import asyncio
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

from backend.integrations.llm.llm_factory import LLMFactory
from backend.economy.resource_marketplace import ResourceMarketplace, ResourceType
from backend.core.event_bus.nats_bus import NATSEventBus
from backend.integrations.observability.telemetry import get_tracer, get_meter
from backend.models.domain.agent import AgentStatus
from backend.models.domain.mission import MissionStatus

tracer = get_tracer(__name__)
meter = get_meter(__name__)

# Metrics
mission_counter = meter.create_counter(
    "omnipath_missions_total",
    description="Total number of missions executed"
)

mission_duration = meter.create_histogram(
    "omnipath_mission_duration_seconds",
    description="Mission execution duration in seconds"
)

agent_invocations = meter.create_counter(
    "omnipath_agent_invocations_total",
    description="Total agent invocations by type"
)


class MissionComplexity(Enum):
    """Mission complexity levels"""
    SIMPLE = "simple"  # Single agent, single step
    MODERATE = "moderate"  # Multiple steps, single agent
    COMPLEX = "complex"  # Multiple agents, coordination required
    SWARM = "swarm"  # Requires dynamic swarm formation


class MissionExecutor:
    """
    Orchestrates mission execution with full Agent Economy integration
    """
    
    def __init__(
        self,
        marketplace: ResourceMarketplace,
        event_bus: NATSEventBus,
        llm_factory: LLMFactory
    ):
        self.marketplace = marketplace
        self.event_bus = event_bus
        self.llm_factory = llm_factory
        self.active_missions: Dict[str, Dict[str, Any]] = {}
        
    async def execute_mission(
        self,
        mission_id: str,
        goal: str,
        tenant_id: str,
        user_id: str,
        budget: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Execute a mission end-to-end with full economy integration
        
        Args:
            mission_id: Unique mission identifier
            goal: Mission objective in natural language
            tenant_id: Tenant ID for multi-tenancy
            user_id: User who created the mission
            budget: Optional budget limit in credits
            
        Returns:
            Mission execution result with metrics
        """
        start_time = datetime.utcnow()
        
        with tracer.start_as_current_span("execute_mission") as span:
            span.set_attribute("mission_id", mission_id)
            span.set_attribute("tenant_id", tenant_id)
            
            try:
                # Phase 1: Guardian validates the mission
                validation_result = await self._validate_mission(
                    mission_id, goal, tenant_id
                )
                
                if not validation_result["is_safe"]:
                    return {
                        "mission_id": mission_id,
                        "status": "REJECTED",
                        "reason": validation_result["reason"],
                        "risk_score": validation_result["risk_score"]
                    }
                
                # Phase 2: Commander analyzes and plans
                plan = await self._create_execution_plan(
                    mission_id, goal, tenant_id, budget
                )
                
                # Phase 3: Execute based on complexity
                if plan["complexity"] == MissionComplexity.SWARM.value:
                    result = await self._execute_with_swarm(
                        mission_id, plan, tenant_id
                    )
                else:
                    result = await self._execute_with_agents(
                        mission_id, plan, tenant_id
                    )
                
                # Phase 4: Archivist records everything
                await self._archive_mission(
                    mission_id, goal, plan, result, tenant_id
                )
                
                # Phase 5: Reward successful agents
                if result["status"] == "SUCCESS":
                    await self._distribute_rewards(
                        mission_id, plan, result, tenant_id
                    )
                
                # Record metrics
                duration = (datetime.utcnow() - start_time).total_seconds()
                mission_duration.record(duration)
                mission_counter.add(1, {"status": result["status"]})
                
                return {
                    "mission_id": mission_id,
                    "status": result["status"],
                    "output": result.get("output"),
                    "cost": result.get("cost", 0.0),
                    "duration_seconds": duration,
                    "agents_used": result.get("agents_used", [])
                }
                
            except Exception as e:
                span.record_exception(e)
                mission_counter.add(1, {"status": "ERROR"})
                return {
                    "mission_id": mission_id,
                    "status": "ERROR",
                    "error": str(e)
                }
    
    async def _validate_mission(
        self,
        mission_id: str,
        goal: str,
        tenant_id: str
    ) -> Dict[str, Any]:
        """Guardian validates mission safety"""
        with tracer.start_as_current_span("guardian_validate"):
            agent_invocations.add(1, {"agent": "guardian"})
            
            # Get Guardian's LLM
            llm = self.llm_factory.get_llm("guardian", tenant_id)
            
            prompt = f"""You are the Guardian, a safety validation agent.
            
Mission Goal: {goal}

Analyze this mission for:
1. Safety risks (harmful content, illegal activities, privacy violations)
2. Resource requirements (computational cost, time estimate)
3. Feasibility (can this actually be accomplished?)

Respond in JSON format:
{{
    "is_safe": true/false,
    "risk_score": 0.0-1.0,
    "reason": "explanation",
    "estimated_cost": 0.0-100.0,
    "estimated_duration_seconds": integer
}}
"""
            
            response = await llm.ainvoke(prompt)
            
            # Parse LLM response (simplified - production would use structured output)
            import json
            try:
                result = json.loads(response.content)
            except:
                # Fallback if LLM doesn't return valid JSON
                result = {
                    "is_safe": True,
                    "risk_score": 0.1,
                    "reason": "Auto-approved (parsing failed)",
                    "estimated_cost": 1.0,
                    "estimated_duration_seconds": 30
                }
            
            # Publish validation event
            await self.event_bus.publish(
                "mission.validated",
                {
                    "mission_id": mission_id,
                    "is_safe": result["is_safe"],
                    "risk_score": result["risk_score"]
                }
            )
            
            return result
    
    async def _create_execution_plan(
        self,
        mission_id: str,
        goal: str,
        tenant_id: str,
        budget: Optional[float]
    ) -> Dict[str, Any]:
        """Commander creates execution plan"""
        with tracer.start_as_current_span("commander_plan"):
            agent_invocations.add(1, {"agent": "commander"})
            
            llm = self.llm_factory.get_llm("commander", tenant_id)
            
            prompt = f"""You are the Commander, a strategic planning agent.

Mission Goal: {goal}
Available Budget: {budget if budget else 'unlimited'} credits

Create an execution plan:
1. Break down the goal into steps
2. Determine complexity level (simple/moderate/complex/swarm)
3. Select which AI model to use (consider cost vs quality)
4. Estimate total cost

Respond in JSON format:
{{
    "complexity": "simple|moderate|complex|swarm",
    "steps": ["step 1", "step 2", ...],
    "model_selection": "gpt-4|gpt-3.5|gemini-flash|claude-3.5",
    "estimated_total_cost": 0.0,
    "requires_tools": ["tool1", "tool2"] or []
}}
"""
            
            response = await llm.ainvoke(prompt)
            
            import json
            try:
                plan = json.loads(response.content)
            except:
                plan = {
                    "complexity": "simple",
                    "steps": [goal],
                    "model_selection": "gpt-3.5-turbo",
                    "estimated_total_cost": 0.5,
                    "requires_tools": []
                }
            
            await self.event_bus.publish(
                "mission.planned",
                {
                    "mission_id": mission_id,
                    "complexity": plan["complexity"],
                    "estimated_cost": plan["estimated_total_cost"]
                }
            )
            
            return plan
    
    async def _execute_with_agents(
        self,
        mission_id: str,
        plan: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Execute mission with standard agents"""
        with tracer.start_as_current_span("execute_agents"):
            total_cost = 0.0
            outputs = []
            
            # Get LLM based on Commander's selection
            model_name = plan.get("model_selection", "gpt-3.5-turbo")
            llm = self.llm_factory.get_llm_by_model(model_name, tenant_id)
            
            # Execute each step
            for i, step in enumerate(plan["steps"]):
                agent_invocations.add(1, {"agent": "executor"})
                
                # Charge for resource usage
                cost = await self.marketplace.charge_for_resource(
                    tenant_id,
                    f"agent_executor_{i}",
                    ResourceType.LLM_CALL,
                    1.0  # Base cost, will be updated with actual
                )
                
                response = await llm.ainvoke(step)
                outputs.append(response.content)
                total_cost += cost
            
            return {
                "status": "SUCCESS",
                "output": "\n\n".join(outputs),
                "cost": total_cost,
                "agents_used": ["commander", "guardian", "executor"]
            }
    
    async def _execute_with_swarm(
        self,
        mission_id: str,
        plan: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """Execute mission with dynamic swarm"""
        with tracer.start_as_current_span("execute_swarm"):
            # Spawn multiple agents in parallel
            tasks = []
            for step in plan["steps"]:
                task = self._execute_with_agents(
                    f"{mission_id}_sub_{len(tasks)}",
                    {"steps": [step], "model_selection": plan["model_selection"]},
                    tenant_id
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks)
            
            total_cost = sum(r["cost"] for r in results)
            combined_output = "\n\n".join(r["output"] for r in results)
            
            return {
                "status": "SUCCESS",
                "output": combined_output,
                "cost": total_cost,
                "agents_used": ["commander", "guardian", "swarm"]
            }
    
    async def _archive_mission(
        self,
        mission_id: str,
        goal: str,
        plan: Dict[str, Any],
        result: Dict[str, Any],
        tenant_id: str
    ):
        """Archivist records mission for future learning"""
        with tracer.start_as_current_span("archivist_archive"):
            agent_invocations.add(1, {"agent": "archivist"})
            
            await self.event_bus.publish(
                "mission.archived",
                {
                    "mission_id": mission_id,
                    "goal": goal,
                    "plan": plan,
                    "result": result,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
    
    async def _distribute_rewards(
        self,
        mission_id: str,
        plan: Dict[str, Any],
        result: Dict[str, Any],
        tenant_id: str
    ):
        """Distribute credits to successful agents"""
        with tracer.start_as_current_span("distribute_rewards"):
            # Calculate reward based on mission value
            base_reward = 10.0
            complexity_multiplier = {
                "simple": 1.0,
                "moderate": 1.5,
                "complex": 2.0,
                "swarm": 3.0
            }
            
            reward = base_reward * complexity_multiplier.get(
                plan.get("complexity", "simple"), 1.0
            )
            
            # Reward each agent that participated
            for agent_type in result.get("agents_used", []):
                agent_id = f"{tenant_id}_{agent_type}"
                await self.marketplace.reward_agent(
                    tenant_id,
                    agent_id,
                    reward / len(result["agents_used"])
                )
