# Few-Shot Reference Library: Architecture

**Author**: Manus AI (for Obex Blackvault)
**Status**: Final

---

## 1. Overview

This document specifies the architecture for a scalable few-shot reference library. The goal is to provide agents with concrete examples of both good and bad outputs for specific scenarios, directly in their prompts, to improve the quality and consistency of their responses.

This system is designed to be:
- **Scalable**: Easy to add new scenarios and examples without code changes.
- **Targeted**: Delivers only the relevant examples for the current task.
- **Explicit**: Clearly separates good examples from bad examples and explains *why*.
- **Integrated**: Hooks directly into the existing `assemble_prompt` governance layer.

## 2. Data Schema

The library will be stored as a single JSON file: `backend/agents/governance/few_shot_library.json`. This file will contain an array of `FewShotExample` objects.

### `FewShotExample` Schema

```json
{
  "scenario": "string",
  "type": "positive | negative",
  "input": "string",
  "output": "string",
  "explanation": "string",
  "tags": ["string"]
}
```

| Field | Type | Description |
|---|---|---|
| `scenario` | string | **Required**. The name of the scenario this example applies to (e.g., `"lead_qualification"`, `"proposal_writing"`). This is the primary key for retrieval. |
| `type` | string | **Required**. Either `"positive"` (a good example) or `"negative"` (a bad example). |
| `input` | string | **Required**. A representative input for the scenario. Can contain placeholders like `{company_name}`. |
| `output` | string | **Required**. The corresponding output generated from the input. |
| `explanation` | string | **Required**. A concise explanation of *why* this is a good or bad example, referencing the Pride Protocol. |
| `tags` | array | *Optional*. A list of tags for fine-grained filtering (e.g., `"json_format"`, `"retail_industry"`). |

## 3. Core Components

### `FewShotLibrary` Service

A new class, `FewShotLibrary`, will be created in `backend/agents/governance/few_shot_library.py`. This service will be a singleton responsible for:
- Loading and parsing `few_shot_library.json` into memory on startup.
- Providing a method `get_examples(scenario: str, count: int = 2) -> List[FewShotExample]` to retrieve a balanced set of positive and negative examples for a given scenario.
- Caching the library in memory to avoid repeated file I/O.

### `assemble_prompt` Integration

The `assemble_prompt` function in `pride_kernel.py` will be modified to accept an optional `scenario` argument:

```python
# In backend/agents/governance/pride_kernel.py

def assemble_prompt(
    user_system_prompt: Optional[str] = None,
    scenario: Optional[str] = None
) -> str:
    # ...
```

If a `scenario` is provided, `assemble_prompt` will:
1. Call `FewShotLibrary.get_examples(scenario)` to retrieve the relevant examples.
2. Format these examples into a structured markdown block.
3. Inject this block into the final prompt between the Pride Protocol preamble and the user's system prompt.

## 4. Prompt Injection Format

The injected few-shot examples will be formatted for maximum clarity to the LLM:

```markdown
[... PRIDE PROTOCOL PREAMBLE ...]

---

## Reference Examples for: lead_qualification

### ✅ PROPER ACTION (Positive Example)

**INPUT**:
```
Company: Innovate Inc.
Industry: SaaS
Research: Raised $20M Series B, hiring 50 engineers.
```

**OUTPUT**:
```json
{
  "qualification_score": 0.9,
  "qualification_notes": "Strong fit. Recent funding and hiring indicates growth and budget. Their tech stack is compatible.",
  "contact_title": "VP of Engineering",
  "estimated_value": 75000,
  "probability": 0.6
}
```

**EXPLANATION**: This is a proper action because the output is valid JSON, all fields are populated, and the reasoning is directly tied to the input data.

### ❌ IMPROPER ACTION (Negative Example)

**INPUT**:
```
Company: Legacy Corp.
Industry: Manufacturing
Research: No recent news, website outdated.
```

**OUTPUT**:
```json
{
  "qualification_score": 0.2
}
```

**EXPLANATION**: This is an improper action. The JSON is incomplete, and the score is not justified. It violates the principle of delivering complete work.

---

[... USER'S SYSTEM PROMPT ...]
```

This structure makes the distinction between good and bad examples explicit and reinforces the core tenets of the Pride Protocol in a practical, scenario-specific way.
