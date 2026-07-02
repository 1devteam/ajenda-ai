# API Error Contract

## Structured errors

Machine-readable errors use a single envelope:

```json
{
  "detail": {
    "code": "QUOTA_EXCEEDED",
    "message": "Human-readable summary",
    "field": "tasks_per_month",
    "limit": 50,
    "current": 49,
    "plan": "free"
  }
}
```

Legacy string errors (`{"detail": "..."}`) remain on some routes until migrated.

## Status code guide

| Status | Meaning |
|--------|---------|
| 400 | Client mistake or invalid request state |
| 401 | Missing or invalid credentials (`AUTHENTICATION_REQUIRED`) |
| 402 | Plan or quota limit reached (`QUOTA_EXCEEDED`) |
| 403 | Authenticated but forbidden (RBAC, cross-tenant, suspended tenant) |
| 404 | Resource not found |
| 422 | Request validation failed (`VALIDATION_ERROR`) |
| 429 | Rate limit exceeded (not plan quota) |
| 503 | Dependency unavailable (`DB_UNAVAILABLE`, `QUOTA_CHECK_UNAVAILABLE`) |

## Common codes

| Code | Typical status |
|------|----------------|
| `AUTHENTICATION_REQUIRED` | 401 |
| `QUOTA_EXCEEDED` | 402 |
| `QUOTA_CHECK_UNAVAILABLE` | 503 |
| `VALIDATION_ERROR` | 422 |
| `MISSING_TENANT_ID` | 400 |
| `TENANT_NOT_FOUND` | 404 |
| `CROSS_TENANT_REJECTED` | 403 |