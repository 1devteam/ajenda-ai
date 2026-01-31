# Omnipath Grafana Dashboards

Professional monitoring and visualization dashboards for Omnipath v5.0.

## Overview

This directory contains pre-configured Grafana dashboards for monitoring your Omnipath agent economy system. The dashboards provide real-time insights into:

- **Agent Economy**: Credits, balances, transactions, and resource allocation
- **Mission Performance**: Success rates, durations, queue depths, and agent activity
- **System Health**: API performance, database connections, LLM usage, and uptime

## Dashboards

### 1. Agent Economy Dashboard
**File**: `dashboards/agent_economy.json`

Visualizes the agent economy system with:
- Total economy balance and active agents
- Transaction rates and credit flow
- Agent balance distribution (top 10)
- Resource type distribution
- Top earning and spending agents

**Key Metrics**:
- `omnipath_agent_balance` - Current balance per agent
- `omnipath_transactions_total` - Total transactions by type
- `omnipath_credits_earned_total` - Credits earned by agents
- `omnipath_credits_spent_total` - Credits spent by agents

### 2. Mission Performance Dashboard
**File**: `dashboards/mission_performance.json`

Tracks mission execution and performance:
- Active, completed, and failed missions
- Success rate and completion rate over time
- Mission status and priority distribution
- Average duration and duration histogram (p50, p90, p99)
- Most active agents
- Mission queue depth

**Key Metrics**:
- `omnipath_missions_active` - Currently running missions
- `omnipath_missions_completed_total` - Completed missions counter
- `omnipath_missions_failed_total` - Failed missions counter
- `omnipath_mission_duration_seconds` - Mission execution time

### 3. System Health Dashboard
**File**: `dashboards/system_health.json`

Monitors system infrastructure and performance:
- API request rate and response time (p95)
- Error rates and HTTP status distribution
- Database connection pool usage
- Redis operations
- LLM API calls and token usage
- Event bus message throughput
- System uptime

**Key Metrics**:
- `omnipath_http_requests_total` - HTTP request counter
- `omnipath_http_request_duration_seconds` - Request latency
- `omnipath_db_connections_active` - Active DB connections
- `omnipath_llm_requests_total` - LLM API calls
- `omnipath_llm_tokens_total` - Token usage

## Setup

### Docker Compose Integration

The dashboards are automatically loaded when using the provided Docker Compose configuration:

```yaml
grafana:
  image: grafana/grafana:latest
  volumes:
    - ./grafana/dashboards:/etc/grafana/provisioning/dashboards
    - ./grafana/provisioning:/etc/grafana/provisioning/dashboards/config
  ports:
    - "3000:3000"
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=admin
    - GF_USERS_ALLOW_SIGN_UP=false
```

### Manual Setup

1. **Start Grafana**:
   ```bash
   docker-compose -f docker-compose.v3.yml up -d grafana
   ```

2. **Access Grafana**:
   - URL: http://localhost:3000
   - Default credentials: admin / admin

3. **Import Dashboards**:
   - Navigate to Dashboards → Import
   - Upload each JSON file from `dashboards/` directory
   - Select "Prometheus" as the data source

## Metrics Implementation

To enable these dashboards, your backend must expose Prometheus metrics. Add the following to your FastAPI application:

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from fastapi import Response

# Define metrics
agent_balance = Gauge('omnipath_agent_balance', 'Agent credit balance', ['agent_id'])
transactions_total = Counter('omnipath_transactions_total', 'Total transactions', ['type', 'resource_type'])
missions_active = Gauge('omnipath_missions_active', 'Active missions')
missions_completed = Counter('omnipath_missions_completed_total', 'Completed missions')
http_requests = Counter('omnipath_http_requests_total', 'HTTP requests', ['method', 'endpoint', 'status'])
http_duration = Histogram('omnipath_http_request_duration_seconds', 'HTTP request duration', ['endpoint'])

# Expose metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")
```

## Customization

### Adding New Panels

1. Edit the dashboard JSON file
2. Add a new panel object to the `panels` array
3. Configure the PromQL query in `targets`
4. Set visualization type and options
5. Reload Grafana or re-import the dashboard

### Modifying Queries

Each panel has a `targets` array with PromQL queries. Common patterns:

- **Rate**: `rate(metric[5m])` - Per-second rate over 5 minutes
- **Sum**: `sum(metric)` - Total across all labels
- **Average**: `avg(metric)` - Average value
- **Top K**: `topk(10, metric)` - Top 10 values
- **Percentile**: `histogram_quantile(0.95, rate(metric_bucket[5m]))` - 95th percentile

### Refresh Intervals

Default refresh is 5 seconds. To change:
```json
"refresh": "10s"
```

Options: `5s`, `10s`, `30s`, `1m`, `5m`, `15m`, `30m`, `1h`

## Alerting

Grafana supports alerting on dashboard panels. To set up alerts:

1. Edit a panel
2. Navigate to the "Alert" tab
3. Define alert conditions (e.g., "when avg() is above 100")
4. Configure notification channels (email, Slack, PagerDuty)

### Recommended Alerts

- **High Error Rate**: Alert when error rate > 5% for 5 minutes
- **Low Success Rate**: Alert when mission success rate < 80%
- **High Response Time**: Alert when p95 latency > 3 seconds
- **Low Balance**: Alert when total economy balance < 100 credits
- **Queue Depth**: Alert when mission queue depth > 50

## Troubleshooting

**Dashboards not loading:**
- Check Grafana logs: `docker logs omnipath-grafana`
- Verify provisioning config in `provisioning/dashboards.yml`
- Ensure dashboard JSON files are valid

**No data in panels:**
- Verify Prometheus is scraping metrics: http://localhost:9090/targets
- Check that backend is exposing `/metrics` endpoint
- Verify PromQL queries are correct

**Connection refused to Prometheus:**
- Ensure Prometheus container is running
- Check datasource configuration in `provisioning/datasources.yml`
- Verify network connectivity between containers

## Best Practices

1. **Use templating**: Add dashboard variables for filtering by agent, mission, or time range
2. **Set appropriate time ranges**: Use relative time ranges (e.g., "Last 24 hours")
3. **Add annotations**: Mark deployments or incidents on graphs
4. **Create folders**: Organize dashboards by category (Economy, Performance, Health)
5. **Export regularly**: Back up customized dashboards as JSON files
6. **Monitor performance**: Avoid too many panels or complex queries that slow down Grafana

## Resources

- [Grafana Documentation](https://grafana.com/docs/)
- [PromQL Basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Dashboard Best Practices](https://grafana.com/docs/grafana/latest/best-practices/)

## License

Part of the Omnipath v5.0 project.
