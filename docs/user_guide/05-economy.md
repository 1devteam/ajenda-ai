# The OmniPath Economy

OmniPath includes a sophisticated internal economy to manage and control the costs associated with running autonomous agents. This system provides granular visibility into resource consumption and powerful tools for budget enforcement.

## Credits: The Unit of Work

Every action an agent takes consumes **credits**. This includes:

-   **LLM Calls**: The primary cost driver. Costs are calculated based on the specific model used and the number of input/output tokens.
-   **Tool Use**: Using powerful tools (e.g., a web browser, code interpreter) incurs a credit cost.
-   **Agent Runtime**: Agents consume a small number of credits per minute to cover their operational overhead.

This credit-based system translates all agent activity into a single, understandable metric.

## Budget Enforcement

To prevent cost overruns, you can set a **budget** (in credits) for every mission you launch. If a mission's cumulative cost exceeds its assigned budget, it will be automatically and immediately terminated. This is a critical safeguard for managing your AI operational expenses.

## Tracking Costs and Balances

The Economy API provides several endpoints to monitor your tenant's financial status.

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/economy/balance` | `GET` | Returns the current credit balance for every agent in your tenant. |
| `/api/v1/economy/transactions` | `GET` | Provides a detailed log of all credit transactions (charges and rewards). |
| `/api/v1/economy/stats` | `GET` | Returns high-level economic statistics for your tenant, including total balance, total spend, and average cost per mission. |

## Risk-Based Pricing

The OmniPath economy is integrated with the governance framework. The **Risk-Based Pricing** engine automatically adjusts the credit cost of an action based on its associated risk level. For example, an action that modifies a production database will cost significantly more credits than a read-only query on a staging server.

This system incentivizes the use of safer, lower-risk operations and provides a natural economic brake on potentially dangerous agent behavior.
