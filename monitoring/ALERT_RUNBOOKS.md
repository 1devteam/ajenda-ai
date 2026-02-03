# Omnipath Alert Runbooks

**Version**: 1.0  
**Last Updated**: 2026-02-03  
**Built with Pride for Obex Blackvault**

---

## Table of Contents

1. [Critical Alerts](#critical-alerts)
2. [High Priority Alerts](#high-priority-alerts)
3. [Medium Priority Alerts](#medium-priority-alerts)
4. [Low Priority Alerts](#low-priority-alerts)
5. [General Troubleshooting](#general-troubleshooting)

---

## Critical Alerts

### BackendDown

**Severity**: Critical  
**Threshold**: Backend unreachable for > 1 minute

**Impact**: Complete system outage - no API access

**Immediate Actions**:
1. Check if backend container is running:
   ```bash
   docker ps | grep omnipath-backend
   ```

2. If not running, check why it stopped:
   ```bash
   docker logs omnipath-backend --tail 100
   ```

3. Restart backend:
   ```bash
   docker-compose -f docker-compose.v3.yml restart backend
   ```

4. If restart fails, check for:
   - Database connection issues
   - Configuration errors
   - Port conflicts

**Root Cause Investigation**:
- Check recent deployments
- Review application logs
- Verify environment variables
- Check system resources

**Escalation**: If not resolved in 5 minutes, escalate to on-call engineer

---

### HighErrorRate

**Severity**: Critical  
**Threshold**: > 5% of requests returning 5xx errors for > 5 minutes

**Impact**: Degraded service - users experiencing failures

**Immediate Actions**:
1. Check backend logs for errors:
   ```bash
   docker logs -f omnipath-backend | grep ERROR
   ```

2. Check recent deployments:
   ```bash
   git log --oneline -10
   ```

3. Check database connectivity:
   ```bash
   docker exec omnipath-postgres pg_isready
   ```

4. If recent deployment, consider rollback:
   ```bash
   git checkout <previous-commit>
   docker-compose -f docker-compose.v3.yml up -d --build
   ```

**Root Cause Investigation**:
- Identify which endpoints are failing
- Check for database query timeouts
- Review recent code changes
- Check for dependency issues

**Escalation**: If error rate doesn't decrease in 10 minutes, escalate

---

### DatabaseConnectionFailure

**Severity**: Critical  
**Threshold**: Cannot connect to PostgreSQL for > 1 minute

**Impact**: Complete data layer failure

**Immediate Actions**:
1. Check if PostgreSQL is running:
   ```bash
   docker ps | grep omnipath-postgres
   ```

2. Check PostgreSQL logs:
   ```bash
   docker logs omnipath-postgres --tail 100
   ```

3. Try to connect manually:
   ```bash
   docker exec -it omnipath-postgres psql -U omnipath -d omnipath -c "SELECT 1;"
   ```

4. Restart PostgreSQL if needed:
   ```bash
   docker-compose -f docker-compose.v3.yml restart postgres
   ```

**Root Cause Investigation**:
- Check disk space: `df -h`
- Check for corrupted data files
- Review PostgreSQL configuration
- Check for connection pool exhaustion

**Escalation**: Immediate escalation if database doesn't recover in 2 minutes

---

### RedisDown

**Severity**: Critical  
**Threshold**: Redis unreachable for > 1 minute

**Impact**: Caching layer failure - increased database load

**Immediate Actions**:
1. Check if Redis is running:
   ```bash
   docker ps | grep omnipath-redis
   ```

2. Check Redis logs:
   ```bash
   docker logs omnipath-redis --tail 100
   ```

3. Test Redis connectivity:
   ```bash
   docker exec -it omnipath-redis redis-cli PING
   ```

4. Restart Redis:
   ```bash
   docker-compose -f docker-compose.v3.yml restart redis
   ```

**Root Cause Investigation**:
- Check memory usage
- Review Redis configuration
- Check for OOM (Out of Memory) kills
- Verify persistence settings

**Escalation**: If not resolved in 5 minutes, escalate

---

### NATSDisconnected

**Severity**: Critical  
**Threshold**: NATS unreachable for > 1 minute

**Impact**: Event bus failure - inter-agent communication broken

**Immediate Actions**:
1. Check if NATS is running:
   ```bash
   docker ps | grep omnipath-nats
   ```

2. Check NATS logs:
   ```bash
   docker logs omnipath-nats --tail 100
   ```

3. Check NATS status:
   ```bash
   curl http://localhost:8222/varz
   ```

4. Restart NATS:
   ```bash
   docker-compose -f docker-compose.v3.yml restart nats
   ```

**Root Cause Investigation**:
- Check for network issues
- Review NATS configuration
- Check for authentication problems
- Verify cluster connectivity

**Escalation**: If not resolved in 5 minutes, escalate

---

## High Priority Alerts

### HighMissionFailureRate

**Severity**: High  
**Threshold**: > 10% of missions failing for > 10 minutes

**Impact**: Degraded agent performance

**Immediate Actions**:
1. Check recent failed missions:
   ```bash
   docker exec -it omnipath-postgres psql -U omnipath -d omnipath -c \
     "SELECT id, command, error_message FROM missions WHERE state='failed' ORDER BY created_at DESC LIMIT 10;"
   ```

2. Check for common error patterns in logs:
   ```bash
   docker logs omnipath-backend | grep "Mission failed" | tail -20
   ```

3. Check LLM API status (OpenAI, Anthropic, etc.)

4. Review agent configurations

**Root Cause Investigation**:
- Identify which agents are failing
- Check for LLM API rate limits
- Review mission complexity
- Check for timeout issues

**Escalation**: If failure rate doesn't improve in 30 minutes, escalate

---

### SlowAPIResponse

**Severity**: High  
**Threshold**: P95 response time > 1s for > 10 minutes

**Impact**: Poor user experience

**Immediate Actions**:
1. Check which endpoints are slow:
   ```bash
   curl http://localhost:8000/metrics | grep http_request_duration
   ```

2. Check database query performance:
   ```bash
   docker exec -it omnipath-postgres psql -U omnipath -d omnipath -c \
     "SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;"
   ```

3. Check system resources:
   ```bash
   docker stats
   ```

4. Check for slow LLM API calls

**Root Cause Investigation**:
- Profile slow endpoints
- Identify slow database queries
- Check for N+1 query problems
- Review caching effectiveness

**Escalation**: If performance doesn't improve in 20 minutes, escalate

---

### HighMemoryUsage

**Severity**: High  
**Threshold**: Backend memory > 85% for > 5 minutes

**Impact**: Risk of OOM kills and crashes

**Immediate Actions**:
1. Check current memory usage:
   ```bash
   docker stats omnipath-backend --no-stream
   ```

2. Check for memory leaks in logs:
   ```bash
   docker logs omnipath-backend | grep -i "memory\|leak"
   ```

3. Consider restarting backend (temporary fix):
   ```bash
   docker-compose -f docker-compose.v3.yml restart backend
   ```

4. Increase memory limit if needed (in docker-compose.yml)

**Root Cause Investigation**:
- Profile memory usage
- Check for unclosed connections
- Review caching strategies
- Look for memory leaks in recent code

**Escalation**: If memory continues to grow, escalate immediately

---

### HighCPUUsage

**Severity**: High  
**Threshold**: CPU usage > 80% for > 10 minutes

**Impact**: Slow response times, potential throttling

**Immediate Actions**:
1. Check current CPU usage:
   ```bash
   docker stats omnipath-backend --no-stream
   ```

2. Check for CPU-intensive operations in logs

3. Consider horizontal scaling if available

4. Check for infinite loops or runaway processes

**Root Cause Investigation**:
- Profile CPU usage
- Identify hot code paths
- Check for inefficient algorithms
- Review recent code changes

**Escalation**: If CPU doesn't decrease in 20 minutes, escalate

---

### LowAgentBalance

**Severity**: High  
**Threshold**: Agent balance < 100 credits for > 5 minutes

**Impact**: Agent may stop accepting missions

**Immediate Actions**:
1. Check agent balance:
   ```bash
   docker exec -it omnipath-postgres psql -U omnipath -d omnipath -c \
     "SELECT id, name, execution_count, success_count FROM agents WHERE id='<agent_id>';"
   ```

2. Check recent transactions:
   ```bash
   curl http://localhost:8000/api/v1/economy/transactions?agent_id=<agent_id>
   ```

3. Review agent performance

4. Consider credit allocation adjustment

**Root Cause Investigation**:
- Check agent success rate
- Review mission costs
- Analyze earning vs spending patterns
- Check for configuration issues

**Escalation**: Notify economy team for review

---

## Medium Priority Alerts

### IncreasedMissionDuration

**Severity**: Medium  
**Threshold**: P95 mission duration > 300s for > 15 minutes

**Impact**: Slower mission completion

**Actions**:
1. Check LLM API latency
2. Review mission complexity distribution
3. Check database query performance
4. Consider optimizing agent prompts

---

### HighLLMCost

**Severity**: Medium  
**Threshold**: > $10/hour in LLM API costs for > 1 hour

**Impact**: Increased operational costs

**Actions**:
1. Review which agents are using expensive models
2. Check mission complexity
3. Consider using cheaper models for simple tasks
4. Review token usage patterns

---

### LowSuccessRate

**Severity**: Medium  
**Threshold**: Success rate < 80% for > 30 minutes

**Impact**: Reduced system effectiveness

**Actions**:
1. Analyze failed missions
2. Review agent configurations
3. Check for systematic issues
4. Consider agent retraining

---

### HighDatabaseConnections

**Severity**: Medium  
**Threshold**: > 80 active connections for > 10 minutes

**Impact**: Risk of connection exhaustion

**Actions**:
1. Check for connection leaks
2. Review connection pool settings
3. Identify long-running queries
4. Consider increasing max connections

---

### RedisMemoryHigh

**Severity**: Medium  
**Threshold**: Redis memory > 80% for > 10 minutes

**Impact**: Risk of evictions and OOM

**Actions**:
1. Review cache eviction policy
2. Check TTL settings
3. Consider increasing Redis memory
4. Review caching strategy

---

## Low Priority Alerts

### NoRecentMissions

**Severity**: Low  
**Threshold**: No missions for > 1 hour

**Impact**: Possible system idle or connectivity issue

**Actions**:
1. Check if this is expected downtime
2. Verify agent connectivity
3. Check for client-side issues

---

### LowThroughput

**Severity**: Low  
**Threshold**: < 1 req/sec for > 30 minutes

**Impact**: Possible underutilization

**Actions**:
1. Check if this is expected
2. Verify monitoring is working
3. Check for connectivity issues

---

### MetaLearningStale

**Severity**: Low  
**Threshold**: No updates for > 1 hour

**Impact**: Outdated learning insights

**Actions**:
1. Check meta-learning service
2. Verify data pipeline
3. Review recent missions

---

## General Troubleshooting

### Quick Health Check
```bash
# Check all services
docker-compose -f docker-compose.v3.yml ps

# Check backend health
curl http://localhost:8000/health

# Check metrics
curl http://localhost:8000/metrics

# Check logs
docker logs -f omnipath-backend
```

### Common Issues

**Issue**: Container won't start  
**Solution**: Check logs, verify configuration, check port conflicts

**Issue**: Database connection errors  
**Solution**: Verify PostgreSQL is running, check credentials, check network

**Issue**: High latency  
**Solution**: Check database queries, check LLM API, check system resources

**Issue**: Memory leaks  
**Solution**: Restart service, profile memory usage, check for unclosed connections

### Useful Commands

```bash
# View all logs
docker-compose -f docker-compose.v3.yml logs -f

# Restart all services
docker-compose -f docker-compose.v3.yml restart

# Check resource usage
docker stats

# Access database
docker exec -it omnipath-postgres psql -U omnipath -d omnipath

# Access Redis
docker exec -it omnipath-redis redis-cli

# Check NATS
curl http://localhost:8222/varz
```

---

## Escalation Contacts

**Critical Issues**: On-call engineer (PagerDuty)  
**High Priority**: Engineering team lead  
**Medium/Low Priority**: Create GitHub issue

---

**Remember**: Always document your actions and findings when responding to alerts!
