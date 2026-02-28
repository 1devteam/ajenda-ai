# 3. Missions

A mission is a high-level objective that you assign to an agent.

## Defining a Mission

To define a mission, you provide a clear, natural language prompt describing the goal. For example:

> "Research the market trends for AI-powered code generation tools and produce a 5-page report summarizing the key players, market size, and future outlook."

## Launching a Mission

To launch a mission, make a `POST` request to `/api/v1/missions`. You will need to provide:

- `prompt`: The mission objective.
- `primary_agent_id`: The ID of the agent to lead the mission.
- `budget`: An optional credit budget for the mission.

## Mission Status

Missions progress through several statuses:

- **PENDING:** The mission has been created and is awaiting execution.
- **IN_PROGRESS:** The mission is actively being executed by the agent.
- **COMPLETED:** The mission finished successfully.
- **FAILED:** The mission failed due to an error or budget exhaustion.
- **CANCELED:** The mission was manually canceled.