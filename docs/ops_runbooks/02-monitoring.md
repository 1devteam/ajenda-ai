# 2. Monitoring & Alerting

## Dashboards

Grafana is pre-configured with several key dashboards:

- **API Performance:** Latency, error rates, request volume.
- **System Health:** CPU, memory, DB connections.
- **Governance:** Risk scores, compliance status.
- **Logs:** Search and explore structured application logs.

## Key Alerts

The system will automatically alert on critical conditions. The most important alerts to watch for are:

- `OmnipathBackendDown`: The main API service is not reachable.
- `HighErrorRate`: The API is returning a high percentage of 5xx errors.
- `HighLatency`: API response times are exceeding thresholds.
- `PostgresqlDown`: The primary database is down.
- `CriticalRiskAssetCreated`: An agent or asset with an "Unacceptable" risk tier has been created.