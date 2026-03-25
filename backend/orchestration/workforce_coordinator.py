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
from backend.domain.control.repositories.workforce_run_repository import WorkforceRunRepository
from backend.domain.control.services.execution_coordinator import ExecutionCoordinator
from backend.models.domain.execution_task import ExecutionTask, ExecutionTaskStatus, ExecutionTaskType

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AgentRole(str, Enum):
    """Roles available in a workforce."""

    COMMANDER = "commander"  # Decomposes goal, coordinates team
    RESEARCHER = "researcher"  # Gathers information
    ANALYST = "analyst"  # Processes and interprets data
    WRITER = "writer"  # Produces content / reports
    POSTER = "poster"  # Publishes to external platforms
    REVIEWER = "reviewer"  # Quality-checks output before delivery
    EXECUTOR = "executor"  # Generic task execution


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
    depends_on: List[str] = field(default_factory=list)  # sub_mission_ids
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
    Contains governed execution tasks plus legacy compatibility sub-missions.
    """

    plan_id: str
    workforce_id: str
    goal: str
    sub_missions: List[SubMission] = field(default_factory=list)
    execution_tasks: List[ExecutionTask] = field(default_factory=list)
    pipeline_type: str = "sequential"  # "sequential" | "parallel" | "mixed"
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
        execution_coordinator: Optional[ExecutionCoordinator] = None,
        workforce_run_repository: Optional[WorkforceRunRepository] = None,
    ) -> None:
        self.llm_service = llm_service
        self.mission_executor = mission_executor
        self.event_store = event_store
        self.marketplace = marketplace
        self.execution_coordinator = execution_coordinator or ExecutionCoordinator()
        self.workforce_run_repository = workforce_run_repository

        # Transitional compatibility seam:
        # keeps current workforce orchestration runnable while authoritative
        # governed runtime ownership moves to ExecutionTask / WorkforceFleet /
        # ExecutionBranch persistence.
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
        self._persist_run_state(run)

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

            self._attach_planned_execution_tasks(run, plan)
            self._persist_run_state(run)

            # Phase 2: Execute sub-missions in dependency order
            run.status = WorkforceStatus.RUNNING
            await self._execute_plan(run=run, tenant_id=tenant_id, user_id=user_id)

            # Phase 3: Aggregate results
            run.status = WorkforceStatus.AGGREGATING
            final_output = await self._aggregate(run=run, tenant_id=tenant_id)
            run.final_output = final_output

            # Determine final status from governed ExecutionTask state
            failed_count = self._count_failed_governed_tasks(run)
            if failed_count == 0:
                run.status = WorkforceStatus.COMPLETED
            elif failed_count < len(run.sub_missions):
                run.status = WorkforceStatus.PARTIALLY_FAILED
            else:
                run.status = WorkforceStatus.FAILED

            run.completed_at = datetime.utcnow()
            self._persist_run_state(run)

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
            self._persist_run_state(run)

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
            self._serialize_run(r) for r in self._runs.values() if r.workforce_id == workforce_id
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
                raw = "\n".join(line for line in lines if not line.startswith("```")).strip()

            import json

            plan_data = json.loads(raw)

        except Exception as exc:
            logger.warning(f"Commander planning LLM failed ({exc}), using default plan")
            # Fallback: one sub-mission per role, sequential
            plan_data = {
                "pipeline_type": "sequential",
                "sub_missions": [{"role": r.value, "goal": goal, "depends_on": []} for r in roles],
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

        execution_tasks = [
            self._planned_sub_mission_to_execution_task(
                run_id=run_id,
                tenant_id=tenant_id,
                created_at=datetime.utcnow(),
                sub_mission=sub_mission,
            )
            for sub_mission in sub_missions
        ]

        return WorkforcePlan(
            plan_id=str(uuid.uuid4()),
            workforce_id=run_id,
            goal=goal,
            sub_missions=sub_missions,
            execution_tasks=execution_tasks,
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

        Governed ExecutionTask planning graph is the primary execution graph.
        SubMission remains only as the dispatch compatibility shell.
        """
        task_map = self._get_planned_task_map(run)
        pending_ids: set[str] = set(task_map.keys()) or set(run.sub_missions.keys())

        while pending_ids:
            governed_completed_ids = self._dependency_ids_completed_in_governed_state(run)
            ready_task_ids = self._resolve_ready_task_ids(
                run=run,
                pending_ids=pending_ids,
                completed_ids=governed_completed_ids,
            )

            if not ready_task_ids:
                logger.warning(
                    f"Workforce run {run.run_id}: no ready sub-missions, "
                    f"breaking execution loop"
                )
                for task_id in list(pending_ids):
                    sm = run.sub_missions.get(task_id)
                    if sm:
                        sm.status = SubMissionStatus.SKIPPED
                        self._sync_execution_task(run, sm)
                break

            completed_results = self._get_completed_results_from_governed_tasks(
                run=run,
                completed_ids=governed_completed_ids,
            )

            tasks = [
                self._execute_sub_mission(
                    run=run,
                    task_id=task_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    completed_results=completed_results,
                )
                for task_id in ready_task_ids
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            for task_id in ready_task_ids:
                pending_ids.discard(task_id)

    async def _execute_sub_mission(
        self,
        run: WorkforceRun,
        task_id: str,
        tenant_id: str,
        user_id: str,
        completed_results: Dict[str, str],
    ) -> None:
        """
        Execute a single sub-mission, with retry on failure.

        Dispatch is task-ID-first; legacy SubMission is resolved internally
        as a compatibility shell during transition.
        """
        sub_mission = run.sub_missions[task_id]

        sub_mission.status = SubMissionStatus.RUNNING
        sub_mission.started_at = datetime.utcnow()
        self._sync_execution_task(run, sub_mission)

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
                # Transitional governed identity alignment:
                # bind mission execution to the governed work-unit identity so
                # runtime lineage is no longer split across random mission IDs.
                mission_id = sub_mission.sub_mission_id

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
                    self._sync_execution_task(run, sub_mission)

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

                raise RuntimeError(result.get("output", "Sub-mission returned non-success status"))

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
                    self._sync_execution_task(run, sub_mission)
                    await asyncio.sleep(1.0 * sub_mission.retry_count)
                else:
                    sub_mission.status = SubMissionStatus.FAILED
                    sub_mission.completed_at = datetime.utcnow()
                    self._sync_execution_task(run, sub_mission)

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
        Synthesise the outputs of all completed work units into a final
        coherent result using the Commander LLM.

        Governed task outputs are the primary aggregation source.
        """
        completed = self._get_all_completed_results_from_governed_tasks(run)

        if not completed:
            return "No sub-missions completed successfully."

        completed_items = list(completed.values())

        if len(completed_items) == 1:
            return completed_items[0]["result"]

        outputs_block = "\n\n".join(
            f"[{item['role'].upper()} OUTPUT]\n{item['result']}"
            for item in completed_items
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
            return "\n\n---\n\n".join(
                f"[{item['role']}]\n{item['result']}"
                for item in completed_items
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

    def _map_sub_mission_status(self, status: SubMissionStatus) -> ExecutionTaskStatus:
        """Map legacy SubMissionStatus to first-class ExecutionTaskStatus."""
        mapping = {
            SubMissionStatus.PENDING: ExecutionTaskStatus.PENDING,
            SubMissionStatus.RUNNING: ExecutionTaskStatus.ACTIVE,
            SubMissionStatus.COMPLETED: ExecutionTaskStatus.COMPLETED,
            SubMissionStatus.FAILED: ExecutionTaskStatus.FAILED,
            SubMissionStatus.RETRYING: ExecutionTaskStatus.BLOCKED,
            SubMissionStatus.SKIPPED: ExecutionTaskStatus.CANCELLED,
        }
        return mapping.get(status, ExecutionTaskStatus.PENDING)

    def _map_role_to_task_type(self, role: AgentRole) -> ExecutionTaskType:
        """Map workforce role to task type."""
        mapping = {
            AgentRole.RESEARCHER: ExecutionTaskType.RESEARCH,
            AgentRole.ANALYST: ExecutionTaskType.ANALYSIS,
            AgentRole.WRITER: ExecutionTaskType.GENERATION,
            AgentRole.POSTER: ExecutionTaskType.GENERATION,
            AgentRole.REVIEWER: ExecutionTaskType.ANALYSIS,
            AgentRole.EXECUTOR: ExecutionTaskType.GENERIC,
            AgentRole.COMMANDER: ExecutionTaskType.COORDINATION,
        }
        return mapping.get(role, ExecutionTaskType.GENERIC)

    def _sub_mission_to_execution_task(
        self,
        run: WorkforceRun,
        sub_mission: SubMission,
    ) -> ExecutionTask:
        """Translate legacy SubMission into a first-class ExecutionTask view."""
        return ExecutionTask(
            id=sub_mission.sub_mission_id,
            mission_id=run.run_id,
            tenant_id=run.tenant_id,
            title=f"{sub_mission.role.value.title()} Task",
            objective=sub_mission.goal,
            status=self._map_sub_mission_status(sub_mission.status),
            task_type=self._map_role_to_task_type(sub_mission.role),
            input_payload={
                "goal": sub_mission.goal,
                "context": sub_mission.context,
            },
            output_payload={
                "result": sub_mission.result,
            }
            if sub_mission.result
            else {},
            dependencies=sub_mission.depends_on,
            metadata={
                "source": "workforce_coordinator",
                "legacy_role": sub_mission.role.value,
                "retry_count": sub_mission.retry_count,
                "max_retries": sub_mission.max_retries,
            },
            created_at=run.created_at,
            started_at=sub_mission.started_at,
            completed_at=sub_mission.completed_at,
            error=sub_mission.error,
        )

    def _planned_sub_mission_to_execution_task(
        self,
        *,
        run_id: str,
        tenant_id: str,
        created_at: datetime,
        sub_mission: SubMission,
    ) -> ExecutionTask:
        """
        Build governed ExecutionTask during planning.

        Transitional intent:
        - make plan construction ExecutionTask-first
        - retain SubMission as execution-loop compatibility shell
        """
        return ExecutionTask(
            id=sub_mission.sub_mission_id,
            mission_id=run_id,
            tenant_id=tenant_id,
            title=f"{sub_mission.role.value.title()} Task",
            objective=sub_mission.goal,
            status=ExecutionTaskStatus.PENDING,
            task_type=self._map_role_to_task_type(sub_mission.role),
            input_payload={
                "goal": sub_mission.goal,
                "context": sub_mission.context,
            },
            output_payload={},
            dependencies=list(sub_mission.depends_on),
            metadata={
                "source": "workforce_coordinator.plan",
                "legacy_role": sub_mission.role.value,
                "retry_count": sub_mission.retry_count,
                "max_retries": sub_mission.max_retries,
            },
            created_at=created_at,
            started_at=None,
            completed_at=None,
            error=None,
        )

    def _attach_planned_execution_tasks(
        self,
        run: WorkforceRun,
        plan: WorkforcePlan,
    ) -> None:
        """
        Attach governed plan tasks before execution begins.

        Purpose:
        - persist/runtime-register governed work units at plan initialization
        - keep later sync calls focused on state transitions
        """
        for task in plan.execution_tasks:
            self.execution_coordinator.attach_task(
                {
                    "mission_id": run.run_id,
                    "tenant_id": run.tenant_id,
                    "objective": run.goal,
                },
                task,
            )

    def _sync_execution_task(
        self,
        run: WorkforceRun,
        sub_mission: SubMission,
    ) -> ExecutionTask:
        """
        Transitional governed-task sync for legacy SubMission execution.

        Purpose:
        - make ExecutionTask the persisted/runtime-backed governed work unit
        - preserve current SubMission execution loop until callers migrate

        Replacement target:
        - direct ExecutionTask-owned execution flow

        Removal condition:
        - SubMission is no longer authoritative in the coordinator

        Removal milestone:
        - Exit Transitional Runtime State
        """
        task = self._sub_mission_to_execution_task(run, sub_mission)
        self.execution_coordinator.attach_task(
            {
                "mission_id": run.run_id,
                "tenant_id": run.tenant_id,
                "objective": run.goal,
            },
            task,
        )
        return task

    def _sync_all_execution_tasks(self, run: WorkforceRun) -> List[ExecutionTask]:
        """Sync all current sub-missions into governed ExecutionTask state."""
        return [self._sync_execution_task(run, sm) for sm in run.sub_missions.values()]

    def _get_governed_task_status_map(self, run_id: str) -> Dict[str, str]:
        """
        Return task_id -> status from authoritative governed execution state.

        Transitional intent:
        - execution control begins reading governed task state
        - legacy SubMission remains as a compatibility shell until fully removed
        """
        execution_state = self.execution_coordinator.get_authoritative_mission_execution_state(
            run_id
        )
        tasks = execution_state.get("tasks", []) if isinstance(execution_state, dict) else []
        return {
            task.get("id"): task.get("status")
            for task in tasks
            if isinstance(task, dict) and task.get("id")
        }

    def _dependency_ids_completed_in_governed_state(
        self,
        run: WorkforceRun,
    ) -> set[str]:
        """Return all run task IDs marked completed in governed runtime state."""
        governed_statuses = self._get_governed_task_status_map(run.run_id)
        return {
            task_id
            for task_id, status in governed_statuses.items()
            if status == ExecutionTaskStatus.COMPLETED.value and task_id in run.sub_missions
        }

    def _count_failed_governed_tasks(self, run: WorkforceRun) -> int:
        """Count failed governed tasks for final workforce status projection."""
        governed_statuses = self._get_governed_task_status_map(run.run_id)
        return sum(
            1
            for task_id, status in governed_statuses.items()
            if task_id in run.sub_missions and status == ExecutionTaskStatus.FAILED.value
        )

    def _get_planned_task_map(self, run: WorkforceRun) -> Dict[str, ExecutionTask]:
        """
        Return planned governed tasks keyed by task ID.

        Transitional intent:
        - plan task graph becomes the primary execution graph
        - SubMission remains only as dispatch compatibility state
        """
        if not run.plan:
            return {}
        return {task.id: task for task in run.plan.execution_tasks}

    def _resolve_ready_sub_missions(
        self,
        run: WorkforceRun,
        pending_ids: set[str],
        completed_ids: set[str],
    ) -> List[SubMission]:
        """
        Resolve ready governed tasks to legacy SubMission dispatch objects.
        """
        task_map = self._get_planned_task_map(run)
        ready_task_ids = [
            task_id
            for task_id in pending_ids
            if task_id in task_map
            and all(dep in completed_ids for dep in task_map[task_id].dependencies)
        ]
        return [
            run.sub_missions[task_id]
            for task_id in ready_task_ids
            if task_id in run.sub_missions
        ]

    def _resolve_ready_task_ids(
        self,
        run: WorkforceRun,
        pending_ids: set[str],
        completed_ids: set[str],
    ) -> List[str]:
        """
        Resolve ready governed task IDs from the planned execution graph.
        """
        task_map = self._get_planned_task_map(run)
        return [
            task_id
            for task_id in pending_ids
            if task_id in task_map
            and all(dep in completed_ids for dep in task_map[task_id].dependencies)
            and task_id in run.sub_missions
        ]

    def _get_completed_results_from_governed_tasks(
        self,
        run: WorkforceRun,
        completed_ids: set[str],
    ) -> Dict[str, str]:
        """
        Return completed prior outputs from governed task state first.

        Transitional behavior:
        - governed ExecutionTask output_payload is the primary source
        - legacy SubMission.result is fallback only
        """
        execution_state = self.execution_coordinator.get_authoritative_mission_execution_state(
            run.run_id
        )
        task_items = execution_state.get("tasks", []) if isinstance(execution_state, dict) else []

        governed_results: Dict[str, str] = {}
        for task in task_items:
            if not isinstance(task, dict):
                continue
            task_id = task.get("id")
            if task_id not in completed_ids:
                continue

            output_payload = task.get("output_payload") or {}
            result_value = None

            if isinstance(output_payload, dict):
                result_value = output_payload.get("result")

            if not result_value and task_id in run.sub_missions:
                result_value = run.sub_missions[task_id].result

            if result_value:
                governed_results[task_id] = result_value

        return governed_results

    def _get_all_completed_results_from_governed_tasks(
        self,
        run: WorkforceRun,
    ) -> Dict[str, Dict[str, str]]:
        """
        Return all completed governed task outputs for aggregation.

        Governed task output is primary; legacy SubMission fields are fallback.
        """
        execution_state = self.execution_coordinator.get_authoritative_mission_execution_state(
            run.run_id
        )
        task_items = execution_state.get("tasks", []) if isinstance(execution_state, dict) else []

        completed_results: Dict[str, Dict[str, str]] = {}

        for task in task_items:
            if not isinstance(task, dict):
                continue

            task_id = task.get("id")
            status = task.get("status")
            if not task_id or status != ExecutionTaskStatus.COMPLETED.value:
                continue

            output_payload = task.get("output_payload") or {}
            result_value = None
            if isinstance(output_payload, dict):
                result_value = output_payload.get("result")

            if not result_value and task_id in run.sub_missions:
                result_value = run.sub_missions[task_id].result

            if not result_value:
                continue

            role_value = "executor"
            if task_id in run.sub_missions:
                role_value = run.sub_missions[task_id].role.value

            completed_results[task_id] = {
                "role": role_value,
                "result": result_value,
            }

        return completed_results

    def _persist_run_state(self, run: WorkforceRun) -> None:
        """
        Durable persistence seam for WorkforceRun.

        Purpose:
        - move workforce run ownership toward durable runtime state
        - preserve _runs as compatibility cache until callers migrate
        """
        if not self.workforce_run_repository:
            return

        serialized = self._serialize_run(run)
        governed_execution_state = self.execution_coordinator.get_authoritative_mission_execution_state(
            run.run_id
        )

        payload = {
            **serialized,
            "legacy_sub_missions": serialized.get("legacy_sub_missions", []),
            "governed_execution_state": governed_execution_state,
            "runtime_metadata": {
                "source": "workforce_coordinator",
                "compatibility_cache_present": True,
                "legacy_sub_missions_compatibility_only": True,
            },
            "created_at": run.created_at,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        }
        self.workforce_run_repository.save_run(payload)

    def _serialize_run(self, run: WorkforceRun) -> Dict[str, Any]:
        """Convert a WorkforceRun to a JSON-serialisable dict."""
        execution_tasks = [task.model_dump() for task in self._sync_all_execution_tasks(run)]
        legacy_sub_missions = [
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
                "completed_at": sm.completed_at.isoformat() if sm.completed_at else None,
            }
            for sm in run.sub_missions.values()
        ]

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
            # Governed primary runtime view
            "execution_tasks": execution_tasks,
            # Transitional compatibility payload
            "legacy_sub_missions": legacy_sub_missions,
            "sub_missions": legacy_sub_missions,
            "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def get_run_state(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return serialized run state plus governed execution state for a run."""
        run = self._runs.get(run_id)
        if run:
            serialized = self._serialize_run(run)
            execution_state = self.execution_coordinator.get_authoritative_mission_execution_state(
                run_id
            )
            serialized["governed_execution_state"] = execution_state
            return serialized

        if not self.workforce_run_repository:
            return None

        record = self.workforce_run_repository.get_run(run_id)
        if not record:
            return None

        legacy_sub_missions = list(record.sub_missions or [])
        execution_tasks = list(record.execution_tasks or [])

        return {
            "run_id": record.id,
            "workforce_id": record.workforce_id,
            "goal": record.goal,
            "tenant_id": record.tenant_id,
            "status": record.status,
            "final_output": record.final_output,
            "error": record.error,
            "cost": record.cost,
            "agents_used": list(record.agents_used or []),
            # Governed primary runtime view
            "execution_tasks": execution_tasks,
            # Transitional compatibility payload
            "legacy_sub_missions": legacy_sub_missions,
            "sub_missions": legacy_sub_missions,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "governed_execution_state": dict(record.governed_execution_state or {}),
        }
