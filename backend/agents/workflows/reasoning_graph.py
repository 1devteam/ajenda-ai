"""
LangGraph Reasoning Workflow for Omnipath V2
Built with Pride for Obex Blackvault

This module implements a sophisticated multi-step reasoning workflow using LangGraph.
Agents can plan, execute, reflect, and adapt their strategies dynamically.
"""

from typing import Dict, Any, List, TypedDict, Annotated, Sequence
from enum import Enum
import operator

from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel

from backend.integrations.observability.prometheus_metrics import get_metrics


class ReasoningState(TypedDict):
    """State for the reasoning workflow."""

    messages: Annotated[Sequence[BaseMessage], operator.add]
    objective: str
    plan: List[str]
    current_step: int
    step_results: Dict[int, Any]
    reflection: str
    iteration_count: int
    max_iterations: int
    final_answer: str
    error: str


class WorkflowNode(str, Enum):
    """Nodes in the reasoning workflow."""

    PLANNER = "planner"
    EXECUTOR = "executor"
    REFLECTOR = "reflector"
    ADAPTER = "adapter"
    FINALIZER = "finalizer"


class ReasoningWorkflow:
    """
    LangGraph-based reasoning workflow for intelligent agents.

    Workflow:
    1. PLANNER: Break down the objective into actionable steps
    2. EXECUTOR: Execute the current step
    3. REFLECTOR: Evaluate the result and identify issues
    4. ADAPTER: Adjust the plan based on reflection
    5. FINALIZER: Synthesize results into a final answer
    """

    def __init__(self, llm: BaseChatModel, max_iterations: int = 5):
        """
        Initialize the reasoning workflow.

        Args:
            llm: Language model for reasoning
            max_iterations: Maximum number of plan-execute-reflect cycles
        """
        self.llm = llm
        self.max_iterations = max_iterations
        self.metrics = get_metrics()

        # Build the workflow graph
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        workflow = StateGraph(ReasoningState)

        # Add nodes
        workflow.add_node(WorkflowNode.PLANNER, self._plan_node)
        workflow.add_node(WorkflowNode.EXECUTOR, self._execute_node)
        workflow.add_node(WorkflowNode.REFLECTOR, self._reflect_node)
        workflow.add_node(WorkflowNode.ADAPTER, self._adapt_node)
        workflow.add_node(WorkflowNode.FINALIZER, self._finalize_node)

        # Define edges
        workflow.set_entry_point(WorkflowNode.PLANNER)
        workflow.add_edge(WorkflowNode.PLANNER, WorkflowNode.EXECUTOR)
        workflow.add_edge(WorkflowNode.EXECUTOR, WorkflowNode.REFLECTOR)

        # Conditional edge: Continue or finalize
        workflow.add_conditional_edges(
            WorkflowNode.REFLECTOR,
            self._should_continue,
            {"continue": WorkflowNode.ADAPTER, "finalize": WorkflowNode.FINALIZER},
        )

        workflow.add_edge(WorkflowNode.ADAPTER, WorkflowNode.EXECUTOR)
        workflow.add_edge(WorkflowNode.FINALIZER, END)

        return workflow.compile()

    async def _plan_node(self, state: ReasoningState) -> Dict[str, Any]:
        """
        PLANNER: Break down the objective into actionable steps.
        """
        self.metrics.record_agent_reasoning_step("planner")

        system_prompt = """You are an expert planner. Break down complex objectives into clear, actionable steps.  # noqa: E501
Each step should be specific and measurable. Number the steps clearly."""

        user_prompt = f"""Objective: {state['objective']}

Create a detailed plan to achieve this objective. List 3-7 specific steps."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await self.llm.ainvoke(messages)

        # Parse the plan (simple line-based parsing)
        plan_text = response.content
        plan_steps = [
            line.strip()
            for line in plan_text.split("\n")
            if line.strip() and any(char.isdigit() for char in line[:3])
        ]

        return {
            "messages": [response],
            "plan": plan_steps,
            "current_step": 0,
            "iteration_count": 0,
        }

    async def _execute_node(self, state: ReasoningState) -> Dict[str, Any]:
        """
        EXECUTOR: Execute the current step in the plan.
        """
        self.metrics.record_agent_reasoning_step("executor")

        current_step = state["current_step"]
        plan = state["plan"]

        if current_step >= len(plan):
            return {"error": "No more steps to execute"}

        step_description = plan[current_step]

        system_prompt = """You are an expert executor. Given a specific step, provide a detailed execution strategy and expected outcome."""  # noqa: E501

        user_prompt = f"""Step to execute: {step_description}

Context from previous steps: {state.get('step_results', {})}

Provide:
1. Execution strategy
2. Expected outcome
3. Success criteria"""

        messages = state["messages"] + [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await self.llm.ainvoke(messages)

        # Store the result
        step_results = state.get("step_results", {})
        step_results[current_step] = {
            "step": step_description,
            "execution": response.content,
        }

        return {"messages": [response], "step_results": step_results}

    async def _reflect_node(self, state: ReasoningState) -> Dict[str, Any]:
        """
        REFLECTOR: Evaluate the execution result and identify issues.
        """
        self.metrics.record_agent_reasoning_step("reflector")

        current_step = state["current_step"]
        step_result = state["step_results"][current_step]

        system_prompt = """You are a critical evaluator. Assess the execution result and identify:
1. What went well
2. What could be improved
3. Whether the step achieved its goal"""

        user_prompt = f"""Step: {step_result['step']}
Execution: {step_result['execution']}

Provide a critical reflection."""

        messages = state["messages"] + [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await self.llm.ainvoke(messages)

        return {
            "messages": [response],
            "reflection": response.content,
            "iteration_count": state["iteration_count"] + 1,
        }

    def _should_continue(self, state: ReasoningState) -> str:
        """
        Decide whether to continue iterating or finalize.
        """
        current_step = state["current_step"]
        plan_length = len(state["plan"])
        iteration_count = state["iteration_count"]
        max_iterations = state.get("max_iterations", self.max_iterations)

        # Check if we've completed all steps
        if current_step >= plan_length - 1:
            return "finalize"

        # Check if we've exceeded max iterations
        if iteration_count >= max_iterations:
            return "finalize"

        return "continue"

    async def _adapt_node(self, state: ReasoningState) -> Dict[str, Any]:
        """
        ADAPTER: Adjust the plan based on reflection.
        """
        self.metrics.record_agent_reasoning_step("adapter")

        reflection = state["reflection"]
        current_step = state["current_step"]

        system_prompt = """You are an adaptive planner. Based on the reflection, decide:
1. Should we move to the next step?
2. Should we retry the current step with modifications?
3. Should we revise the remaining plan?

Respond with: NEXT_STEP, RETRY, or REVISE_PLAN"""

        user_prompt = f"""Reflection: {reflection}

What should we do next?"""

        messages = state["messages"] + [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await self.llm.ainvoke(messages)
        decision = response.content.strip().upper()

        # Determine next step
        if "NEXT_STEP" in decision:
            next_step = current_step + 1
        elif "RETRY" in decision:
            next_step = current_step  # Retry the same step
        else:
            next_step = current_step + 1  # Default to next

        return {"messages": [response], "current_step": next_step}

    async def _finalize_node(self, state: ReasoningState) -> Dict[str, Any]:
        """
        FINALIZER: Synthesize all results into a final answer.
        """
        self.metrics.record_agent_reasoning_step("finalizer")

        system_prompt = """You are a synthesis expert. Given the objective and all execution results, provide a comprehensive final answer."""  # noqa: E501

        user_prompt = f"""Objective: {state['objective']}

Plan: {state['plan']}

Execution Results: {state['step_results']}

Provide a clear, actionable final answer that addresses the original objective."""

        messages = state["messages"] + [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await self.llm.ainvoke(messages)

        return {"messages": [response], "final_answer": response.content}

    async def run(self, objective: str) -> Dict[str, Any]:
        """
        Execute the reasoning workflow for a given objective.

        Args:
            objective: The goal to achieve

        Returns:
            Final answer and workflow metadata
        """
        initial_state: ReasoningState = {
            "messages": [],
            "objective": objective,
            "plan": [],
            "current_step": 0,
            "step_results": {},
            "reflection": "",
            "iteration_count": 0,
            "max_iterations": self.max_iterations,
            "final_answer": "",
            "error": "",
        }

        # Execute the workflow
        final_state = await self.graph.ainvoke(initial_state)

        return {
            "objective": objective,
            "plan": final_state["plan"],
            "final_answer": final_state["final_answer"],
            "iterations": final_state["iteration_count"],
            "step_results": final_state["step_results"],
        }
