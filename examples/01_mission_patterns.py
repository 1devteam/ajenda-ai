"""
Example 01 — Mission Patterns
==============================
Demonstrates how to run single-agent and multi-agent missions using the
Citadel AI orchestration layer.

This file shows the three core patterns used throughout the codebase:
  1. Single-agent mission via MissionExecutor
  2. Multi-agent mission via WorkforceCoordinator
  3. Streaming mission with real-time step callbacks

Run this file directly:
    cd /path/to/citadel
    python3 examples/01_mission_patterns.py

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import asyncio
import os
import sys

# Allow running from the repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.orchestration.mission_executor import MissionExecutor
from backend.orchestration.workforce_coordinator import WorkforceCoordinator
from backend.agents.tools.tool_registry import get_tool_registry


# ─── Pattern 1: Single-Agent Mission ─────────────────────────────────────────

async def run_single_agent_mission() -> None:
    """
    The simplest pattern: one agent, one goal, one result.

    The MissionExecutor selects the best agent role for the goal,
    equips it with the registered tool suite, and runs the ReAct loop
    until the goal is achieved or the budget is exhausted.
    """
    print("\n" + "=" * 60)
    print("Pattern 1: Single-Agent Mission")
    print("=" * 60)

    executor = MissionExecutor(
        tool_registry=get_tool_registry(),
        model="gpt-4.1-mini",       # Use gpt-4.1-mini for cost efficiency
        max_iterations=10,           # Max ReAct loop iterations
        budget_limit=0.50,           # Max $0.50 in API costs
    )

    result = await executor.execute_mission(
        goal="Find the current price of Bitcoin and calculate what $1,000 invested "
             "at the 2020 low ($3,800) would be worth today.",
        tenant_id="example-tenant",
    )

    print(f"Status:  {result.status}")
    print(f"Steps:   {len(result.steps or [])}")
    print(f"Credits: {result.credits_used:.4f}")
    print(f"\nResult:\n{result.result.summary if result.result else 'No result'}")


# ─── Pattern 2: Multi-Agent Workforce Mission ─────────────────────────────────

async def run_workforce_mission() -> None:
    """
    The full workforce pattern: the WorkforceCoordinator decomposes the goal
    into sub-missions, assigns each to the appropriate specialist agent
    (Researcher, Analyst, Writer, Poster), and aggregates the results.

    This is the pattern used by the RevenueAgent for the full sales pipeline.
    """
    print("\n" + "=" * 60)
    print("Pattern 2: Multi-Agent Workforce Mission")
    print("=" * 60)

    coordinator = WorkforceCoordinator(
        tool_registry=get_tool_registry(),
        model="gpt-4.1-mini",
        max_agents=4,
    )

    result = await coordinator.run(
        goal=(
            "Research the AI consulting market in 2025. "
            "Find the top 3 pain points for SMB companies adopting AI, "
            "then write a 200-word executive summary suitable for a sales deck."
        ),
        tenant_id="example-tenant",
    )

    print(f"Status:      {result.get('status')}")
    print(f"Sub-missions: {len(result.get('sub_missions', []))}")
    print(f"\nFinal Output:\n{result.get('final_output', 'No output')}")


# ─── Pattern 3: Mission with Step Callbacks ───────────────────────────────────

async def run_mission_with_callbacks() -> None:
    """
    Streaming pattern: register callbacks to receive real-time updates
    as the agent reasons, uses tools, and produces output.

    This is the pattern used by the frontend WebSocket endpoint to stream
    mission progress to the UI.
    """
    print("\n" + "=" * 60)
    print("Pattern 3: Mission with Step Callbacks")
    print("=" * 60)

    step_count = 0

    def on_step(step: dict) -> None:
        nonlocal step_count
        step_count += 1
        tool = step.get("tool_used", "reasoning")
        output_preview = str(step.get("output", ""))[:80].replace("\n", " ")
        print(f"  Step {step_count:02d} [{tool:20s}]: {output_preview}…")

    executor = MissionExecutor(
        tool_registry=get_tool_registry(),
        model="gpt-4.1-mini",
        max_iterations=8,
        on_step_callback=on_step,
    )

    result = await executor.execute_mission(
        goal="What is 2^32 and what is its significance in computing?",
        tenant_id="example-tenant",
    )

    print(f"\nCompleted in {step_count} steps")
    print(f"Answer: {result.result.summary if result.result else 'No result'}")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    """Run all three mission patterns in sequence."""
    # Pattern 1: fastest, cheapest, single agent
    await run_single_agent_mission()

    # Pattern 2: full workforce, multi-step decomposition
    # Uncomment to run (costs more API credits):
    # await run_workforce_mission()

    # Pattern 3: real-time step streaming
    await run_mission_with_callbacks()


if __name__ == "__main__":
    asyncio.run(main())
