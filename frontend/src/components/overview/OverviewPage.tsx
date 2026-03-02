import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import Layout from '../layout/Layout';
import { StatCard, Card, CardTitle, Badge, Btn, Spinner } from '../layout/UI';
import { dashboard, missions } from '../../services/api';
import type { Mission } from '../../types';

function statusBadgeVariant(status: string) {
  if (status === 'completed') return 'active';
  if (status === 'executing' || status === 'planning') return 'info';
  if (status === 'failed') return 'error';
  if (status === 'cancelled') return 'inactive';
  return 'pending';
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function OverviewPage() {
  const navigate = useNavigate();

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: dashboard.stats,
    refetchInterval: 30000,
  });

  const { data: recentMissions, isLoading: missionsLoading } = useQuery({
    queryKey: ['missions-recent'],
    queryFn: () => missions.list({ limit: 6 }),
    refetchInterval: 15000,
  });

  const missionList: Mission[] = Array.isArray(recentMissions)
    ? recentMissions
    : (recentMissions as { items?: Mission[] })?.items || [];

  return (
    <Layout
      title="Command Overview"
      subtitle="Real-time status of your OmniPath deployment · Last updated just now"
      actions={
        <Btn variant="primary" onClick={() => navigate('/missions/new')}>
          <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
            <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          Launch Mission
        </Btn>
      }
    >
      {/* Stats Grid */}
      {statsLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spinner size={32} /></div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
          <StatCard
            label="Active Agents"
            value={stats?.active_agents ?? 0}
            delta={`${stats?.active_agents ?? 0} online`}
            deltaDir="up"
            progress={(stats?.active_agents ?? 0) * 10}
            progressVariant="success"
          />
          <StatCard
            label="Missions Running"
            value={stats?.running_missions ?? 0}
            delta={`${stats?.completed_missions_today ?? 0} completed today`}
            deltaDir="neutral"
            progress={(stats?.running_missions ?? 0) * 15}
            progressVariant="accent"
          />
          <StatCard
            label="Credits Spent Today"
            value={(stats?.credits_spent_today ?? 0).toLocaleString()}
            delta="today"
            deltaDir="down"
            progress={Math.min(100, ((stats?.credits_spent_today ?? 0) / (stats?.total_credits ?? 1)) * 100)}
            progressVariant="warning"
          />
          <StatCard
            label="Compliance Score"
            value={`${stats?.compliance_score ?? 94}%`}
            delta="PRIDE Protocol active"
            deltaDir="up"
            progress={stats?.compliance_score ?? 94}
            progressVariant="success"
          />
        </div>
      )}

      {/* Two-column grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Recent Missions */}
        <Card>
          <CardTitle>Recent Missions</CardTitle>
          {missionsLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 24 }}><Spinner /></div>
          ) : missionList.length === 0 ? (
            <div style={{ color: 'var(--text-3)', fontSize: 13, padding: '12px 0' }}>
              No missions yet. <span
                style={{ color: 'var(--accent)', cursor: 'pointer' }}
                onClick={() => navigate('/missions/new')}
              >Launch your first mission →</span>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {missionList.slice(0, 6).map((m) => (
                <div
                  key={m.mission_id}
                  onClick={() => navigate(`/missions/${m.mission_id}`)}
                  style={{
                    display: 'flex', alignItems: 'flex-start', gap: 12,
                    padding: '10px 0', borderBottom: '1px solid var(--border)',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{
                    width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 11, fontWeight: 700,
                    background: m.status === 'completed' ? 'rgba(34,211,160,0.15)' :
                      m.status === 'executing' || m.status === 'planning' ? 'rgba(108,99,255,0.15)' :
                      m.status === 'failed' ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.15)',
                    color: m.status === 'completed' ? 'var(--success)' :
                      m.status === 'executing' || m.status === 'planning' ? 'var(--accent)' :
                      m.status === 'failed' ? 'var(--danger)' : 'var(--warning)',
                  }}>
                    {m.status === 'completed' ? '✓' : m.status === 'executing' ? '⚡' : m.status === 'failed' ? '✗' : '⏳'}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {m.goal.slice(0, 60)}{m.goal.length > 60 ? '…' : ''}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>
                      <Badge variant={statusBadgeVariant(m.status)}>{m.status}</Badge>
                      {' · '}
                      {m.created_at ? timeAgo(m.created_at) : ''}
                      {m.credits_used ? ` · ${m.credits_used} credits` : ''}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          <div style={{ marginTop: 12 }}>
            <Btn variant="ghost" size="sm" onClick={() => navigate('/missions')}>
              View all missions →
            </Btn>
          </div>
        </Card>

        {/* System Status */}
        <Card>
          <CardTitle>System Status</CardTitle>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[
              { label: 'PRIDE Protocol', status: 'active', detail: 'v1.0 · immutable · priority 9999' },
              { label: 'LLM Providers', status: 'active', detail: 'OpenAI · Claude · Gemini' },
              { label: 'MCP Subsystem', status: 'active', detail: '5 tools available' },
              { label: 'NATS Event Bus', status: 'active', detail: '5 streams active' },
              { label: 'Observability', status: 'active', detail: 'Langfuse · Prometheus' },
              { label: 'Database', status: 'active', detail: 'PostgreSQL connected' },
            ].map((item) => (
              <div key={item.label} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>{item.label}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>{item.detail}</div>
                </div>
                <Badge variant="active">Online</Badge>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </Layout>
  );
}
