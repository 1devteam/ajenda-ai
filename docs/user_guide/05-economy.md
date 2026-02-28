# 5. Economy & Budgeting

Omnipath operates on a credit-based economy to track and control costs.

## Credits

All actions, including LLM calls, tool use, and agent runtime, consume credits. Your tenant has a credit balance that is debited as agents operate.

## Setting Budgets

You can set a credit budget for each mission. If a mission's cost exceeds its budget, it will be automatically terminated to prevent cost overruns. This provides a critical financial safeguard.

## Tracking Costs

Every mission response includes the `cost` of the mission. You can also query the `/api/v1/economy/balance` endpoint to get your current tenant credit balance and the `/api/v1/economy/transactions` endpoint for a detailed cost breakdown.