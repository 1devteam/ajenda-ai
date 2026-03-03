# Citadel AI — Examples

Runnable examples demonstrating the core patterns of the Citadel AI system.
Each file is self-contained and can be run directly from the repo root.

## Quick Start

```bash
# Set your API key
export OPENAI_API_KEY=your-key-here

# Run any example
cd /path/to/citadel
python3 examples/01_mission_patterns.py
```

## Examples

### `01_mission_patterns.py` — How to run missions

Three patterns for executing agent missions:

| Pattern | Use Case | Cost |
|---|---|---|
| Single-agent | Simple tasks, fast results | Low |
| Workforce (multi-agent) | Complex research, multi-step goals | Medium |
| Streaming with callbacks | Real-time UI updates, monitoring | Low |

### `02_tool_usage.py` — How to use each tool directly

Demonstrates every registered tool with working examples:

| Tool | What It Does |
|---|---|
| `SearchMemoryTool` | DuckDuckGo search with per-session deduplication cache |
| `WebPageReaderTool` | Fetch and extract clean text from any URL |
| `PythonExecutorTool` | Run Python code in a sandboxed subprocess |
| `CalculatorTool` | Evaluate mathematical expressions safely |
| `EmailTool` | Send SMTP emails (dry-run when unconfigured) |

Also demonstrates the **search → read → synthesise** chain — the correct
two-step research pattern that avoids redundant re-queries.

### `03_revenue_pipeline.py` — The full sales pipeline

Three pipeline patterns:

| Pattern | Description |
|---|---|
| Step-by-step | Run each stage individually for maximum visibility |
| Full saga | One call, automatic compensation on failure |
| Lead discovery | AI discovers prospects matching your ICP |

### `04_first_real_mission.py` — Your first live mission

A complete, production-ready script for your first real revenue run.
Edit the `YOUR_VALUE_PROPOSITION` and `YOUR_IDEAL_CUSTOMER_PROFILE` constants,
then run:

```bash
# Dry run (no emails sent)
python3 examples/04_first_real_mission.py

# Live run (sends real emails — requires SMTP config)
SEND_LIVE=true python3 examples/04_first_real_mission.py
```

## Email Configuration

To enable live email sending, set these environment variables:

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your@gmail.com
export SMTP_PASSWORD=your-app-password   # Use a Gmail App Password
```

Or add them to your `.env` file.

## Code Style Reference

All Citadel AI code follows these conventions:

```python
# Type hints on all functions
async def qualify_lead(
    lead: dict[str, str],
    value_proposition: str,
    ideal_customer_profile: str,
) -> dict[str, float | str]:
    ...

# Docstrings on all public methods
"""
Brief one-line summary.

Longer description if needed.

Args:
    lead: The lead data dict with company_name, industry, etc.
    value_proposition: What problem we solve for the customer.

Returns:
    Dict with qualification_score (0.0–1.0) and qualification_notes.
"""

# Explicit error handling — never silent failures
try:
    result = await agent.qualify_lead(lead)
except QualificationError as e:
    logger.error("Qualification failed for %s: %s", lead["company_name"], e)
    return {"qualification_score": 0.0, "error": str(e)}

# Constants at module level, not magic strings inline
QUALIFICATION_THRESHOLD = 0.6
MAX_RETRIES = 3
DEFAULT_MODEL = "gpt-4.1-mini"
```
