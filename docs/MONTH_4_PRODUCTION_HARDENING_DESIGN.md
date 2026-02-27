# MONTH 4: PRODUCTION HARDENING DESIGN

**Goal:** Transform governance system from in-memory prototype to production-ready, integrated, secure, and deployable platform.

**Timeline:** 4 weeks (Mar 20 - Apr 16, 2026)
**Delivery:** Single commit at end of Month 4
**Standards:** Pride-based development (95%+ proper actions)

---

## OVERVIEW

### Current State
- 13,000+ lines governance code (Months 2-3)
- 360 tests, 94% pass rate
- 70+ API endpoints
- In-memory storage (dictionaries)
- No authentication
- No persistence
- Not integrated with core platform
- No deployment automation

### Target State
- Production-grade persistence (PostgreSQL + Redis)
- Integrated with Omnipath agents/missions
- Secured with authentication & authorization
- Performance optimized (1000+ req/sec)
- Containerized and deployable
- Monitored with Prometheus/Grafana
- CI/CD automated

---

## WEEK 1: PRODUCTION INFRASTRUCTURE

### Goal
Replace in-memory storage with production-grade persistence and caching.

### Components

#### 1.1 PostgreSQL Schema Design
**Tables:**
- `governance_assets` - Asset registry (replaces in-memory dict)
- `governance_lineage_events` - Lineage tracking
- `governance_risk_scores` - Risk assessments with history
- `governance_policies` - Policy definitions
- `governance_policy_evaluations` - Evaluation results cache
- `governance_audit_events` - Audit trail
- `governance_approvals` - Approval workflows
- `governance_compliance_findings` - Compliance check results
- `governance_webhooks` - Webhook subscriptions
- `governance_api_keys` - API key management

**Indexes:**
- Asset lookups by ID, type, owner, status, tags
- Lineage by asset_id, event_type, timestamp
- Risk scores by asset_id, tier, calculated_at
- Policies by status, priority, applies_to
- Audit events by asset_id, actor_id, event_type, timestamp
- Approvals by asset_id, status, required_authority

**Migrations:**
- Alembic migration scripts
- Seed data for default policies
- Rollback support

#### 1.2 Redis Caching Strategy
**Cache Keys:**
- `governance:risk:{asset_id}` - Risk scores (30-day TTL)
- `governance:policy_eval:{asset_id}:{policy_id}` - Policy evaluations (5-min TTL)
- `governance:asset:{asset_id}` - Asset metadata (1-hour TTL)
- `governance:compliance:{asset_id}` - Compliance status (1-hour TTL)
- `governance:approval_queue:{tier}` - Approval queues (real-time)

**Cache Invalidation:**
- Asset update → invalidate asset, risk, compliance caches
- Policy change → invalidate all policy_eval caches
- Risk recalculation → invalidate risk cache
- Approval action → invalidate approval_queue cache

#### 1.3 Database Abstraction Layer
**Repository Pattern:**
```python
class AssetRepository:
    def create(asset: AIAsset) -> AIAsset
    def get(asset_id: str) -> Optional[AIAsset]
    def list(filters: dict) -> List[AIAsset]
    def update(asset_id: str, **kwargs) -> AIAsset
    def delete(asset_id: str) -> bool
```

**Benefits:**
- Decouples business logic from storage
- Easy to test (mock repositories)
- Can swap storage backends
- Consistent error handling

#### 1.4 Message Queue Integration
**Use Cases:**
- Async webhook delivery
- Async compliance checks
- Async risk recalculation
- Async alert notifications

**Implementation:**
- Use existing NATS.io from core platform
- Create governance-specific subjects:
  - `governance.webhooks.{event_type}`
  - `governance.compliance.check`
  - `governance.risk.recalculate`
  - `governance.alerts.{severity}`

### Deliverables
- PostgreSQL schema (10 tables)
- Alembic migrations (3 files)
- Repository implementations (10 classes, 1,500 lines)
- Redis cache manager (300 lines)
- NATS integration (200 lines)
- Tests (50 tests)

---

## WEEK 2: CORE PLATFORM INTEGRATION

### Goal
Connect governance system to Omnipath agents, missions, and economy.

### Components

#### 2.1 Agent Lifecycle Hooks
**Registration Hook:**
- Intercept agent creation in `backend/agents/agent_service.py`
- Auto-register in governance asset registry
- Apply default tags based on agent capabilities
- Calculate initial risk score
- Check policy compliance before allowing registration

**Update Hook:**
- Track agent modifications (model changes, capability updates)
- Recalculate risk score
- Create lineage event
- Check if approval required for changes

**Deletion Hook:**
- Mark asset as archived in registry
- Preserve audit trail
- Check for dependent assets

#### 2.2 Mission Execution Hooks
**Pre-Execution:**
- Check agent compliance status
- Evaluate applicable policies
- Require approval if high-risk
- Block if policy denies
- Log audit event

**During Execution:**
- Track data accessed (for contextual tagging)
- Monitor API calls (for risk assessment)
- Detect anomalies (unusual behavior)

**Post-Execution:**
- Update agent performance metrics
- Adjust risk score based on outcomes
- Create lineage event
- Generate compliance report

#### 2.3 Economy Integration
**Charging:**
- High-risk operations cost more credits
- Policy violations incur penalties
- Approval requests cost credits

**Rewards:**
- Compliant agents earn bonus credits
- Successful audits reward owners
- Policy adherence increases agent value

**Implementation:**
```python
# In mission executor
risk_score = governance.get_risk_score(agent_id)
if risk_score.tier == RiskTier.HIGH:
    cost_multiplier = 1.5
elif risk_score.tier == RiskTier.CRITICAL:
    cost_multiplier = 2.0
else:
    cost_multiplier = 1.0

mission_cost = base_cost * cost_multiplier
economy.charge_agent(agent_id, mission_cost)
```

#### 2.4 Real-World Testing
**Test Scenarios:**
1. Create agent → Verify auto-registration
2. Execute mission → Verify policy enforcement
3. High-risk agent → Verify approval required
4. Policy violation → Verify mission blocked
5. Compliant agent → Verify credit reward

### Deliverables
- Agent hooks (3 files, 600 lines)
- Mission hooks (2 files, 400 lines)
- Economy integration (1 file, 200 lines)
- Integration tests (30 tests)

---

## WEEK 3: SECURITY & PERFORMANCE

### Goal
Harden system for production: authentication, authorization, rate limiting, optimization.

### Components

#### 3.1 Authentication & Authorization
**JWT Integration:**
- Reuse existing JWT from core platform
- Add governance-specific claims:
  - `governance_role`: guest, user, operator, admin, compliance_officer
  - `governance_permissions`: list of allowed operations

**API Key Support:**
- Generate API keys for programmatic access
- Store hashed keys in `governance_api_keys` table
- Support key rotation and expiration
- Rate limit per key

**RBAC Matrix:**
| Role | Permissions |
|------|-------------|
| Guest | Read assets, policies |
| User | + Create assets, request approvals |
| Operator | + Execute high-risk with oversight |
| Admin | + Approve medium/high, manage policies |
| Compliance Officer | + Override, audit access, critical approvals |

**Implementation:**
```python
@router.post("/api/v1/risk/approvals/{id}/approve")
@require_auth
@require_role(AuthorityLevel.ADMIN)
async def approve_request(id: str, user: User = Depends(get_current_user)):
    # Check if user has sufficient authority
    # Process approval
    # Return result
```

#### 3.2 Rate Limiting
**Strategy:**
- Per-IP rate limiting (100 req/min)
- Per-user rate limiting (1000 req/hour)
- Per-API-key rate limiting (configurable)
- Burst allowance (10 req/sec)

**Implementation:**
- Use Redis for rate limit counters
- Sliding window algorithm
- Return 429 Too Many Requests with Retry-After header

**Endpoints:**
- Read operations: 100 req/min
- Write operations: 20 req/min
- Approval operations: 10 req/min
- Webhook delivery: 50 req/min

#### 3.3 Input Validation & Sanitization
**Pydantic Models:**
- Strict validation for all API inputs
- Regex patterns for IDs, names, emails
- Length limits for strings
- Range checks for numbers
- Enum validation for status fields

**SQL Injection Protection:**
- Use SQLAlchemy ORM (parameterized queries)
- Never concatenate user input into SQL
- Validate all filter parameters

**XSS Protection:**
- Escape HTML in user-generated content
- Sanitize markdown rendering
- CSP headers

#### 3.4 Performance Optimization
**Database Optimization:**
- Add indexes for common queries
- Use connection pooling (10-20 connections)
- Implement query result caching
- Use database read replicas for heavy reads

**Caching Strategy:**
- Cache frequently accessed data (assets, policies)
- Cache expensive computations (risk scores, compliance checks)
- Use cache warming for critical data
- Implement cache-aside pattern

**Query Optimization:**
- Use eager loading for relationships
- Implement pagination (limit 100 items)
- Add database query logging
- Profile slow queries

**Load Testing:**
- Target: 1000 req/sec
- Scenarios: Read-heavy, write-heavy, mixed
- Tools: Locust or k6
- Metrics: Response time (p50, p95, p99), error rate, throughput

### Deliverables
- Auth middleware (2 files, 400 lines)
- Rate limiting (1 file, 200 lines)
- Input validation (enhanced Pydantic models)
- Performance optimizations (database, caching)
- Load tests (3 scenarios)
- Security audit report

---

## WEEK 4: DEPLOYMENT & MONITORING

### Goal
Containerize, deploy, monitor, and automate governance system.

### Components

#### 4.1 Dockerization
**Governance Service Dockerfile:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Docker Compose:**
- Add governance service to existing `docker-compose.yml`
- Connect to existing PostgreSQL, Redis, NATS
- Environment variables for configuration
- Health checks

#### 4.2 Kubernetes Deployment
**Manifests:**
- Deployment (3 replicas)
- Service (ClusterIP)
- Ingress (HTTPS with cert-manager)
- ConfigMap (configuration)
- Secret (credentials)
- HorizontalPodAutoscaler (scale 3-10 pods)

**Resource Limits:**
- CPU: 500m request, 2000m limit
- Memory: 512Mi request, 2Gi limit

**Health Checks:**
- Liveness probe: `/health`
- Readiness probe: `/health/ready`
- Startup probe: `/health/startup`

#### 4.3 CI/CD Pipeline
**GitHub Actions Workflow:**
```yaml
name: Governance CI/CD

on:
  push:
    branches: [main]
    paths:
      - 'backend/agents/compliance/**'
      - 'backend/api/routes/governance/**'
      - 'tests/test_*governance*'

jobs:
  test:
    - Lint (black, flake8, mypy)
    - Test (pytest with coverage)
    - Security scan (bandit, safety)
  
  build:
    - Build Docker image
    - Push to registry
    - Tag with commit SHA
  
  deploy:
    - Deploy to staging
    - Run smoke tests
    - Manual approval
    - Deploy to production
```

**Deployment Strategy:**
- Blue-green deployment
- Zero-downtime rolling updates
- Automatic rollback on failure

#### 4.4 Prometheus Metrics
**Custom Metrics:**
- `governance_assets_total{type, status}` - Asset counts
- `governance_risk_score{tier}` - Risk score distribution
- `governance_policy_evaluations_total{result}` - Policy eval counts
- `governance_approvals_pending{tier}` - Approval queue depth
- `governance_compliance_checks_total{status}` - Compliance check results
- `governance_api_requests_total{endpoint, status}` - API usage
- `governance_api_latency_seconds{endpoint}` - API response times
- `governance_cache_hits_total` - Cache hit rate
- `governance_cache_misses_total` - Cache miss rate

**Implementation:**
```python
from prometheus_client import Counter, Histogram, Gauge

policy_evaluations = Counter(
    'governance_policy_evaluations_total',
    'Total policy evaluations',
    ['result']
)

api_latency = Histogram(
    'governance_api_latency_seconds',
    'API request latency',
    ['endpoint']
)
```

#### 4.5 Grafana Dashboards
**Dashboard 1: Governance Overview**
- Total assets by type
- Risk score distribution
- Compliance posture
- Approval queue depth
- Policy evaluation rate

**Dashboard 2: API Performance**
- Request rate by endpoint
- Response time (p50, p95, p99)
- Error rate
- Cache hit rate
- Database query time

**Dashboard 3: Security & Compliance**
- Failed authentication attempts
- Rate limit violations
- Policy violations
- High-risk asset count
- Audit event timeline

#### 4.6 Alert Rules
**Critical Alerts:**
- Service down (no heartbeat for 1 min)
- High error rate (>5% for 5 min)
- Critical risk asset created
- Policy violation detected
- Approval queue backlog (>10 pending)

**Warning Alerts:**
- High response time (p95 >500ms for 10 min)
- Low cache hit rate (<70% for 15 min)
- Database connection pool exhausted
- High-risk asset count increasing

**Notification Channels:**
- Slack (critical alerts)
- Email (warning alerts)
- PagerDuty (production incidents)

### Deliverables
- Dockerfile (1 file)
- Kubernetes manifests (6 files)
- GitHub Actions workflow (1 file)
- Prometheus metrics (integrated into code)
- Grafana dashboards (3 JSON files)
- Alert rules (1 YAML file)
- Deployment runbook (1 doc)

---

## TESTING STRATEGY

### Unit Tests
- Repository layer (database operations)
- Cache manager (Redis operations)
- Auth middleware (JWT validation)
- Rate limiter (Redis counters)
- Integration hooks (agent/mission lifecycle)

### Integration Tests
- End-to-end agent registration → governance
- Mission execution → policy enforcement
- Approval workflow → economy integration
- Webhook delivery → external systems

### Performance Tests
- Load test: 1000 req/sec sustained
- Stress test: Find breaking point
- Spike test: Handle traffic bursts
- Soak test: 24-hour stability

### Security Tests
- Authentication bypass attempts
- Authorization escalation attempts
- SQL injection attempts
- Rate limit evasion attempts
- Input validation fuzzing

---

## MIGRATION STRATEGY

### Phase 1: Parallel Run (Week 1-2)
- Keep in-memory storage
- Add database persistence alongside
- Write to both, read from database
- Verify data consistency

### Phase 2: Database Primary (Week 3)
- Switch to database as primary
- Keep in-memory as fallback
- Monitor performance
- Fix any issues

### Phase 3: Remove In-Memory (Week 4)
- Remove in-memory storage
- Database-only mode
- Final validation
- Production deployment

---

## ROLLBACK PLAN

**If issues found:**
1. Revert to previous commit
2. Redeploy previous version
3. Restore database from backup
4. Investigate issue
5. Fix and redeploy

**Database Rollback:**
- Alembic downgrade migrations
- Restore from backup if needed
- Verify data integrity

---

## SUCCESS CRITERIA

### Week 1: Infrastructure
- ✅ All data persisted to PostgreSQL
- ✅ Redis caching working (>80% hit rate)
- ✅ NATS integration functional
- ✅ 50+ tests passing

### Week 2: Integration
- ✅ Agents auto-register on creation
- ✅ Missions enforce policies
- ✅ Economy integration working
- ✅ 30+ integration tests passing

### Week 3: Security & Performance
- ✅ Authentication required for all endpoints
- ✅ Rate limiting enforced
- ✅ Load test: 1000 req/sec achieved
- ✅ Security audit: No critical issues

### Week 4: Deployment
- ✅ Docker image builds successfully
- ✅ Kubernetes deployment working
- ✅ CI/CD pipeline automated
- ✅ Grafana dashboards populated
- ✅ Alerts firing correctly

---

## TIMELINE

**Week 1 (Mar 20-26):** Production Infrastructure
**Week 2 (Mar 27-Apr 2):** Core Platform Integration
**Week 3 (Apr 3-9):** Security & Performance
**Week 4 (Apr 10-16):** Deployment & Monitoring

**Final Commit:** Apr 16, 2026

---

**Built with Pride for Obex Blackvault**
