# Omnipath Grafana Dashboards

Pre-configured Grafana dashboards for monitoring Omnipath v5.0 system performance, agent economy, and LLM usage.

## Dashboards

### 1. System Overview (`system_overview.json`)
**Purpose:** High-level view of system health and performance

**Metrics:**
- Total missions executed
- Active missions count
- Overall success rate
- HTTP request rate
- Mission duration (p50, p95)
- Missions by complexity level
- Agent invocations by model
- HTTP response times
- Error rates

**Use Cases:**
- Quick system health check
- Identify performance bottlenecks
- Monitor overall system load
- Track success rates

### 2. Agent Economy (`agent_economy.json`)
**Purpose:** Monitor the credit-based economy system

**Metrics:**
- Total credits earned
- Total credits spent
- Net economy balance
- Average agent balance
- Credits flow over time
- Top earning agents
- Top spending agents
- Economy health gauge

**Use Cases:**
- Monitor economy balance
- Identify top performers
- Track credit distribution
- Detect economy imbalances

### 3. LLM Performance (`llm_performance.json`)
**Purpose:** Track LLM API usage, costs, and performance

**Metrics:**
- Total LLM API calls
- Total tokens used
- Total LLM costs
- Average latency
- API calls by model
- Token usage by model
- Cost breakdown by model
- Latency by model
- Cost per token efficiency

**Use Cases:**
- Monitor LLM costs
- Compare model performance
- Optimize model selection
- Track token usage

## Setup

### Prerequisites

- Omnipath v5.0 backend running
- Prometheus collecting metrics from `/metrics` endpoint
- Grafana instance

### Installation

#### Option 1: Docker Compose (Recommended)

The dashboards auto-load if you're using the provided `docker-compose.v3.yml`:

```bash
docker-compose -f docker-compose.v3.yml up -d
```

Grafana will be available at: http://localhost:3000
- Username: `admin`
- Password: `admin` (change on first login)

#### Option 2: Manual Import

1. Open Grafana UI
2. Go to Dashboards → Import
3. Upload each JSON file from `grafana/dashboards/`
4. Select "Prometheus" as the datasource
5. Click Import

### Configuration

**Datasource Configuration:**

The provisioning file (`provisioning/datasources.yml`) automatically configures Prometheus:

```yaml
url: http://prometheus:9090
```

If your Prometheus is elsewhere, update this URL.

**Dashboard Provisioning:**

Dashboards auto-load from `provisioning/dashboards.yml`:

```yaml
path: /etc/grafana/provisioning/dashboards
```

This path is mounted in docker-compose.

### Verification

1. Open Grafana: http://localhost:3000
2. Login (admin/admin)
3. Go to Dashboards
4. You should see 3 dashboards:
   - Omnipath System Overview
   - Agent Economy
   - LLM Performance

## Customization

### Adding Panels

1. Open a dashboard
2. Click "Add panel"
3. Write PromQL query
4. Configure visualization
5. Save dashboard

### Available Metrics

All Prometheus metrics exposed by Omnipath:

**Mission Metrics:**
- `omnipath_missions_total{complexity, status}`
- `omnipath_mission_duration_seconds`
- `omnipath_active_missions`

**Agent Metrics:**
- `omnipath_agent_invocations_total{model}`
- `omnipath_agent_errors_total{model}`

**Economy Metrics:**
- `omnipath_credits_earned_total{agent_id}`
- `omnipath_credits_spent_total{agent_id}`
- `omnipath_agent_balance{agent_id}`

**LLM Metrics:**
- `omnipath_llm_api_calls_total{model}`
- `omnipath_llm_tokens_used_total{model}`
- `omnipath_llm_cost_total{model}`
- `omnipath_llm_latency_seconds{model}`

**HTTP Metrics:**
- `omnipath_http_requests_total{method, endpoint, status}`
- `omnipath_http_request_duration_seconds`

### Refresh Rate

Default: 5 seconds

To change:
1. Open dashboard settings (gear icon)
2. Set "Auto refresh" interval
3. Save

## Alerting

### Setting Up Alerts

1. Open a dashboard panel
2. Click "Alert" tab
3. Create alert rule
4. Set threshold (e.g., success rate < 80%)
5. Configure notification channel

### Recommended Alerts

**High Priority:**
- Success rate < 80%
- Error rate > 5%
- Active missions > 100
- Economy net balance < 0

**Medium Priority:**
- LLM latency > 10s
- HTTP p95 > 1s
- Agent errors > 10/min

## Troubleshooting

**No data showing:**
- Check Prometheus is scraping: http://localhost:9090/targets
- Verify backend `/metrics` endpoint works
- Check datasource connection in Grafana

**Dashboards not loading:**
- Check Grafana logs: `docker logs omnipath-grafana`
- Verify provisioning files are mounted
- Restart Grafana: `docker-compose restart grafana`

**Metrics missing:**
- Ensure backend is running with observability enabled
- Check Prometheus config includes backend target
- Verify metrics are being recorded: `curl http://localhost:8000/metrics`

## Tips

- Use time range selector (top right) to view historical data
- Click legend items to hide/show series
- Hover over graphs for detailed values
- Use variables for dynamic filtering
- Export dashboards as JSON for backup

## Integration with Meta-Learning

The dashboards complement the meta-learning system:

1. **Grafana** - Real-time visual monitoring
2. **Meta-Learning API** - Historical analysis and insights
3. **CLI** - Quick command-line access

Use all three together for complete observability!

## Support

For issues or questions:
- Check Grafana docs: https://grafana.com/docs/
- Review Prometheus queries: https://prometheus.io/docs/prometheus/latest/querying/basics/
- Omnipath issues: GitHub repository
