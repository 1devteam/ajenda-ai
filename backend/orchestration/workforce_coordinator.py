"""
Workforce Coordinator — Omnipath v6.3 (Phase 4: The Coordinating Agent)

Orchestrates heterogeneous agent teams where each agent has a distinct role
and the output of one feeds the input of the next. Unlike the swarm executor
(which runs identical parallel tasks), the WorkforceCoordinator manages:

  - Goal decomposition into typed sub-missions
  - Role-based agent assignment (researcher → analyst → writer → poster)
  - Sequential and parallel execution pipelines
  - Child mission tracking via EventStore
  - Partial-failure compensation (retry one child, not the whole workforce)
  - Result aggregation and synthesis

Built with Pride for Obex Blackvault.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.governance import assemble_prompt
from backend.core.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AgentRole(str, Enum):
    """Roles available in a workforce."""

    COMMANDER = "commander"      # Decomposes goal, coordinates team
    RESEARCHER = "researcher"    # Gathers information
    ANALYST = "analyst"          # Processes and interprets data
    WRITER = "writer"            # Produces content / reports
    POSTER = "poster"            # Publishes to external platforms
    REVIEWER = "reviewer"        # Quality-checks output before delivery
    EXECUTOR = "executor"        # Generic task execution


class WorkforceStatus(str, Enum):
    """Lifecycle status of a workforce run."""

    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


class SubMissionStatus(str, Enum):
    """Status of a single child mission within a workforce run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SubMission:
    """
    A single unit of work assigned to one agent role within a workforce run.
    """

    sub_mission_id: str
    role: AgentRole
    goal: str
    context: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)   # sub_mission_ids
    status: SubMissionStatus = SubMissionStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class WorkforcePlan:
    """
    Execution plan produced by the Commander during the planning phase.
    Contains an ordered list of sub-missions with dependency edges.
    """

    plan_id: str
    workforce_id: str
    goal: str
    sub_missions: List[SubMission] = field(default_factory=list)
    pipeline_type: str = "sequential"   # "sequential" | "parallel" | "mixed"
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class WorkforceRun:
    """
    Runtime state of a workforce execution.
    """

    run_id: str
    workforce_id: str
    goal: str
    tenant_id: str
    plan: Optional[WorkforcePlan] = None
    status: WorkforceStatus = WorkforceStatus.PENDING
    sub_missions: Dict[str, SubMission] = field(default_factory=dict)
    final_output: Optional[str] = None
    error: Optional[str] = None
    cost: float = 0.0
    agents_used: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# WorkforceCoordinator
# ---------------------------------------------------------------------------


class WorkforceCoordinator:
    """
    Coordinates heterogeneous agent teams to accomplish complex goals.

    The coordinator acts as the Commander layer above MissionExecutor:
    it decomposes a high-level goal into typed sub-missions, dispatches
    them in dependency order, tracks their completion via the EventStore,
    and synthesises the final output.

    Args:
        llm_service: LLMService instance for LLM calls.
        mission_executor: MissionExecutor for dispatching sub-missions.
        event_store: EventStore for recording workforce events.
        marketplace: ResourceMarketplace for credit management.
    """

    def __init__(
        self,
        llm_service: Any,
        mission_executor: Any,
        event_store: Any,
        marketplace: Any,
    ) -> None:
        self.llm_service = llm_service
        self.mission_executor = mission_executor
        self.event_store = event_store
        self.marketplace = marketplace

        # In-memory run registry (production: persist to DB)
        self._runs: Dict[str, WorkforceRun] = {}

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def run(
        self,
        workforce_id: str,
        goal: str,
        tenant_id: str,
        user_id: str,
        roles: Optional[List[str]] = None,
        pipeline_type: str = "sequential",
        budget: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute a full workforce run for the given goal.

        Args:
            workforce_id: Stable identifier for this workforce configuration.
            goal: High-level objective in natural language.
            tenant_id: Tenant scope.
            user_id: Requesting user.
            roles: Optional list of AgentRole values to include. Defaults to
                   [researcher, analyst, writer].
            pipeline_type: "sequential" | "parallel" | "mixed".
            budget: Optional credit budget cap.

        Returns:
            Dict with run_id, status, output, cost, agents_used, sub_missions.
        """
        run_id = str(uuid.uuid4())
        run = WorkforceRun(
            run_id=run_id,
            workforce_id=workforce_id,
            goal=goal,
            tenant_id=tenant_id,
            status=WorkforceStatus.PENDING,
        )
        self._runs[run_id] = run

        await self._emit_event(
            run_id=run_id,
            event_type="workforce.started",
            data={
                "workforce_id": workforce_id,
                "goal": goal,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "pipeline_type": pipeline_type,
            },
        )

        try:
            run.started_at = datetime.utcnow()

            # Phase 1: Commander decomposes goal into sub-missions
            run.status = WorkforceStatus.PLANNING
            effective_roles = roles or [
                AgentRole.RESEARCHER,
                AgentRole.ANALYST,
                AgentRole.WRITER,
            ]
            plan = await self._plan(
                run_id=run_id,
                goal=goal,
                tenant_id=tenant_id,
                roles=effective_roles,
                pipeline_type=pipeline_type,
            )
            run.plan = plan
            for sm in plan.sub_missions:
                run.sub_missions[sm.sub_mission_id] = sm

            # Phase 2: Execute sub-missions in dependency order
            run.status = WorkforceStatus.RUNNING
            await self._execute_plan(run=run, tenant_id=tenant_id, user_id=user_id)

            # Phase 3: Aggregate results
            run.status = WorkforceStatus.AGGREGATING
            final_output = await self._aggregate(run=run, tenant_id=tenant_id)
            run.final_output = final_output

            # Determine final status
            failed_count = sum(
                1 for sm in run.sub_missions.values()
                if sm.status == SubMissionStatus.FAILED
            )
            if failed_count == 0:
                run.status = WorkforceStatus.COMPLETED
            elif failed_count < len(run.sub_missions):
                run.status = WorkforceStatus.PARTIALLY_FAILED
            else:
                run.status = WorkforceStatus.FAILED

            run.completed_at = datetime.utcnow()

            await self._emit_event(
                run_id=run_id,
                event_type="workforce.completed",
                data={
                    "workforce_id": workforce_id,
                    "status": run.status.value,
                    "cost": run.cost,
                    "agents_used": run.agents_used,
                    "sub_mission_count": len(run.sub_missions),
                    "failed_count": failed_count,
                },
            )

            return self._serialize_run(run)

        except Exception as exc:
            run.status = WorkforceStatus.FAILED
            run.error = str(exc)
            run.completed_at = datetime.utcnow()

            await self._emit_event(
                run_id=run_id,
                event_type="workforce.failed",
                data={
                    "workforce_id": workforce_id,
                    "error": str(exc),
                },
            )

            logger.error(f"Workforce run {run_id} failed: {exc}", exc_info=True)
            return self._serialize_run(run)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return serialized run state, or None if not found."""
        run = self._runs.get(run_id)
        return self._serialize_run(run) if run else None

    def list_runs(self, workforce_id: str) -> List[Dict[str, Any]]:
        """Return all runs for a given workforce_id."""
        return [
            self._serialize_run(r)
            for r in self._runs.values()
            if r.workforce_id == workforce_id
        ]

    # -----------------------------------------------------------------------
    # Planning
    # -----------------------------------------------------------------------

    async def _plan(
        self,
        run_id: str,
        goal: str,
        tenant_id: str,
        roles: List[AgentRole],
        pipeline_type: str,
    ) -> WorkforcePlan:
        """
        Use the Commander LLM to decompose the goal into typed sub-missions.

        The LLM is given the goal and the available roles, and asked to
        produce a JSON plan. We then parse and validate the plan.
        """
        llm = self.llm_service.get_llm("commander", tenant_id)

        role_list = ", ".join(r.value for r in roles)
        commander_role = (
            "You are the Commander agent. Your job is to decompose a high-level "
            "goal into a precise execution plan for a team of specialised agents. "
            "Return ONLY valid JSON — no markdown, no explanation."
        )
        system_prompt = assemble_prompt(commander_role)

        user_prompt = f"""
Goal: {goal}

Available agent roles: {role_list}
Pipeline type: {pipeline_type}

Produce a JSON plan with this exact structure:
{{
  "pipeline_type": "{pipeline_type}",
  "sub_missions": [
    {{
      "role": "<one of: {role_list}>",
      "goal": "<specific task for this agent>",
      "depends_on": []
    }}
  ]
}}

Rules:
- Each sub_mission must have a unique, actionable goal.
- depends_on lists the indices (0-based) of sub_missions that must complete first.
- For sequential pipelines, each step depends on the previous.
- For parallel pipelines, all steps have empty depends_on.
- For mixed pipelines, use your judgment.
- Maximum {len(roles)} sub_missions.
- Return only the JSON object.
"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = await llm.ainvoke(messages)
            raw = response.content.strip()

            # Strip markdown code fences if present
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(
                    line for line in lines
                    if not line.startswith("```")
                ).strip()

            import json
            plan_data = json.loads(raw)

        except Exception as exc:
            logger.warning(
                f"Commander planning LLM failed ({exc}), using default plan"
            )
            # Fallback: one sub-mission per role, sequential
            plan_data = {
                "pipeline_type": "sequential",
                "sub_missions": [
                    {"role": r.value, "goal": goal, "depends_on": []}
                    for r in roles
                ],
            }

        # Build SubMission objects
        sub_missions: List[SubMission] = []
        raw_sms = plan_data.get("sub_missions", [])
        id_map: Dict[int, str] = {}  # index → sub_mission_id

        for idx, sm_data in enumerate(raw_sms):
            sm_id = str(uuid.uuid4())
            id_map[idx] = sm_id

            # Resolve depends_on indices to IDs (already-created entries)
            depends_on_ids = []
            for dep_idx in sm_data.get("depends_on", []):
                if isinstance(dep_idx, int) and dep_idx in id_map:
                    depends_on_ids.append(id_map[dep_idx])

            role_str = sm_data.get("role", AgentRole.EXECUTOR.value)
            try:
                role = AgentRole(role_str)
            except ValueError:
                role = AgentRole.EXECUTOR

            sub_missions.append(
                SubMission(
                    sub_mission_id=sm_id,
                    role=role,
                    goal=sm_data.get("goal", goal),
                    depends_on=depends_on_ids,
                )
            )

        return WorkforcePlan(
            plan_id=str(uuid.uuid4()),
            workforce_id=run_id,
            goal=goal,
            sub_missions=sub_missions,
            pipeline_type=plan_data.get("pipeline_type", "sequential"),
        )

    # -----------------------------------------------------------------------
    # Execution
    # -----------------------------------------------------------------------

    async def _execute_plan(
        self,
        run: WorkforceRun,
        tenant_id: str,
        user_id: str,
    ) -> None:
        """
        Execute sub-missions respecting dependency order.

        Sub-missions with no unresolved dependencies are dispatched
        concurrently. Each completion may unblock further sub-missions.
        """
        completed_ids: set = set()
        pending = list(run.sub_missions.values())

        while pending:
            # Find all sub-missions whose dependencies are satisfied
            ready = [
                sm for sm in pending
                if all(dep in completed_ids for dep in sm.depends_on)
            ]

            if not ready:
                # Circular dependency or all remaining are blocked by failures
                logger.warning(
                    f"Workforce run {run.run_id}: no ready sub-missions, "
                    f"breaking execution loop"
                )
                for sm in pending:
                    sm.status = SubMissionStatus.SKIPPED
                break

            # Dispatch ready sub-missions concurrently
            tasks = [
                self._execute_sub_mission(
                    run=run,
                    sub_mission=sm,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    completed_results={
                        sid: run.sub_missions[sid].result
                        for sid in completed_ids
                        if run.sub_missions[sid].result
                    },
                )
                for sm in ready
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Mark dispatched as no longer pending
            for sm in ready:
                pending.remove(sm)
                completed_ids.add(sm.sub_mission_id)

    async def _execute_sub_mission(
        self,
        run: WorkforceRun,
        sub_mission: SubMission,
        tenant_id: str,
        user_id: str,
        completed_results: Dict[str, str],
    ) -> None:
        """
        Execute a single sub-mission, with retry on failure.

        Enriches the sub-mission goal with context from already-completed
        sub-missions so each agent builds on prior work.
        """
        sub_mission.status = SubMissionStatus.RUNNING
        sub_mission.started_at = datetime.utcnow()

        # Build enriched goal with prior context
        enriched_goal = sub_mission.goal
        if completed_results:
            context_block = "\n\n".join(
                f"[Prior output]\n{result}"
                for result in completed_results.values()
                if result
            )
            if context_block:
                enriched_goal = (
                    f"{sub_mission.goal}\n\n"
                    f"Use the following prior work as context:\n{context_block}"
                )

        while sub_mission.retry_count <= sub_mission.max_retries:
            try:
                mission_id = str(uuid.uuid4())

                result = await self.mission_executor.execute_mission(
                    mission_id=mission_id,
                    goal=enriched_goal,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )

                if result.get("status") in ("COMPLETED", "SUCCESS"):
                    sub_mission.status = SubMissionStatus.COMPLETED
                    sub_mission.result = result.get("output", "")
                    sub_mission.completed_at = datetime.utcnow()
                    run.cost += result.get("cost", 0.0)
                    run.agents_used.append(sub_mission.role.value)

                    await self._emit_event(
                        run_id=run.run_id,
                        event_type="workforce.sub_mission.completed",
                        data={
                            "sub_mission_id": sub_mission.sub_mission_id,
                            "role": sub_mission.role.value,
                            "mission_id": mission_id,
                        },
                    )
                    return

                else:
                    raise RuntimeError(
                        result.get("output", "Sub-mission returned non-success status")
                    )

            except Exception as exc:
                sub_mission.retry_count += 1
                sub_mission.error = str(exc)
                logger.warning(
                    f"Sub-mission {sub_mission.sub_mission_id} "
                    f"(role={sub_mission.role.value}) attempt "
                    f"{sub_mission.retry_count} failed: {exc}"
                )

                if sub_mission.retry_count <= sub_mission.max_retries:
                    sub_mission.status = SubMissionStatus.RETRYING
                    await asyncio.sleep(1.0 * sub_mission.retry_count)
                else:
                    sub_mission.status = SubMissionStatus.FAILED
                    sub_mission.completed_at = datetime.utcnow()

                    await self._emit_event(
                        run_id=run.run_id,
                        event_type="workforce.sub_mission.failed",
                        data={
                            "sub_mission_id": sub_mission.sub_mission_id,
                            "role": sub_mission.role.value,
                            "error": str(exc),
                            "retries": sub_mission.retry_count,
                        },
                    )
                    return

    # -----------------------------------------------------------------------
    # Aggregation
    # -----------------------------------------------------------------------

    async def _aggregate(
        self,
        run: WorkforceRun,
        tenant_id: str,
    ) -> str:
        """
        Synthesise the outputs of all completed sub-missions into a final
        coherent result using the Commander LLM.
        """
        completed = [
            sm for sm in run.sub_missions.values()
            if sm.status == SubMissionStatus.COMPLETED and sm.result
        ]

        if not completed:
            return "No sub-missions completed successfully."

        if len(completed) == 1:
            return completed[0].result or ""

        # Build synthesis prompt
        outputs_block = "\n\n".join(
            f"[{sm.role.value.upper()} OUTPUT]\n{sm.result}"
            for sm in completed
        )

        llm = self.llm_service.get_llm("commander", tenant_id)
        synthesiser_role = (
            "You are the Commander agent synthesising the outputs of your team. "
            "Produce a single, coherent final report that integrates all outputs. "
            "Be concise, accurate, and actionable."
        )
        system_prompt = assemble_prompt(synthesiser_role)
        user_prompt = (
            f"Original goal: {run.goal}\n\n"
            f"Team outputs:\n{outputs_block}\n\n"
            f"Synthesise these into a final report."
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = await llm.ainvoke(messages)
            return response.content.strip()
        except Exception as exc:
            logger.error(f"Aggregation LLM failed: {exc}")
            # Fallback: concatenate outputs
            return "\n\n---\n\n".join(
                f"[{sm.role.value}]\n{sm.result}" for sm in completed
            )

    # -----------------------------------------------------------------------
    # EventStore integration
    # -----------------------------------------------------------------------

    async def _emit_event(
        self,
        run_id: str,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """Append a workforce event to the EventStore (non-fatal on failure)."""
        if not self.event_store:
            return
        try:
            await self.event_store.append(
                aggregate_id=run_id,
                aggregate_type="workforce",
                event_type=event_type,
                data=data,
            )
        except Exception as exc:
            logger.warning(f"EventStore append failed (non-fatal): {exc}")

    # -----------------------------------------------------------------------
    # Serialisation
    # -----------------------------------------------------------------------

    def _serialize_run(self, run: WorkforceRun) -> Dict[str, Any]:
        """Convert a WorkforceRun to a JSON-serialisable dict."""
        return {
            "run_id": run.run_id,
            "workforce_id": run.workforce_id,
            "goal": run.goal,
            "tenant_id": run.tenant_id,
            "status": run.status.value,
            "final_output": run.final_output,
            "error": run.error,
            "cost": run.cost,
            "agents_used": run.agents_used,
            "sub_missions": [
                {
                    "sub_mission_id": sm.sub_mission_id,
                    "role": sm.role.value,
                    "goal": sm.goal,
                    "status": sm.status.value,
                    "result": sm.result,
                    "error": sm.error,
                    "retry_count": sm.retry_count,
                    "depends_on": sm.depends_on,
                    "started_at": sm.started_at.isoformat() if sm.started_at else None,
                    "completed_at": (
                        sm.completed_at.isoformat() if sm.completed_at else None
                    ),
                }
                for sm in run.sub_missions.values()
            ],
            "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
