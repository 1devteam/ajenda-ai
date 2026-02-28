# 3. Incident Response

## Playbook: `HighErrorRate`

1.  **Check the Logs Dashboard:** Filter for `level="ERROR"` or `level="CRITICAL"` to identify the root cause. Look for stack traces or specific error messages.
2.  **Check the API Performance Dashboard:** Identify which specific endpoints are failing.
3.  **Check System Health Dashboard:** Look for resource exhaustion (CPU, memory, DB connections).
4.  **Rollback:** If the issue was caused by a recent deployment, consider rolling back to the previous version.