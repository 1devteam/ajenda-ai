// ============================================================
// OMNIPATH v2 — TYPE DEFINITIONS
// ============================================================

export type AgentType = 'researcher' | 'analyst' | 'developer' | 'commander';
export type AgentStatus = 'active' | 'idle' | 'busy' | 'error' | 'offline';
export type MissionStatus = 'pending' | 'planning' | 'executing' | 'completed' | 'failed' | 'cancelled';
export type MissionComplexity = 'simple' | 'moderate' | 'complex';
export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

// ---- Agent ----
export interface Agent {
  agent_id: string;
  name: string;
  agent_type: AgentType;
  status: AgentStatus;
  model: string;
  capabilities: string[];
  credit_balance: number;
  total_missions: number;
  success_rate: number;
  tenant_id: string;
  created_at: string;
  last_active?: string;
  emotional_state?: {
    confidence: number;
    stress: number;
    motivation: number;
  };
}

// ---- Mission ----
export interface Mission {
  mission_id: string;
  goal: string;
  status: MissionStatus;
  complexity?: MissionComplexity;
  agent_id?: string;
  agent_name?: string;
  tenant_id: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  credits_used: number;
  budget_limit?: number;
  progress_percentage?: number;
  result?: MissionResult;
  steps?: MissionStep[];
}

export interface MissionResult {
  summary: string;
  output?: string;
  artifacts?: string[];
  quality_score?: number;
  success: boolean;
}

export interface MissionStep {
  step_id: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at?: string;
  completed_at?: string;
  tool_used?: string;
  credits_used?: number;
  output?: string;
}

// ---- Economy ----
export interface EconomyStats {
  total_credits_issued: number;
  total_credits_spent: number;
  total_credits_earned: number;
  active_agents: number;
  avg_mission_cost: number;
  top_spenders: Array<{ agent_id: string; agent_name: string; credits_spent: number }>;
}

export interface Transaction {
  transaction_id: string;
  agent_id: string;
  agent_name?: string;
  type: 'earned' | 'spent' | 'allocated' | 'penalty';
  amount: number;
  description: string;
  mission_id?: string;
  created_at: string;
}

// ---- Governance / Policy ----
export interface Policy {
  policy_id: string;
  name: string;
  description: string;
  status: 'active' | 'draft' | 'deprecated';
  priority: number;
  immutable: boolean;
  enforcement_count: number;
  created_at: string;
  updated_at?: string;
}

export interface AuditEvent {
  event_id: string;
  event_type: string;
  actor: string;
  action: string;
  result: 'allowed' | 'denied' | 'error';
  timestamp: string;
  details?: Record<string, unknown>;
  agent_id?: string;
  mission_id?: string;
}

// ---- Dashboard ----
export interface DashboardStats {
  active_agents: number;
  running_missions: number;
  completed_missions_today: number;
  total_credits: number;
  credits_spent_today: number;
  compliance_score: number;
  system_health: 'healthy' | 'degraded' | 'down';
}

// ---- Revenue Pipeline ----
export type LeadStatus = 'new' | 'contacted' | 'qualified' | 'disqualified' | 'converted';
export type OpportunityStatus = 'open' | 'proposal_sent' | 'negotiating' | 'closed_won' | 'closed_lost';
export type DealStatus = 'active' | 'won' | 'lost' | 'on_hold';

export interface Lead {
  id: string;
  company_name: string;
  industry?: string;
  company_size?: string;
  contact_name?: string;
  contact_email?: string;
  contact_linkedin?: string;
  website?: string;
  status: LeadStatus;
  qualification_score?: number;
  qualification_notes?: string;
  estimated_value?: number;
  notes?: string;
  created_at: string;
  updated_at?: string;
}

export interface Opportunity {
  id: string;
  lead_id: string;
  title: string;
  stage: string;
  status: OpportunityStatus;
  value: number;
  probability: number;
  expected_close_date?: string;
  notes?: string;
  created_at: string;
  updated_at?: string;
}

export interface Proposal {
  id: string;
  opportunity_id: string;
  lead_id?: string;
  title: string;
  content: string;
  status: 'draft' | 'sent' | 'accepted' | 'rejected';
  value: number;
  sent_at?: string;
  created_at: string;
}

export interface Deal {
  id: string;
  opportunity_id: string;
  lead_id?: string;
  title: string;
  value: number;
  status: DealStatus;
  closed_at?: string;
  created_at: string;
}

export interface RevenueDashboard {
  total_leads: number;
  qualified_leads: number;
  open_opportunities: number;
  total_pipeline_value: number;
  proposals_sent: number;
  deals_closed: number;
  total_revenue: number;
  conversion_rate: number;
  avg_deal_value: number;
}

// ---- API Response wrappers ----
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApiError {
  detail: string;
  status_code?: number;
}
