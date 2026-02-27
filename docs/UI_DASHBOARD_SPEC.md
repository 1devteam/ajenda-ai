# UI Dashboard Specification

**Week 4: Governance Dashboard Frontend**

Complete specification for building the Governance Dashboard UI.

---

## Overview

The Governance Dashboard provides real-time visibility into AI governance across the organization. Built with React + TypeScript + TailwindCSS, it connects to the backend APIs and WebSocket streams for live updates.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Governance Dashboard                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Overview   │  │  Compliance  │  │     Risk     │      │
│  │   Dashboard  │  │    Center    │  │  Management  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │    Policy    │  │    Audit     │  │  Approvals   │      │
│  │    Engine    │  │   Explorer   │  │     Queue    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │    Asset     │  │     Alerts   │  │ Integrations │      │
│  │   Registry   │  │     Feed     │  │   Settings   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
    REST APIs           WebSocket            Event Streaming
```

---

## Pages & Components

### 1. Overview Dashboard

**Route:** `/dashboard`

**Purpose:** Executive summary of governance posture

**Components:**

```typescript
// RiskOverviewCard.tsx
interface RiskOverviewProps {
  totalAssets: number;
  averageRiskScore: number;
  criticalAssets: number;
  complianceScore: number;
}

// Displays: Total assets, avg risk, critical count, compliance %
// API: GET /api/v1/dashboard/overview
// Updates: Real-time via WebSocket (metrics stream)
```

```typescript
// RiskHeatmap.tsx
interface RiskHeatmapProps {
  data: Array<{
    assetType: string;
    riskTier: string;
    count: number;
  }>;
}

// Displays: Asset type × Risk tier matrix
// API: GET /api/v1/dashboard/heatmap
// Visualization: D3.js heatmap or Recharts
```

```typescript
// TopRisksTable.tsx
interface TopRisksProps {
  risks: Array<{
    assetId: string;
    name: string;
    riskScore: number;
    riskTier: string;
    lastAssessed: string;
  }>;
}

// Displays: Top 10 highest-risk assets
// API: GET /api/v1/dashboard/top-risks
// Actions: Click to view details, approve, mitigate
```

```typescript
// TrendChart.tsx
interface TrendChartProps {
  metric: 'risk_score' | 'asset_count' | 'compliance_coverage';
  period: '7d' | '30d' | '90d';
  data: Array<{
    date: string;
    value: number;
  }>;
}

// Displays: Time series chart of selected metric
// API: GET /api/v1/dashboard/trends/{metric}?period={period}
// Visualization: Recharts LineChart
```

---

### 2. Compliance Center

**Route:** `/compliance`

**Purpose:** Compliance status and reports

**Components:**

```typescript
// ComplianceScoreGauge.tsx
interface ComplianceScoreProps {
  score: number; // 0-100
  status: 'compliant' | 'warning' | 'non_compliant';
  lastChecked: string;
}

// Displays: Circular gauge with compliance score
// API: GET /api/v1/audit/compliance-score
// Updates: Every 5 minutes
```

```typescript
// ComplianceChecksTable.tsx
interface ComplianceChecksProps {
  checks: Array<{
    checkId: string;
    checkType: string;
    status: 'pass' | 'fail' | 'warning';
    timestamp: string;
    findings: number;
  }>;
}

// Displays: Recent compliance check results
// API: GET /api/v1/audit/checks
// Actions: View findings, run check, export report
```

```typescript
// ViolationsPanel.tsx
interface ViolationsProps {
  violations: Array<{
    findingId: string;
    severity: 'critical' | 'high' | 'medium' | 'low';
    description: string;
    affectedAssets: string[];
    recommendation: string;
  }>;
}

// Displays: Active compliance violations
// API: GET /api/v1/audit/violations
// Actions: Acknowledge, remediate, escalate
```

```typescript
// ReportGenerator.tsx
interface ReportGeneratorProps {
  reportTypes: Array<'executive' | 'audit' | 'regulatory' | 'risk'>;
}

// Displays: Report generation form
// API: POST /api/v1/dashboard/reports/{type}
// Actions: Generate, download, schedule
```

---

### 3. Risk Management

**Route:** `/risk`

**Purpose:** Risk assessment and mitigation

**Components:**

```typescript
// RiskDistributionChart.tsx
interface RiskDistributionProps {
  distribution: {
    minimal: number;
    low: number;
    medium: number;
    high: number;
    critical: number;
  };
}

// Displays: Pie chart of risk tier distribution
// API: GET /api/v1/dashboard/risk-distribution
// Visualization: Recharts PieChart
```

```typescript
// AssetRiskTable.tsx
interface AssetRiskProps {
  assets: Array<{
    assetId: string;
    name: string;
    type: string;
    riskScore: number;
    riskTier: string;
    factors: {
      inherent: number;
      dataSensitivity: number;
      operational: number;
      historical: number;
    };
  }>;
}

// Displays: All assets with risk scores
// API: GET /api/v1/risk/assets/{id}/breakdown
// Actions: Recalculate, view breakdown, mitigate
```

```typescript
// ImpactAssessmentPanel.tsx
interface ImpactAssessmentProps {
  assetId: string;
  impact: {
    business: {
      severity: string;
      description: string;
    };
    technical: {
      severity: string;
      description: string;
    };
    compliance: {
      severity: string;
      description: string;
    };
  };
}

// Displays: Impact assessment for an asset
// API: POST /api/v1/risk/assets/{id}/impact
// Actions: View mitigation strategies
```

---

### 4. Policy Engine

**Route:** `/policies`

**Purpose:** Policy management and evaluation

**Components:**

```typescript
// PolicyList.tsx
interface PolicyListProps {
  policies: Array<{
    policyId: string;
    name: string;
    status: 'draft' | 'active' | 'deprecated';
    priority: number;
    conditions: number;
    actions: number;
    createdAt: string;
  }>;
}

// Displays: All policies
// API: GET /api/v1/policies
// Actions: Create, edit, activate, deactivate, delete
```

```typescript
// PolicyEditor.tsx
interface PolicyEditorProps {
  policy?: Policy; // For editing existing
}

// Displays: Policy creation/editing form
// Fields: Name, description, conditions, actions, priority
// API: POST /api/v1/policies, PUT /api/v1/policies/{id}
// Features: Condition builder, action selector, template import
```

```typescript
// PolicyTemplates.tsx
interface PolicyTemplatesProps {
  templates: Array<{
    templateId: string;
    name: string;
    description: string;
    category: string;
  }>;
}

// Displays: Pre-built policy templates
// API: GET /api/v1/policies/templates
// Actions: Create from template, preview
```

```typescript
// PolicyEvaluationTest.tsx
interface PolicyEvaluationTestProps {
  policyId: string;
}

// Displays: Policy testing interface
// API: POST /api/v1/policies/test
// Features: Context input, evaluation result, matched policies
```

---

### 5. Audit Explorer

**Route:** `/audit`

**Purpose:** Audit event exploration and analysis

**Components:**

```typescript
// AuditEventTimeline.tsx
interface AuditEventTimelineProps {
  events: Array<{
    eventId: string;
    eventType: string;
    timestamp: string;
    actor: string;
    action: string;
    result: 'allowed' | 'denied' | 'error';
    assetId?: string;
  }>;
}

// Displays: Chronological event timeline
// API: GET /api/v1/audit/events
// Features: Filtering, search, export
// Updates: Real-time via WebSocket (audit stream)
```

```typescript
// AnomalyDetector.tsx
interface AnomalyDetectorProps {
  anomalies: Array<{
    anomalyId: string;
    anomalyType: string;
    detectedAt: string;
    description: string;
    severity: string;
    affectedEvents: string[];
  }>;
}

// Displays: Detected anomalies
// API: GET /api/v1/audit/anomalies
// Actions: Investigate, dismiss, create alert
```

```typescript
// AuditTrailViewer.tsx
interface AuditTrailProps {
  assetId: string;
}

// Displays: Complete audit trail for an asset
// API: GET /api/v1/audit/trail/{assetId}
// Features: Event filtering, export, lineage view
```

---

### 6. Approvals Queue

**Route:** `/approvals`

**Purpose:** Approval workflow management

**Components:**

```typescript
// ApprovalQueue.tsx
interface ApprovalQueueProps {
  approvals: Array<{
    approvalId: string;
    assetId: string;
    assetName: string;
    requestedBy: string;
    requestedAt: string;
    riskTier: string;
    requiredAuthority: string;
    status: 'pending' | 'approved' | 'rejected';
  }>;
}

// Displays: Pending approval requests
// API: GET /api/v1/risk/approvals?status=pending
// Actions: Approve, reject, escalate, view details
// Updates: Real-time via WebSocket (approval stream)
```

```typescript
// ApprovalDetails.tsx
interface ApprovalDetailsProps {
  approvalId: string;
}

// Displays: Detailed approval request information
// API: GET /api/v1/risk/approvals/{id}
// Features: Risk breakdown, impact assessment, history
// Actions: Approve with comment, reject with reason
```

```typescript
// ApprovalHistory.tsx
interface ApprovalHistoryProps {
  assetId: string;
}

// Displays: Approval history for an asset
// API: GET /api/v1/risk/approvals/asset/{id}/history
// Features: Timeline view, decision rationale
```

---

### 7. Asset Registry

**Route:** `/assets`

**Purpose:** Asset inventory and management

**Components:**

```typescript
// AssetInventory.tsx
interface AssetInventoryProps {
  assets: Array<{
    assetId: string;
    name: string;
    type: 'agent' | 'tool' | 'model' | 'vector_db';
    status: 'active' | 'deprecated' | 'archived';
    owner: string;
    tags: string[];
    riskScore?: number;
  }>;
}

// Displays: All registered assets
// API: GET /api/v1/registry/assets
// Features: Filtering, search, bulk operations
```

```typescript
// AssetDetails.tsx
interface AssetDetailsProps {
  assetId: string;
}

// Displays: Complete asset information
// API: GET /api/v1/registry/assets/{id}
// Tabs: Overview, Dependencies, Lineage, Tags, Risk, Audit
```

```typescript
// DependencyGraph.tsx
interface DependencyGraphProps {
  assetId: string;
}

// Displays: Asset dependency visualization
// API: GET /api/v1/registry/assets/{id}/dependencies?recursive=true
// Visualization: D3.js force-directed graph
```

```typescript
// LineageViewer.tsx
interface LineageViewerProps {
  assetId: string;
}

// Displays: Model lineage chain
// API: GET /api/v1/registry/assets/{id}/lineage/chain
// Visualization: Hierarchical tree or Sankey diagram
```

---

### 8. Alerts Feed

**Route:** `/alerts`

**Purpose:** Alert management and notifications

**Components:**

```typescript
// AlertsFeed.tsx
interface AlertsFeedProps {
  alerts: Array<{
    alertId: string;
    alertType: string;
    severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
    timestamp: string;
    title: string;
    description: string;
    status: 'pending' | 'sent' | 'acknowledged' | 'resolved';
  }>;
}

// Displays: Real-time alert feed
// API: GET /api/v1/audit/alerts
// Updates: Real-time via WebSocket (alert stream)
// Actions: Acknowledge, resolve, escalate
```

```typescript
// AlertNotifications.tsx
// Displays: Toast notifications for new alerts
// Updates: WebSocket push notifications
// Features: Click to view, dismiss, snooze
```

---

### 9. Integrations Settings

**Route:** `/integrations`

**Purpose:** External integration management

**Components:**

```typescript
// WebhookManager.tsx
interface WebhookManagerProps {
  subscriptions: Array<{
    subscriptionId: string;
    url: string;
    events: string[];
    active: boolean;
    createdAt: string;
  }>;
}

// Displays: Webhook subscriptions
// API: GET /api/v1/integrations/webhooks
// Actions: Create, edit, delete, test
```

```typescript
// APIKeyManager.tsx
interface APIKeyManagerProps {
  keys: Array<{
    keyId: string;
    name: string;
    organization: string;
    permissions: string[];
    rateLimit: number;
    active: boolean;
  }>;
}

// Displays: API keys
// API: GET /api/v1/integrations/api-keys
// Actions: Create, revoke, view usage
```

---

## Real-Time Features

### WebSocket Connection

```typescript
// hooks/useWebSocket.ts
export function useWebSocket(streamType: StreamType) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  
  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/api/v1/integrations/stream');
    
    ws.onopen = () => {
      setConnected(true);
      // Subscribe to stream
      ws.send(JSON.stringify({
        action: 'subscribe',
        stream_type: streamType,
      }));
    };
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'event') {
        setEvents(prev => [data, ...prev].slice(0, 100));
      }
    };
    
    ws.onclose = () => setConnected(false);
    
    // Keep-alive ping every 30s
    const interval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'ping' }));
      }
    }, 30000);
    
    return () => {
      clearInterval(interval);
      ws.close();
    };
  }, [streamType]);
  
  return { events, connected };
}
```

### Auto-Refresh Hook

```typescript
// hooks/useAutoRefresh.ts
export function useAutoRefresh<T>(
  fetcher: () => Promise<T>,
  interval: number = 30000, // 30s default
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  
  useEffect(() => {
    const fetch = async () => {
      setLoading(true);
      try {
        const result = await fetcher();
        setData(result);
      } finally {
        setLoading(false);
      }
    };
    
    fetch(); // Initial fetch
    const timer = setInterval(fetch, interval);
    
    return () => clearInterval(timer);
  }, [fetcher, interval]);
  
  return { data, loading };
}
```

---

## Technology Stack

**Frontend:**
- React 18
- TypeScript
- TailwindCSS
- Recharts (charts)
- D3.js (advanced visualizations)
- React Query (data fetching)
- Zustand (state management)
- React Router (routing)

**Build:**
- Vite
- ESLint + Prettier

**Testing:**
- Vitest
- React Testing Library

---

## Implementation Guide

### Step 1: Initialize Project

```bash
cd /home/ubuntu/omnipath_v2_clone
mkdir -p frontend
cd frontend
npm create vite@latest . -- --template react-ts
npm install
npm install tailwindcss recharts d3 @tanstack/react-query zustand react-router-dom
```

### Step 2: Configure TailwindCSS

```bash
npx tailwindcss init -p
```

### Step 3: Create Directory Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── dashboard/
│   │   ├── compliance/
│   │   ├── risk/
│   │   ├── policies/
│   │   ├── audit/
│   │   ├── approvals/
│   │   ├── assets/
│   │   ├── alerts/
│   │   └── integrations/
│   ├── hooks/
│   ├── services/
│   ├── types/
│   ├── utils/
│   └── App.tsx
```

### Step 4: Implement API Client

```typescript
// services/api.ts
const API_BASE = 'http://localhost:8000';

export const api = {
  // Dashboard
  getDashboardOverview: () => fetch(`${API_BASE}/api/v1/dashboard/overview`).then(r => r.json()),
  getRiskHeatmap: () => fetch(`${API_BASE}/api/v1/dashboard/heatmap`).then(r => r.json()),
  
  // Compliance
  getComplianceScore: () => fetch(`${API_BASE}/api/v1/audit/compliance-score`).then(r => r.json()),
  getComplianceChecks: () => fetch(`${API_BASE}/api/v1/audit/checks`).then(r => r.json()),
  
  // Risk
  getRiskDistribution: () => fetch(`${API_BASE}/api/v1/dashboard/risk-distribution`).then(r => r.json()),
  
  // ... etc
};
```

### Step 5: Build Components

Follow component specifications above. Each component should:
1. Fetch data from API
2. Handle loading/error states
3. Update in real-time where applicable
4. Be fully typed with TypeScript

### Step 6: Deploy

```bash
npm run build
# Serve via FastAPI static files or separate web server
```

---

## API Endpoints Used

All endpoints documented in:
- `/api/v1/dashboard/*` - Dashboard data
- `/api/v1/audit/*` - Audit events, checks, alerts
- `/api/v1/risk/*` - Risk scores, approvals
- `/api/v1/policies/*` - Policy management
- `/api/v1/registry/*` - Asset registry
- `/api/v1/integrations/*` - Webhooks, API keys, streaming

---

## Next Steps

1. **Month 4:** Full React implementation
2. **Month 5:** Advanced visualizations, custom dashboards
3. **Month 6:** Mobile app, embedded widgets

---

**Built with Pride for Obex Blackvault**
