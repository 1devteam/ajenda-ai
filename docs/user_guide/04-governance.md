# 4. Governance & Compliance

Omnipath includes a robust governance framework to manage risk and ensure compliance.

## Risk Tiers

Every agent and asset is assigned a risk tier based on its capabilities and the data it handles:

- **Minimal:** Low-risk, internal tools.
- **Limited:** Access to non-sensitive external resources.
- **High:** Access to sensitive data or critical systems.
- **Unacceptable:** Poses a significant security or financial risk.

## Approval Workflows

Actions involving high-risk agents or assets require explicit approval. When such an action is attempted, an approval request is created. An authorized user must then approve or deny the request via the `/api/v1/approvals` endpoint before the action can proceed.

## Policy Engine

The policy engine automatically enforces rules based on regulatory frameworks (e.g., GDPR, SOC2) and custom organizational policies. Violations are logged, and in some cases, actions are automatically blocked.