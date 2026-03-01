# Agents in OmniPath

Agents are the core actors in the OmniPath ecosystem. They are specialized, autonomous entities designed to execute missions. This guide covers the available agent types and how to manage them.

## Agent Types

OmniPath v2 includes several built-in agent types, each optimized for a specific function. You can also create custom agents by extending the base agent class.

| Agent Type | Description | Key Responsibilities |
|---|---|---|
| **Commander** | The orchestrator. It breaks down complex objectives into sub-tasks and delegates them to other agents. | Mission planning, task delegation, progress monitoring. |
| **Researcher** | The information gatherer. It is skilled at using search tools and web browsers to find and synthesize information. | Web searches, data extraction, report generation. |
| **Analyst** | A specialized sub-class of the Researcher. It focuses on structured data analysis and visualization. | Data cleaning, statistical analysis, chart generation. |
| **Developer** | A specialized sub-class of the Researcher. It is designed for code-related tasks. | Code generation, debugging, API interaction. |

## Creating Your First Agent

Before you can create an agent, you must first have a user account. If you have not created one, please do so via the `/api/v1/auth/register` endpoint.

Once you have authenticated and received your JWT access token, you can create an agent with a `POST` request.

**Endpoint**: `POST /api/v1/agents`

**Headers**:
`Authorization: Bearer <your_jwt_token>`

**Body**:

```json
{
  "name": "My First Commander",
  "type": "Commander",
  "model": "gpt-4-turbo",
  "temperature": 0.7,
  "system_prompt": "You are a world-class project manager. Your goal is to break down complex tasks and ensure they are completed efficiently.",
  "capabilities": ["web_search", "file_system"],
  "config": {}
}
```

The response will contain the full agent object, including its unique `id`.

## Managing Agents

The Agents API provides full CRUD (Create, Read, Update, Delete) functionality for managing your agent fleet.

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/agents` | `GET` | List all agents for your tenant. |
| `/api/v1/agents/{agent_id}` | `GET` | Get detailed information for a specific agent. |
| `/api/v1/agents/{agent_id}` | `PUT` | Update an agent's configuration (e.g., name, model, system prompt). |
| `/api/v1/agents/{agent_id}` | `DELETE` | Deactivate and remove an agent. |

## Agent Lifecycle

Agents in OmniPath follow a simple lifecycle, managed by their `status` field.

| Status | Description |
|---|---|
| `active` | The agent is operational and can be assigned to missions. |
| `inactive` | The agent is temporarily disabled and cannot execute missions. |
| `archived` | The agent has been removed from active service but its history is preserved. |

Understanding and managing your agents is the first step to orchestrating powerful, autonomous operations within OmniPath.
