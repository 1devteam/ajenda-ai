# Governance in OmniPath

OmniPath is built with a powerful, integrated governance framework to ensure that your AI operations are safe, compliant, and aligned with your organization's policies. This guide provides an overview of the key governance features.

## Policy Engine

The core of the governance framework is the **Policy Engine**. This allows you to define and enforce rules that govern agent behavior, resource access, and data handling. Policies are managed via the `/api/v1/policies` endpoint.

A policy consists of:

-   **Conditions**: The criteria that trigger the policy (e.g., `agent_risk_level > high`, `asset_tags contains 'pii'`).
-   **Actions**: The automated response when the conditions are met (e.g., `block_action`, `require_approval`, `log_event`).

This allows you to implement rules like, "Any mission targeting a production database must be approved by a senior developer."

## Approval Workflows

For actions that require human oversight, OmniPath provides a built-in **Approval Workflow** system. When a policy action requires approval, an approval request is created and placed in a queue.

Authorized users can then review these requests and either approve or deny them.

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/approvals` | `GET` | List all pending approval requests. |
| `/api/v1/approvals/{request_id}` | `GET` | Get the details of a specific approval request. |
| `/api/v1/approvals/{request_id}/approve` | `POST` | Approve a request, allowing the action to proceed. |
| `/api/v1/approvals/{request_id}/deny` | `POST` | Deny a request, blocking the action permanently. |

## Immutable Audit Trails

Every significant action in OmniPath is recorded as an immutable event in the **Audit Log**. This provides a complete, tamper-proof history of all system activity, which is essential for compliance and security investigations.

Audit events can be accessed via the `/api/v1/audit/events` endpoint, which supports powerful filtering by actor, action, result, and time range.

## Compliance Reporting

OmniPath can automate the generation of compliance reports. The `/api/v1/audit/compliance-reports` endpoint allows you to generate reports for specific regulatory frameworks (e.g., GDPR, HIPAA) or custom internal policies. These reports summarize relevant audit events and policy evaluations, dramatically simplifying the compliance process.

By leveraging these governance features, you can confidently deploy autonomous agents while maintaining control and visibility over their operations.
