# MONTH 3 WEEKS 2-4 INTEGRATED DESIGN

**Objective:** Build Audit Automation, Integration Layer, and UI Dashboard as one cohesive system with single commit at Week 4.

**Design Philosophy:** Deep integration, not separate modules. Each week's deliverable enhances the others.

---

## SYSTEM ARCHITECTURE

### Week 2: Audit Automation (Foundation)
**Purpose:** Continuous monitoring and automated compliance checks

**Core Components:**
1. **Audit Monitor** - Real-time event tracking
2. **Compliance Checker** - Automated rule validation
3. **Alert Manager** - Notification system
4. **Audit Trail** - Immutable event log

**Integration Points:**
- Monitors all Week 1 policy evaluations
- Feeds data to Week 3 webhooks
- Provides data for Week 4 dashboard

### Week 3: Integration Layer (Connectivity)
**Purpose:** Connect Omnipath to external systems

**Core Components:**
1. **Webhook Manager** - Outbound event notifications
2. **API Gateway** - Inbound integrations
3. **Event Streaming** - Real-time data flow
4. **Connector Framework** - Third-party tool integration

**Integration Points:**
- Streams Week 2 audit events externally
- Receives external triggers for policy evaluation
- Provides real-time updates to Week 4 dashboard

### Week 4: UI Dashboard (Visibility)
**Purpose:** Visual governance interface

**Core Components:**
1. **React Frontend** - Modern web UI
2. **Real-time Updates** - WebSocket connections
3. **Visual Policy Builder** - Drag-and-drop policy creation
4. **Compliance Dashboard** - Executive reporting

**Integration Points:**
- Displays Week 2 audit data in real-time
- Uses Week 3 webhooks for live updates
- Manages Week 1 policies visually

---

## WEEK 2: AUDIT AUTOMATION

### 2.1 Audit Monitor
**File:** `backend/agents/compliance/audit_monitor.py` (400 lines)

**Responsibilities:**
- Track all governance events (policy evaluations, approvals, risk assessments)
- Monitor asset lifecycle changes
- Detect anomalies and violations
- Generate audit trail entries

**Data Model:**
```python
@dataclass
class AuditEvent:
    event_id: str
    event_type: AuditEventType  # POLICY_EVALUATION, APPROVAL, RISK_ASSESSMENT, etc.
    timestamp: datetime
    actor: str  # User or system that triggered event
    asset_id: Optional[str]
    action: str  # What was attempted
    result: str  # ALLOWED, DENIED, APPROVED, REJECTED
    policy_ids: List[str]  # Policies that were evaluated
    metadata: Dict[str, Any]
    context: Dict[str, Any]
```

**Key Methods:**
- `track_event(event: AuditEvent)` - Record event
- `get_events(filters: Dict)` - Query events
- `detect_anomalies()` - Find unusual patterns
- `get_audit_trail(asset_id: str)` - Complete history

### 2.2 Compliance Checker
**File:** `backend/agents/compliance/compliance_checker.py` (500 lines)

**Responsibilities:**
- Run automated compliance checks
- Validate against regulatory requirements
- Generate compliance reports
- Schedule periodic audits

**Check Types:**
1. **Asset Compliance** - All assets properly registered and tagged
2. **Policy Compliance** - All required policies active
3. **Approval Compliance** - High-risk operations properly approved
4. **Data Compliance** - Sensitive data properly protected
5. **Audit Compliance** - Complete audit trails exist

**Data Model:**
```python
@dataclass
class ComplianceCheck:
    check_id: str
    check_type: ComplianceCheckType
    status: CheckStatus  # PASS, FAIL, WARNING
    timestamp: datetime
    findings: List[ComplianceFinding]
    recommendations: List[str]
    severity: Severity  # CRITICAL, HIGH, MEDIUM, LOW

@dataclass
class ComplianceFinding:
    finding_id: str
    description: str
    affected_assets: List[str]
    regulation: str  # GDPR, HIPAA, SOX, EU_AI_ACT
    article: str  # Specific article/section
    remediation: str
```

**Key Methods:**
- `run_check(check_type: ComplianceCheckType)` - Execute check
- `schedule_check(check_type, interval)` - Schedule recurring
- `get_compliance_score()` - Overall compliance percentage
- `get_violations()` - Active violations

### 2.3 Alert Manager
**File:** `backend/agents/compliance/alert_manager.py` (300 lines)

**Responsibilities:**
- Send notifications for compliance violations
- Escalate critical issues
- Manage alert rules and recipients
- Track alert acknowledgments

**Alert Types:**
1. **Policy Violation** - Policy denied an operation
2. **Compliance Failure** - Automated check failed
3. **Anomaly Detected** - Unusual pattern found
4. **Approval Required** - High-risk operation needs approval
5. **Audit Gap** - Missing audit trail

**Data Model:**
```python
@dataclass
class Alert:
    alert_id: str
    alert_type: AlertType
    severity: Severity
    timestamp: datetime
    title: str
    description: str
    affected_assets: List[str]
    recipients: List[str]
    status: AlertStatus  # PENDING, SENT, ACKNOWLEDGED, RESOLVED
    metadata: Dict[str, Any]
```

**Key Methods:**
- `send_alert(alert: Alert)` - Send notification
- `acknowledge_alert(alert_id: str, user: str)` - Mark acknowledged
- `resolve_alert(alert_id: str, resolution: str)` - Mark resolved
- `get_active_alerts()` - Unresolved alerts

### 2.4 Audit API
**File:** `backend/api/routes/audit.py` (600 lines, 15 endpoints)

**Audit Events (5 endpoints):**
- `GET /api/v1/audit/events` - List events (filter by type, asset, user, time)
- `GET /api/v1/audit/events/{id}` - Get event details
- `GET /api/v1/audit/trail/{asset_id}` - Get asset audit trail
- `GET /api/v1/audit/anomalies` - Get detected anomalies
- `POST /api/v1/audit/export` - Export audit data

**Compliance Checks (5 endpoints):**
- `POST /api/v1/audit/checks/run` - Run compliance check
- `GET /api/v1/audit/checks` - List check results
- `GET /api/v1/audit/checks/{id}` - Get check details
- `GET /api/v1/audit/compliance-score` - Get overall score
- `GET /api/v1/audit/violations` - Get active violations

**Alerts (5 endpoints):**
- `GET /api/v1/audit/alerts` - List alerts
- `GET /api/v1/audit/alerts/{id}` - Get alert details
- `POST /api/v1/audit/alerts/{id}/acknowledge` - Acknowledge alert
- `POST /api/v1/audit/alerts/{id}/resolve` - Resolve alert
- `GET /api/v1/audit/alerts/active` - Get active alerts

---

## WEEK 3: INTEGRATION LAYER

### 3.1 Webhook Manager
**File:** `backend/integrations/webhook_manager.py` (400 lines)

**Responsibilities:**
- Send webhook notifications for governance events
- Manage webhook subscriptions
- Retry failed deliveries
- Track delivery status

**Webhook Events:**
- `policy.evaluated` - Policy evaluation completed
- `approval.requested` - Approval required
- `approval.completed` - Approval granted/denied
- `risk.assessed` - Risk score calculated
- `compliance.violated` - Compliance check failed
- `audit.event` - Audit event created
- `alert.triggered` - Alert sent

**Data Model:**
```python
@dataclass
class WebhookSubscription:
    subscription_id: str
    url: str
    events: List[str]  # Event types to subscribe to
    secret: str  # For signature verification
    active: bool
    created_at: datetime
    metadata: Dict[str, Any]

@dataclass
class WebhookDelivery:
    delivery_id: str
    subscription_id: str
    event_type: str
    payload: Dict[str, Any]
    status: DeliveryStatus  # PENDING, SUCCESS, FAILED, RETRYING
    attempts: int
    last_attempt: datetime
    response_code: Optional[int]
    response_body: Optional[str]
```

**Key Methods:**
- `subscribe(subscription: WebhookSubscription)` - Create subscription
- `unsubscribe(subscription_id: str)` - Remove subscription
- `send_webhook(event_type: str, payload: Dict)` - Send to all subscribers
- `retry_failed()` - Retry failed deliveries

### 3.2 API Gateway
**File:** `backend/integrations/api_gateway.py` (500 lines)

**Responsibilities:**
- Accept inbound API calls from external systems
- Authenticate and authorize external requests
- Rate limiting and throttling
- Request/response transformation

**Supported Operations:**
- Trigger policy evaluation from external system
- Submit approval requests
- Query compliance status
- Retrieve audit data
- Register/update assets programmatically

**Data Model:**
```python
@dataclass
class APIKey:
    key_id: str
    key_hash: str
    name: str
    organization: str
    permissions: List[str]  # Scopes: read:assets, write:policies, etc.
    rate_limit: int  # Requests per minute
    active: bool
    created_at: datetime
    expires_at: Optional[datetime]

@dataclass
class APIRequest:
    request_id: str
    key_id: str
    endpoint: str
    method: str
    timestamp: datetime
    response_code: int
    response_time_ms: int
```

**Key Methods:**
- `create_api_key(name: str, permissions: List[str])` - Generate API key
- `revoke_api_key(key_id: str)` - Revoke key
- `validate_request(request: Request)` - Authenticate and authorize
- `apply_rate_limit(key_id: str)` - Check rate limit

### 3.3 Event Streaming
**File:** `backend/integrations/event_streaming.py` (400 lines)

**Responsibilities:**
- Stream governance events in real-time
- Support multiple streaming protocols (WebSocket, SSE, Kafka)
- Filter events by type, asset, user
- Maintain connection state

**Stream Types:**
1. **Audit Stream** - All audit events
2. **Policy Stream** - Policy evaluations
3. **Approval Stream** - Approval workflow events
4. **Alert Stream** - Real-time alerts
5. **Metrics Stream** - Performance and compliance metrics

**Data Model:**
```python
@dataclass
class StreamSubscription:
    subscription_id: str
    connection_id: str
    stream_type: StreamType
    filters: Dict[str, Any]
    created_at: datetime
    last_activity: datetime

@dataclass
class StreamEvent:
    event_id: str
    stream_type: StreamType
    timestamp: datetime
    data: Dict[str, Any]
```

**Key Methods:**
- `subscribe(stream_type: StreamType, filters: Dict)` - Create subscription
- `unsubscribe(subscription_id: str)` - Remove subscription
- `publish(event: StreamEvent)` - Publish to subscribers
- `get_active_subscriptions()` - List active streams

### 3.4 Integration API
**File:** `backend/api/routes/integrations.py` (700 lines, 20 endpoints)

**Webhooks (6 endpoints):**
- `POST /api/v1/integrations/webhooks` - Create subscription
- `GET /api/v1/integrations/webhooks` - List subscriptions
- `GET /api/v1/integrations/webhooks/{id}` - Get subscription
- `DELETE /api/v1/integrations/webhooks/{id}` - Delete subscription
- `GET /api/v1/integrations/webhooks/{id}/deliveries` - Get delivery history
- `POST /api/v1/integrations/webhooks/{id}/test` - Test webhook

**API Keys (5 endpoints):**
- `POST /api/v1/integrations/api-keys` - Create API key
- `GET /api/v1/integrations/api-keys` - List API keys
- `GET /api/v1/integrations/api-keys/{id}` - Get API key
- `DELETE /api/v1/integrations/api-keys/{id}` - Revoke API key
- `GET /api/v1/integrations/api-keys/{id}/usage` - Get usage stats

**Event Streaming (4 endpoints):**
- `GET /api/v1/integrations/streams` - List available streams
- `POST /api/v1/integrations/streams/subscribe` - Subscribe to stream
- `DELETE /api/v1/integrations/streams/{id}` - Unsubscribe
- `GET /api/v1/integrations/streams/{id}/events` - Get recent events

**External Operations (5 endpoints):**
- `POST /api/v1/integrations/external/evaluate` - Trigger policy evaluation
- `POST /api/v1/integrations/external/approve` - Submit approval
- `GET /api/v1/integrations/external/compliance` - Get compliance status
- `GET /api/v1/integrations/external/audit` - Get audit data
- `POST /api/v1/integrations/external/asset` - Register asset

---

## WEEK 4: UI DASHBOARD

### 4.1 Dashboard Architecture
**Technology:** React + TypeScript + TailwindCSS (using existing Omnipath frontend)

**Structure:**
```
frontend/
├── src/
│   ├── components/
│   │   ├── governance/
│   │   │   ├── PolicyBuilder.tsx        # Visual policy creation
│   │   │   ├── PolicyList.tsx           # Policy management
│   │   │   ├── ApprovalQueue.tsx        # Approval workflow UI
│   │   │   ├── RiskDashboard.tsx        # Risk visualization
│   │   │   ├── ComplianceReport.tsx     # Compliance reporting
│   │   │   ├── AuditTimeline.tsx        # Audit event timeline
│   │   │   └── AlertPanel.tsx           # Real-time alerts
│   │   └── common/
│   │       ├── RiskBadge.tsx            # Risk level indicator
│   │       ├── StatusBadge.tsx          # Status indicator
│   │       └── MetricsCard.tsx          # Metric display
│   ├── pages/
│   │   ├── GovernanceDashboard.tsx      # Main dashboard
│   │   ├── PolicyManagement.tsx         # Policy CRUD
│   │   ├── ApprovalCenter.tsx           # Approval management
│   │   ├── AuditLog.tsx                 # Audit viewer
│   │   └── ComplianceCenter.tsx         # Compliance overview
│   ├── hooks/
│   │   ├── useWebSocket.ts              # Real-time updates
│   │   ├── usePolicies.ts               # Policy data
│   │   ├── useApprovals.ts              # Approval data
│   │   └── useAudit.ts                  # Audit data
│   └── services/
│       └── governanceApi.ts             # API client
```

### 4.2 Key Components

**PolicyBuilder.tsx** (300 lines)
- Drag-and-drop policy creation
- Visual condition builder
- Action configuration
- Template selection
- Real-time validation

**RiskDashboard.tsx** (400 lines)
- Risk heatmap (asset type × risk tier)
- Top 10 highest-risk assets
- Risk trend charts
- Risk distribution pie chart
- Drill-down to asset details

**ComplianceReport.tsx** (350 lines)
- Compliance score gauge
- Regulation breakdown (GDPR, HIPAA, SOX, EU AI Act)
- Violation list with severity
- Remediation recommendations
- Export to PDF

**AuditTimeline.tsx** (300 lines)
- Chronological event timeline
- Filter by type, asset, user
- Event details modal
- Export audit trail
- Anomaly highlighting

**ApprovalQueue.tsx** (350 lines)
- Pending approvals list
- Approval details view
- Approve/reject actions
- Escalation workflow
- Approval history

**AlertPanel.tsx** (250 lines)
- Real-time alert notifications
- Alert severity indicators
- Acknowledge/resolve actions
- Alert filtering
- Alert history

### 4.3 Real-time Updates
**WebSocket Integration:**
- Connect to Week 3 event streaming
- Subscribe to relevant streams (audit, alerts, approvals)
- Update UI in real-time
- Handle reconnection

**Implementation:**
```typescript
// hooks/useWebSocket.ts
export function useWebSocket(streamType: StreamType) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  
  useEffect(() => {
    const ws = new WebSocket(`ws://api/v1/integrations/streams/${streamType}`);
    
    ws.onopen = () => setConnected(true);
    ws.onmessage = (msg) => {
      const event = JSON.parse(msg.data);
      setEvents(prev => [event, ...prev]);
    };
    ws.onclose = () => setConnected(false);
    
    return () => ws.close();
  }, [streamType]);
  
  return { events, connected };
}
```

### 4.4 Dashboard API Integration
**API Client:** `services/governanceApi.ts` (500 lines)

**Endpoints Used:**
- All Week 1 Policy API endpoints
- All Week 2 Audit API endpoints
- All Week 3 Integration API endpoints
- Month 2 Risk, Registry, Tags APIs

**Features:**
- TypeScript types for all requests/responses
- Error handling and retry logic
- Request caching
- Optimistic updates

---

## INTEGRATION POINTS

### Week 1 → Week 2
**Policy Engine → Audit Monitor:**
- Every policy evaluation creates audit event
- Policy violations trigger alerts
- Approval requests logged

### Week 2 → Week 3
**Audit Monitor → Webhook Manager:**
- Audit events trigger webhooks
- Compliance violations sent to external systems
- Alerts streamed in real-time

**Compliance Checker → Event Streaming:**
- Compliance check results published to streams
- Real-time compliance score updates

### Week 3 → Week 4
**Event Streaming → Dashboard:**
- WebSocket connection for real-time updates
- Audit events displayed in timeline
- Alerts shown in notification panel

**API Gateway → Dashboard:**
- Dashboard uses standard REST APIs
- External systems can trigger dashboard updates

### Week 2 → Week 4
**Audit Monitor → Dashboard:**
- Audit timeline component displays events
- Compliance report uses check results
- Alert panel shows active alerts

### Week 1 → Week 4
**Policy Engine → Dashboard:**
- Policy builder creates/edits policies
- Policy list displays all policies
- Policy evaluation results shown

---

## TESTING STRATEGY

### Unit Tests (2,000+ lines, 150+ tests)
- **Week 2:** test_audit_monitor.py, test_compliance_checker.py, test_alert_manager.py
- **Week 3:** test_webhook_manager.py, test_api_gateway.py, test_event_streaming.py
- **Week 4:** Component tests with React Testing Library

### Integration Tests (1,000+ lines, 50+ tests)
- **Cross-week:** test_audit_to_webhook.py, test_webhook_to_dashboard.py
- **End-to-end:** test_policy_evaluation_to_dashboard.py

### API Tests (500+ lines, 30+ tests)
- All 35 new API endpoints
- Authentication and authorization
- Rate limiting
- Error handling

---

## DELIVERABLES

**Code:**
- 3,000+ lines backend (audit, integration, API)
- 2,000+ lines frontend (React components)
- 3,500+ lines tests
- **Total: 8,500+ lines**

**APIs:**
- 15 audit endpoints
- 20 integration endpoints
- **Total: 35 new endpoints**

**UI:**
- 7 major components
- 4 pages
- Real-time updates
- Visual policy builder

**Documentation:**
- This design document
- API documentation
- User guide for dashboard
- Integration guide for external systems

---

## SUCCESS CRITERIA

1. **All tests passing** (200+ tests, 95%+ pass rate)
2. **Real-time updates working** (WebSocket streaming functional)
3. **Visual policy builder functional** (Can create policies via UI)
4. **Audit trail complete** (All events tracked)
5. **Webhooks delivering** (External integrations working)
6. **Dashboard responsive** (Works on desktop and mobile)
7. **Single commit** (All three weeks integrated)

---

## TIMELINE

**Days 1-2:** Week 2 implementation (audit automation)
**Days 3-4:** Week 3 implementation (integration layer)
**Days 5-6:** Week 4 implementation (UI dashboard)
**Day 7:** Integration testing and final commit

---

Built with Pride for Obex Blackvault.
One system. One push. Excellence.
