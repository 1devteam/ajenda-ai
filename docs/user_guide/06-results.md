# 6. Interpreting Results

Understanding the output of a mission is key to leveraging Omnipath effectively.

## Mission Outcome

The final result of a mission is delivered in the `output` field of the mission object. This can be text, structured data (JSON), or links to generated artifacts.

## Agent Performance

The `/api/v1/agents/{agent_id}/performance` endpoint provides detailed metrics on an agent's performance, including success rate, average mission cost, and efficiency.

## Lineage Tracking

Every piece of data and every action within Omnipath has a complete, auditable lineage. The `lineage_id` allows you to trace the origin of any result back through the entire chain of agents, tools, and data sources that produced it. This is critical for debugging, compliance, and understanding complex agent behavior.