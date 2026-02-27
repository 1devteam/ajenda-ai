"""
Mission Execution Orchestrator
Coordinates agents, manages economy, and executes missions end-to-end
"""
import asyncio
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

from backend.integrations.llm.llm_service import LLMService
from backend.economy.resource_marketplace import ResourceType, ResourceMarketplace
from backend.core.event_bus.nats_bus import NATSEventBus
from backend.integrations.observability.telemetry import get_tracer, get_meter
from backend.models.domain.agent import AgentStatus
from backend.models.domain.mission import MissionStatus
from backend.integrations.observability.prometheus_metrics import get_metrics
from backend.agents.factory.agent_factory import AgentFactory
from backend.agents.integration.governance_hooks import governance_hooks

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)
meter = get_meter(__name__)
# Get metrics instance inside methods to avoid early initialization issues


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
        llm_service: LLMService
    ):
        self.marketplace = marketplace
        self.event_bus = event_bus
        self.llm_service = llm_service
        self.agent_factory = AgentFactory(llm_service)
        self.active_missions: Dict[str, Dict[str, Any]] = {}
        self.status_callback = None
    
    def set_status_callback(self, callback):
        """
        Set callback for status updates
        
        Args:
            callback: Async function(mission_id, status, **kwargs)
        """
        self.status_callback = callback
    
    async def _update_status(self, mission_id: str, status: str, **kwargs):
        """
        Update mission status via callback
        
        Args:
            mission_id: Mission identifier
            status: New status
            **kwargs: Additional data (result, error, execution_time, etc.)
        """
        if self.status_callback:
            try:
                await self.status_callback(mission_id, status, **kwargs)
            except Exception as e:
                logger.error(f"Status callback failed: {e}")
        
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
                # Initial status update
                await self._update_status(mission_id, "RUNNING")
                
                # Governance hook: Check if mission can proceed
                # Note: agent_id would come from plan, using placeholder for now
                # TODO: Get actual agent_id from plan after planning phase
                
                # Phase 1: Guardian validates the mission
                await self._update_status(mission_id, "RUNNING", step="validation")
                validation_result = await self._validate_mission(
                    mission_id, goal, tenant_id
                )
                
                if not validation_result["is_safe"]:
                    # Record rejected metric
                    get_metrics().record_mission_complete(
                        status="REJECTED",
                        complexity="unknown",
                        duration_seconds=(datetime.utcnow() - start_time).total_seconds()
                    )
                    
                    await self._update_status(
                        mission_id, 
                        "REJECTED", 
                        error=validation_result["reason"],
                        risk_score=validation_result["risk_score"]
                    )
                    return {
                        "mission_id": mission_id,
                        "status": "REJECTED",
                        "reason": validation_result["reason"],
                        "risk_score": validation_result["risk_score"]
                    }
                
                # Phase 2: Commander analyzes and plans
                await self._update_status(mission_id, "RUNNING", step="planning")
                plan = await self._create_execution_plan(
                    mission_id, goal, tenant_id, budget
                )
                
                # Update status to RUNNING with complexity
                get_metrics().record_mission_start(complexity=plan.get("complexity", "unknown"))
                
                # Phase 3: Execute based on complexity
                await self._update_status(mission_id, "RUNNING", step="executing")
                if plan["complexity"] == MissionComplexity.SWARM.value:
                    result = await self._execute_with_swarm(
                        mission_id, plan, tenant_id
                    )
                else:
                    # Use specialized agents with reasoning workflows
                    result = await self._execute_with_specialized_agents(
                        mission_id, goal, plan, tenant_id
                    )
                
                # Phase 4: Archivist records everything
                await self._update_status(mission_id, "RUNNING", step="archiving")
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
                get_metrics().record_mission_complete(
                    status=result["status"],
                    complexity=plan.get("complexity", "unknown"),
                    duration_seconds=duration
                )
                
                # Update final status
                final_status = "COMPLETED" if result["status"] == "SUCCESS" else "FAILED"
                await self._update_status(
                    mission_id,
                    final_status,
                    result=result.get("output"),
                    cost=result.get("cost", 0.0),
                    execution_time=duration
                )
                
                # Governance hook: Record mission completion
                # TODO: Get actual agent_id from plan
                try:
                    asyncio.create_task(
                        governance_hooks.on_mission_completed(
                            mission_id=mission_id,
                            agent_id="system",  # Placeholder
                            tenant_id=tenant_id,
                            status=result["status"],
                            result=result
                        )
                    )
                except Exception as e:
                    logger.warning(f"Governance hook failed (non-blocking): {e}")
                
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
                # Determine complexity for metric
                comp = "unknown"
                if 'plan' in locals() and isinstance(plan, dict):
                    comp = plan.get("complexity", "unknown")
                
                get_metrics().record_mission_complete(
                    status="FAILED",
                    complexity=comp,
                    duration_seconds=(datetime.utcnow() - start_time).total_seconds()
                )
                
                # Update status to FAILED
                await self._update_status(mission_id, "FAILED", error=str(e))
                
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
            get_metrics().record_agent_invocation("guardian", "gpt-4-turbo")
            
            # Get Guardian's LLM
            llm = self.llm_service.get_llm("guardian", tenant_id)
            
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
            get_metrics().record_agent_invocation("commander", "gpt-4-turbo")
            
            llm = self.llm_service.get_llm("commander", tenant_id)
            
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
    
    async def _execute_with_specialized_agents(
        self,
        mission_id: str,
        goal: str,
        plan: Dict[str, Any],
        tenant_id: str
    ) -> Dict[str, Any]:
        """
        Execute mission with specialized agents (Researcher, Analyst, Developer).
        
        This method intelligently selects the appropriate specialized agent based on
        the mission goal and plan, then executes the mission using the agent's
        reasoning workflow and tool-calling capabilities.
        
        Args:
            mission_id: Mission identifier
            goal: Mission objective
            plan: Execution plan from Commander
            tenant_id: Tenant ID
            
        Returns:
            Mission execution result with outputs and costs
        """
        with tracer.start_as_current_span("execute_specialized_agents"):
            try:
                # Create appropriate specialized agent for this mission
                agent = self.agent_factory.create_agent_for_mission(
                    mission_goal=goal,
                    plan=plan,
                    tenant_id=tenant_id
                )
                
                # If no specialized agent needed, fall back to simple execution
                if agent is None:
                    logger.info(f"Mission {mission_id}: Using simple execution (no specialized agent needed)")
                    return await self._execute_with_agents(mission_id, plan, tenant_id)
                
                # Log agent selection
                agent_type = agent.agent_type
                logger.info(f"Mission {mission_id}: Using {agent_type} agent with reasoning workflow")
                
                # Charge initial cost for agent invocation
                await self.marketplace.charge(
                    tenant_id=tenant_id,
                    agent_id=agent.agent_id,
                    amount=2.0,  # Base cost for specialized agent
                    resource_type=ResourceType.LLM_CALL.value,
                    mission_id=mission_id,
                    agent_type=agent_type
                )
                
                # Prepare task based on agent type
                if agent_type == "researcher":
                    task = {
                        "query": goal,
                        "depth": "standard" if plan.get("complexity") != "complex" else "deep"
                    }
                elif agent_type == "analyst":
                    task = {
                        "data": plan.get("data", {}),
                        "analysis_type": "descriptive"  # Could be inferred from goal
                    }
                elif agent_type == "developer":
                    task = {
                        "task_type": "generate",  # Could be: generate, debug, review, test
                        "specification": goal
                    }
                else:
                    task = {"query": goal}
                
                # Execute with specialized agent
                result = await agent.execute(task)
                
                # Calculate total cost (base + reasoning steps + tool usage)
                # For now, use a simple cost model
                base_cost = 2.0
                reasoning_cost = 1.0 * len(plan.get("steps", []))  # Cost per reasoning step
                tool_cost = 0.5 * len(plan.get("requires_tools", []))  # Cost per tool
                total_cost = base_cost + reasoning_cost + tool_cost
                
                # Charge additional costs if needed
                if reasoning_cost + tool_cost > 0:
                    await self.marketplace.charge(
                        tenant_id=tenant_id,
                        agent_id=agent.agent_id,
                        amount=reasoning_cost + tool_cost,
                        resource_type=ResourceType.LLM_CALL.value,
                        mission_id=mission_id,
                        agent_type=agent_type
                    )
                
                # Format result
                if result.get("success"):
                    # Extract output based on agent type
                    if agent_type == "researcher":
                        output = result.get("synthesis", "")
                        # Include sources in output
                        sources = result.get("sources", [])
                        if sources:
                            output += "\n\nSources:\n"
                            for i, source in enumerate(sources[:5], 1):
                                output += f"{i}. {source.get('title', 'Unknown')} - {source.get('url', '')}\n"
                    elif agent_type == "analyst":
                        output = result.get("insights", "")
                        # Include calculations
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
                        "tools_used": plan.get("requires_tools", [])
                    }
                else:
                    # Agent execution failed, return error
                    error_msg = result.get("error", "Unknown error")
                    logger.error(f"Mission {mission_id}: {agent_type} agent failed: {error_msg}")
                    
                    return {
                        "status": "FAILED",
                        "output": f"Agent execution failed: {error_msg}",
                        "cost": total_cost,
                        "agents_used": ["commander", "guardian", agent_type],
                        "error": error_msg
                    }
            
            except Exception as e:
                logger.error(f"Mission {mission_id}: Specialized agent execution failed: {e}")
                # Fall back to simple execution on error
                logger.info(f"Mission {mission_id}: Falling back to simple execution")
                return await self._execute_with_agents(mission_id, plan, tenant_id)
    
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
            # Force OpenAI for now (Quick Fix - Option A)
            model_name = "gpt-3.5-turbo"
            llm = self.llm_service.get_llm_by_model(model_name, tenant_id)
            
            # Execute each step
            for i, step in enumerate(plan["steps"]):
                get_metrics().record_agent_invocation("executor", model_name)
                
                # Charge for resource usage
                await self.marketplace.charge(
                    tenant_id=tenant_id,
                    agent_id=f"agent_executor_{i}",
                    amount=1.0,  # Base cost, will be updated with actual
                    resource_type=ResourceType.LLM_CALL.value,
                    mission_id=None,
                    agent_type="executor"
                )
                cost = 1.0
                
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
                task = self._execute_swarm_agent(
                    mission_id, step, tenant_id
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Aggregate results
            total_cost = sum(r.get("cost", 0) for r in results if isinstance(r, dict))
            outputs = [r.get("output", "") for r in results if isinstance(r, dict)]
            
            return {
                "status": "SUCCESS",
                "output": "\n\n".join(outputs),
                "cost": total_cost,
                "agents_used": ["swarm"] * len(results)
            }
    
    async def _execute_swarm_agent(
        self,
        mission_id: str,
        task: str,
        tenant_id: str
    ) -> Dict[str, Any]:
        """Execute a single swarm agent"""
        get_metrics().record_agent_invocation("swarm_agent", "gpt-3.5-turbo")
        
        llm = self.llm_service.get_llm_by_model("gpt-3.5-turbo", tenant_id)
        
        await self.marketplace.charge(
            tenant_id=tenant_id,
            agent_id=f"swarm_agent_{uuid.uuid4().hex[:8]}",
            amount=0.5,
            resource_type=ResourceType.LLM_CALL.value,
            mission_id=None,
            agent_type="swarm_agent"
        )
        cost = 0.5
        
        response = await llm.ainvoke(task)
        
        return {
            "output": response.content,
            "cost": cost
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
            get_metrics().record_agent_invocation("archivist", "gpt-4-turbo")
            
            # Publish mission completion event
            await self.event_bus.publish(
                "mission.completed",
                {
                    "mission_id": mission_id,
                    "goal": goal,
                    "status": result["status"],
                    "cost": result.get("cost", 0.0),
                    "complexity": plan["complexity"]
                }
            )
            
            # In production, this would save to database
            # For now, just log it
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Mission {mission_id} archived: {result['status']}")
    
    async def _distribute_rewards(
        self,
        mission_id: str,
        plan: Dict[str, Any],
        result: Dict[str, Any],
        tenant_id: str
    ):
        """Distribute rewards to successful agents"""
        with tracer.start_as_current_span("distribute_rewards"):
            # Calculate reward based on mission complexity
            complexity_multiplier = {
                "simple": 1.0,
                "moderate": 1.5,
                "complex": 2.0,
                "swarm": 3.0
            }
            
            base_reward = 10.0  # Base credits
            multiplier = complexity_multiplier.get(plan["complexity"], 1.0)
            total_reward = base_reward * multiplier
            
            # Reward each agent that participated
            agents_used = result.get("agents_used", [])
            reward_per_agent = total_reward / len(agents_used) if agents_used else 0
            
            for agent_name in agents_used:
                await self.marketplace.reward(
                    tenant_id=tenant_id,
                    agent_id=agent_name,
                    amount=reward_per_agent,
                    resource_type="mission_reward",
                    mission_id=mission_id,
                    agent_type="executor"
                )
            
            # Publish reward event
            await self.event_bus.publish(
                "rewards.distributed",
                {
                    "mission_id": mission_id,
                    "total_reward": total_reward,
                    "agents": agents_used
                }
            )
