# Understanding Mission Results

Once a mission is complete, understanding its output and the process that generated it is crucial. This guide covers how to access and interpret mission results in OmniPath.

## Accessing Mission Output

The final output of a successfully completed mission is stored in the `result` field of the mission object. You can retrieve this by querying the mission's endpoint.

**Endpoint**: `GET /api/v1/missions/{mission_id}`

**Headers**:
`Authorization: Bearer <your_jwt_token>`

The `result` field is a JSON object that can contain:

-   A final text summary.
-   Structured data (e.g., a list of findings).
-   Links to artifacts created during the mission (e.g., reports, code files, images).

If a mission fails, the `error` field will contain a detailed message explaining the cause of the failure.

## Mission Execution History

For a detailed, step-by-step breakdown of how a mission was executed, you can query the mission's execution history.

**Endpoint**: `GET /api/v1/missions/{mission_id}/history`

This endpoint returns a timeline of every action the agent took, including:

-   Tool calls made.
-   LLM prompts and responses.
-   Internal thoughts and reasoning steps.

This level of detail is invaluable for debugging agent behavior and understanding its decision-making process.

## Asset and Lineage Tracking

OmniPath includes a powerful **Asset Registry** that tracks every piece of data and every artifact created by your agents. Each asset is assigned a unique ID and has a complete, auditable lineage.

This means you can trace any result back to its origin. For example, you can see which agent created a specific report, what data sources it used, and which missions it was involved in. This is critical for compliance, data governance, and ensuring the reliability of your AI-generated outputs.

Lineage information can be accessed via the `/api/v1/registry/assets/{asset_id}/lineage` endpoint.

By combining the final mission result with the detailed execution history and asset lineage, you gain a complete and trustworthy picture of your agent's work.
