# Runbook: Monitoring and Alerting

This runbook provides an overview of the OmniPath observability stack and procedures for monitoring the health and performance of the platform.

## The Observability Stack

The OmniPath monitoring stack consists of several integrated components, all of which are included in the `docker-compose.production.yml` file.

| Component | Purpose | Access URL |
|---|---|---|
| **Prometheus** | Collects and stores time-series metrics from all services. | `http://localhost:9090` |
| **Grafana** | Visualizes metrics in pre-built dashboards. | `http://localhost:3000` |
| **Jaeger** | Provides distributed tracing to track requests as they flow through the system. | `http://localhost:16686` |
| **Alertmanager** | Manages and routes alerts from Prometheus to configured notification channels. | `http://localhost:9093` |

## Key Dashboards

Grafana is pre-loaded with several dashboards that provide insight into different aspects of the system. The most important ones are:

-   **OmniPath Service Dashboard**: The main dashboard for monitoring the health of the backend API. It includes panels for request rate, error rate, latency (p95, p99), and resource usage.
-   **PostgreSQL Database**: Detailed metrics for the PostgreSQL database, including query performance, connection counts, and disk usage.
-   **NATS Monitoring**: Metrics for the NATS event bus, including message rates, pending messages, and connection counts.
-   **Host Metrics**: System-level metrics for the server running the Docker containers, including CPU, memory, and network usage.

## Alerting

Prometheus is configured with a set of alerting rules defined in `monitoring/prometheus/rules.yml`. These rules will fire alerts when certain thresholds are breached. The alerts are then routed by Alertmanager to your configured notification channels (e.g., Slack, PagerDuty).

### Critical Alerts

These alerts require immediate attention.

| Alert Name | Description | Action |
|---|---|---|
| `OmnipathBackendDown` | The main OmniPath API service is not responding to health checks. | Check the container logs (`docker-compose logs backend`) to identify the cause of the crash. Restart the container. |
| `PostgresqlDown` | The PostgreSQL database is unreachable. | Check the `postgres` container logs. Ensure the server has enough disk space. |
| `HighApiErrorRate` | The API is returning a high percentage of 5xx server errors. | Check the backend logs for exceptions. Look at the Jaeger traces for the failing requests to pinpoint the root cause. |

### Warning Alerts

These alerts indicate potential problems that should be investigated.

| Alert Name | Description | Action |
|---|---|---|
| `HighApiLatency` | API response times are elevated. | Check the database dashboard for slow queries. Look for resource contention (CPU, memory) on the host. |
| `NatsQueueFull` | The NATS message queue is backing up, indicating a subscriber is not processing messages fast enough. | Identify the slow subscriber by checking the NATS monitoring dashboard. Check the logs for that service. |

For a full list of all alerts and their runbooks, see `monitoring/ALERT_RUNBOOKS.md`.
