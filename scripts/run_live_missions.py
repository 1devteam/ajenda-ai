"""
Live Mission Runner — Citadel Agent Workforce Assessment
=========================================================
Executes three real missions using the OpenAI API and the agent tool suite.
Each mission is run as a ReAct-style agent loop: the model reasons, selects
a tool, executes it, observes the result, and repeats until done.

This is a direct, dependency-light harness that bypasses the full
MissionExecutor infrastructure to isolate and test the core agent loop.

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

import asyncio
import json
import sys
import time
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import OpenAI

from backend.agents.governance.pride_kernel import assemble_prompt
from backend.agents.governance.few_shot_library import FewShotLibrary
from backend.agents.tools.tool_registry import (
    WebSearchTool,
    PythonExecutorTool,
    FileReaderTool,
    FileWriterTool,
    CalculatorTool,
)
from backend.agents.tools.web_page_reader import WebPageReaderTool

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Use the Manus-provided OpenAI-compatible proxy (key is pre-configured for this endpoint)
OPENAI_BASE_URL = None  # Let the openai client use its default (pre-configured via env)
MODEL = "gpt-4.1-mini"
MAX_TURNS = 10  # Max agent loop iterations per mission
RESULTS_DIR = Path("/home/ubuntu/mission_results")
RESULTS_DIR.mkdir(exist_ok=True)

# Reset the few-shot singleton so it loads from the repo
FewShotLibrary.reset_instance()

# The OpenAI client auto-reads OPENAI_API_KEY and OPENAI_BASE_URL from environment.
# The Manus sandbox pre-configures both, so we use the default client.
client = OpenAI()

# ---------------------------------------------------------------------------
# Tool definitions for the OpenAI function-calling API
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information. "
                "Returns titles, snippets, and URLs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 5).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python_executor",
            "description": (
                "Execute Python code in a sandboxed subprocess. "
                "Returns stdout and stderr."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python code to execute.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds (default 10).",
                        "default": 10,
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_reader",
            "description": "Read the contents of a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file to read.",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_writer",
            "description": "Write content to a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to write the file to.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file.",
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_page_reader",
            "description": (
                "Fetch a web page and return its clean text content. "
                "Use this AFTER web_search to read the full content of a specific URL. "
                "Workflow: web_search to find URLs, then web_page_reader to read them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to fetch (must be http:// or https://).",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return (default 8000, max 32000).",
                        "default": 8000,
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": (
                "Evaluate a mathematical expression. "
                "Supports +, -, *, /, **, sqrt, sin, cos, tan, log, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The mathematical expression to evaluate.",
                    },
                },
                "required": ["expression"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

_tools = {
    "web_search": WebSearchTool(),
    "web_page_reader": WebPageReaderTool(),
    "python_executor": PythonExecutorTool(),
    "file_reader": FileReaderTool(allowed_directories=["/home/ubuntu", "/tmp"]),
    "file_writer": FileWriterTool(allowed_directories=["/home/ubuntu", "/tmp"]),
    "calculator": CalculatorTool(),
}


async def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a named tool with the given arguments."""
    tool = _tools.get(name)
    if not tool:
        return {"success": False, "error": f"Unknown tool: {name}"}
    return await tool.execute(**args)


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


async def run_mission(
    mission_id: str,
    goal: str,
    role_prompt: str,
    scenario: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run a single mission as a ReAct agent loop.

    The agent reasons about the goal, calls tools, observes results,
    and repeats until it produces a final answer or hits MAX_TURNS.

    Returns a dict with: mission_id, goal, status, turns, tool_calls,
    final_answer, elapsed_seconds, files_written.
    """
    system_prompt = assemble_prompt(role_prompt, scenario=scenario)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": goal},
    ]

    turns = []
    files_written = []
    start = time.time()
    final_answer = None
    status = "FAILED"

    print(f"\n{'='*60}")
    print(f"MISSION {mission_id}: Starting")
    print(f"{'='*60}")
    print(f"Goal: {textwrap.shorten(goal, width=120)}")
    print()

    for turn_num in range(1, MAX_TURNS + 1):
        print(f"  [Turn {turn_num}] Calling model...")

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_unset=True))

        turn_record: Dict[str, Any] = {
            "turn": turn_num,
            "tool_calls": [],
            "content": msg.content,
        }

        # If the model called tools, execute them
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                print(f"  [Turn {turn_num}] Tool: {tool_name}({json.dumps(tool_args)[:80]}...)")

                tool_result = await execute_tool(tool_name, tool_args)

                # Track files written
                if tool_name == "file_writer" and tool_result.get("success"):
                    files_written.append(tool_result.get("file_path", ""))

                turn_record["tool_calls"].append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result_summary": str(tool_result)[:200],
                    "success": tool_result.get("success", False),
                })

                # Feed tool result back to the model
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result),
                })

        else:
            # No tool calls — the model produced a final answer
            final_answer = msg.content
            status = "SUCCESS"
            print(f"  [Turn {turn_num}] Final answer received.")
            turns.append(turn_record)
            break

        turns.append(turn_record)

    elapsed = round(time.time() - start, 2)

    if status != "SUCCESS":
        # Hit MAX_TURNS — treat last message content as the answer
        final_answer = messages[-1].get("content", "No answer produced.")
        status = "TIMEOUT"

    print(f"\n  Status: {status} | Turns: {len(turns)} | Time: {elapsed}s")
    if final_answer:
        print(f"  Answer preview: {textwrap.shorten(final_answer, width=200)}")

    return {
        "mission_id": mission_id,
        "goal": goal,
        "status": status,
        "turns": turns,
        "final_answer": final_answer,
        "elapsed_seconds": elapsed,
        "files_written": files_written,
    }


# ---------------------------------------------------------------------------
# Mission definitions
# ---------------------------------------------------------------------------

MISSIONS = [
    {
        "id": "M1_MARKET_ANALYST",
        "scenario": "web_research",
        "role_prompt": (
            "You are a financial research analyst. Your job is to research companies, "
            "extract key financial metrics, and produce clear, concise reports. "
            "Always cite your sources. Always save your final report to the specified file path."
        ),
        "goal": (
            "Research the financial performance of Snowflake Inc. (NYSE: SNOW) for their most "
            "recent quarterly earnings. Find their latest quarterly revenue figure, whether they "
            "beat or missed analyst expectations, and one significant analyst opinion or news "
            "headline about their outlook. Write a 300-word summary of your findings and save it "
            "to /home/ubuntu/mission_results/m1_snowflake_report.md"
        ),
    },
    {
        "id": "M2_CODE_DEBUGGER",
        "scenario": None,
        "role_prompt": (
            "You are a senior Python developer and debugger. Your job is to read code, "
            "identify bugs by running the code, and produce a corrected version. "
            "Always run the original code first to observe the error before proposing a fix. "
            "Always run the fixed code to verify it produces the correct result."
        ),
        "goal": (
            "The Python script at /home/ubuntu/buggy_script.py is producing an incorrect result. "
            "Read the script, run it to observe the bug, identify the root cause, fix it, "
            "and save the corrected script back to /home/ubuntu/buggy_script.py. "
            "Then run the corrected script to confirm it produces the expected output of 30.0."
        ),
    },
    {
        "id": "M3_FACT_CHECKER",
        "scenario": None,
        "role_prompt": (
            "You are a rigorous fact-checker and scientific researcher. Your job is to verify "
            "factual claims using reliable sources and precise calculations. "
            "Always show your work. Always use the calculator tool for numerical computations — "
            "never calculate in your head. Always cite your sources."
        ),
        "goal": (
            "Verify the following claim: 'The distance from the Earth to the Moon is less than "
            "the combined diameters of all the other planets in our solar system.' "
            "Use web search to find the diameter of each planet (Mercury, Venus, Mars, Jupiter, "
            "Saturn, Uranus, Neptune) and the average Earth-Moon distance. "
            "Use the calculator tool to sum the planetary diameters and compare to the Earth-Moon "
            "distance. State clearly whether the claim is TRUE or FALSE, and show all your numbers."
        ),
    },
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    """Run all three missions and save results."""
    print("\n" + "="*60)
    print("CITADEL AGENT WORKFORCE — LIVE MISSION SUITE v1")
    print(f"Started: {datetime.utcnow().isoformat()}Z")
    print("="*60)

    all_results = []

    for mission in MISSIONS:
        result = await run_mission(
            mission_id=mission["id"],
            goal=mission["goal"],
            role_prompt=mission["role_prompt"],
            scenario=mission.get("scenario"),
        )
        all_results.append(result)

        # Save individual mission result
        result_path = RESULTS_DIR / f"{mission['id'].lower()}_result.json"
        result_path.write_text(
            json.dumps(result, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  Result saved: {result_path}")

    # Save combined results
    combined_path = RESULTS_DIR / "all_missions_result.json"
    combined_path.write_text(
        json.dumps(all_results, indent=2, default=str),
        encoding="utf-8",
    )

    # Print summary
    print("\n" + "="*60)
    print("MISSION SUITE SUMMARY")
    print("="*60)
    for r in all_results:
        tool_count = sum(len(t["tool_calls"]) for t in r["turns"])
        print(
            f"  {r['mission_id']}: {r['status']} | "
            f"{len(r['turns'])} turns | {tool_count} tool calls | "
            f"{r['elapsed_seconds']}s"
        )
    print(f"\nAll results saved to: {RESULTS_DIR}")
    print("="*60)

    return all_results


if __name__ == "__main__":
    asyncio.run(main())
