# Missions in OmniPath

Missions are the fundamental unit of work in OmniPath. A mission represents a high-level objective that you assign to an agent to complete. This guide explains how to create, manage, and monitor missions.

## What is a Mission?

A mission is defined by a clear, natural language **objective**. For example:

> "Analyze the attached quarterly sales data, identify the top 3 performing regions, and generate a summary report with visualizations."

When you launch a mission, you assign it to a specific agent. That agent will then use its skills and tools to achieve the objective.

## Launching a Mission

To launch a new mission, you make a `POST` request to the Missions API.

**Endpoint**: `POST /api/v1/missions`

**Headers**:
`Authorization: Bearer <your_jwt_token>`

**Body**:

```json
{
  "objective": "Research the current state of autonomous agent platforms and write a competitive analysis.",
  "agent_id": "<your_agent_id>",
  "priority": "high",
  "context": {
    "competitors_to_exclude": ["OpenAI", "Google"],
    "output_format": "markdown"
  },
  "budget": 5.00
}
```

### Key Mission Parameters

-   `objective`: The core goal of the mission.
-   `agent_id`: The ID of the agent assigned to the mission.
-   `priority`: Can be `low`, `normal`, `high`, or `critical`. This affects resource allocation.
-   `context`: A flexible dictionary to provide additional data, instructions, or constraints to the agent.
-   `budget`: An optional credit limit for the mission. If the mission's cost exceeds this budget, it will be automatically aborted.

## Monitoring Mission Progress

Once a mission is launched, it progresses through a defined lifecycle. You can track its status via the API.

| Status | Description |
|---|---|
| `pending` | The mission has been created and is queued for execution. |
| `running` | The mission is actively being executed by the assigned agent. |
| `completed` | The mission finished successfully. The results are available. |
| `failed` | The mission terminated due to an error. The error details are available. |
| `cancelled` | The mission was manually stopped by a user. |
| `paused` | The mission is temporarily paused and can be resumed later. |

## Managing Missions

The Missions API provides endpoints to manage the entire lifecycle of your missions.

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/missions` | `GET` | List all missions for your tenant. Supports filtering by status, agent, and priority. |
| `/api/v1/missions/{mission_id}` | `GET` | Get the detailed status, objective, and results of a specific mission. |
| `/api/v1/missions/{mission_id}/cancel` | `POST` | Cancel a running mission. |
| `/api/v1/missions/{mission_id}/pause` | `POST` | Pause a running mission. |
| `/api/v1/missions/{mission_id}/resume` | `POST` | Resume a paused mission. |

By mastering missions, you can orchestrate complex workflows and unlock the full potential of your agent fleet.
