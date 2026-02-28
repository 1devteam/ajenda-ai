# 2. Agents

Agents are the core of Omnipath. They are autonomous entities that can perform tasks, execute tools, and achieve objectives.

## Agent Architecture

Each agent has a defined set of capabilities, a memory store, and access to a suite of tools. The primary agent types are:

- **Commander Agent:** Orchestrates missions and delegates tasks to other agents.
- **Researcher Agent:** Gathers and synthesizes information from various sources.
- **Specialist Agents:** Designed for specific tasks like code generation, data analysis, or tool use.

## Creating an Agent

To create an agent, make a `POST` request to `/api/v1/agents`. You will need to specify the agent type, name, and initial configuration. The response will include the `agent_id`.

## Agent Lifecycle

Agents progress through a lifecycle:

1.  **PENDING:** The agent has been created but is not yet active.
2.  **ACTIVE:** The agent is running and available to execute missions.
3.  **DISABLED:** The agent has been manually disabled.
4.  **TERMINATED:** The agent has been permanently deleted.