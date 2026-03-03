"""
Mission 1 Re-Run — WebPageReaderTool Validation
================================================
Re-runs Mission 1 (Market Analyst) with the new WebPageReaderTool available.
This proves the fix works end-to-end.

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

import asyncio
import json
import sys
import time
import textwrap
from pathlib import Path
from typing import Any, Dict

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import OpenAI  # noqa: E402

from backend.agents.governance.pride_kernel import assemble_prompt  # noqa: E402
from backend.agents.governance.few_shot_library import FewShotLibrary  # noqa: E402
from backend.agents.tools.tool_registry import (  # noqa: E402
    WebSearchTool,
    PythonExecutorTool,
    FileReaderTool,
    FileWriterTool,
    CalculatorTool,
)
from backend.agents.tools.web_page_reader import WebPageReaderTool  # noqa: E402

# Reset singleton so it loads from the repo path
FewShotLibrary.reset_instance()

client = OpenAI()

MODEL = "gpt-4.1-mini"
MAX_TURNS = 12
RESULTS_DIR = Path("/home/ubuntu/mission_results")
RESULTS_DIR.mkdir(exist_ok=True)

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information. "
                "Returns titles, snippets, and URLs. "
                "Use this to FIND relevant URLs, then use web_page_reader to READ them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Max results (default 5).",
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
            "name": "web_page_reader",
            "description": (
                "Fetch a web page and return its FULL clean text content. "
                "Use this AFTER web_search to read the complete content of a URL. "
                "ALWAYS use this when a search result URL looks relevant — "
                "do NOT re-search when you already have a relevant URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to fetch (http:// or https://).",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Max characters to return (default 8000).",
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
]

_tools: Dict[str, Any] = {
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


async def run_m1() -> Dict[str, Any]:
    """Run Mission 1 with the new web_page_reader tool."""
    role_prompt = (
        "You are a financial research analyst. Your job is to research companies, "
        "extract key financial metrics, and produce clear, concise reports. "
        "Always cite your sources. Always save your final report to the specified file path."
    )
    goal = (
        "Research the financial performance of Snowflake Inc. (NYSE: SNOW) for their most "
        "recent quarterly earnings. Find their latest quarterly revenue figure, whether they "
        "beat or missed analyst expectations, and one significant analyst opinion or news "
        "headline about their outlook. Write a 300-word summary of your findings and save it "
        "to /home/ubuntu/mission_results/m1_snowflake_report_v2.md"
    )

    system_prompt = assemble_prompt(role_prompt, scenario="web_research")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": goal},
    ]

    turns = []
    files_written = []
    start = time.time()
    final_answer = None
    status = "FAILED"

    print("\n" + "=" * 60)
    print("MISSION 1 RE-RUN: Market Analyst (with WebPageReaderTool)")
    print("=" * 60)
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

        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                arg_preview = json.dumps(tool_args)[:100]
                print(f"  [Turn {turn_num}] Tool: {tool_name}({arg_preview})")

                tool_result = await execute_tool(tool_name, tool_args)

                if tool_name == "file_writer" and tool_result.get("success"):
                    files_written.append(tool_result.get("file_path", ""))

                turn_record["tool_calls"].append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result_summary": str(tool_result)[:300],
                    "success": tool_result.get("success", False),
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result),
                })
        else:
            final_answer = msg.content
            status = "SUCCESS"
            print(f"  [Turn {turn_num}] Final answer received.")
            turns.append(turn_record)
            break

        turns.append(turn_record)

    elapsed = round(time.time() - start, 2)

    if status != "SUCCESS":
        final_answer = messages[-1].get("content", "No answer produced.")
        status = "TIMEOUT"

    total_tool_calls = sum(len(t["tool_calls"]) for t in turns)
    web_page_reads = sum(
        1 for t in turns
        for tc in t["tool_calls"]
        if tc["tool"] == "web_page_reader"
    )
    web_searches = sum(
        1 for t in turns
        for tc in t["tool_calls"]
        if tc["tool"] == "web_search"
    )

    print(f"\n  Status: {status} | Turns: {len(turns)} | Time: {elapsed}s")
    print(f"  Tool calls: {total_tool_calls} total "
          f"({web_searches} searches, {web_page_reads} page reads)")
    if final_answer:
        print(f"  Answer preview: {textwrap.shorten(final_answer or '', width=200)}")

    result = {
        "mission_id": "M1_MARKET_ANALYST_V2",
        "status": status,
        "turns": len(turns),
        "total_tool_calls": total_tool_calls,
        "web_searches": web_searches,
        "web_page_reads": web_page_reads,
        "elapsed_seconds": elapsed,
        "files_written": files_written,
        "final_answer": final_answer,
        "turn_detail": turns,
    }

    result_path = RESULTS_DIR / "m1_rerun_result.json"
    result_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\n  Full result saved to: {result_path}")

    return result


if __name__ == "__main__":
    asyncio.run(run_m1())
