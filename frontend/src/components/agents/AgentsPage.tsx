import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import Layout from '../layout/Layout';
import { Card, Badge, Btn, Table, Tr, Td, Spinner, EmptyState, StatCard } from '../layout/UI';
import { agents } from '../../services/api';
import type { Agent } from '../../types';

function statusVariant(status: string) {
  if (status === 'active' || status === 'busy') return 'active';
  if (status === 'idle') return 'pending';
  if (status === 'error') return 'error';
  return 'inactive';
}

function agentTypeColor(type: string) {
  const colors: Record<string, string> = {
    researcher: 'var(--accent)',
    analyst: 'var(--success)',
    developer: 'var(--warning)',
    commander: 'var(--danger)',
  };
  return colors[type] || 'var(--text-2)';
}

export default function AgentsPage() {
  const navigate = useNavigate();

  const { data: agentList, isLoading } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agents.list({ limit: 100 }),
    refetchInterval: 15000,
  });

  const list: Agent[] = Array.isArray(agentList) ? agentList : [];

  const activeCount = list.filter(a => a.status === 'active' || a.status === 'busy').length;
  const idleCount = list.filter(a => a.status === 'idle').length;
  const errorCount = list.filter(a => a.status === 'error').length;

  return (
    <Layout
      title="Agents"
      subtitle="All registered agents and their current status"
      actions={
        <Btn variant="primary" onClick={() => navigate('/agents/new')}>
          <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
            <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New Agent
        </Btn>
      }
    >
      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        <StatCard label="Total Agents" value={list.length} />
        <StatCard label="Active / Busy" value={activeCount} deltaDir="up" delta="online" progressVariant="success" progress={list.length ? (activeCount / list.length) * 100 : 0} />
        <StatCard label="Idle" value={idleCount} deltaDir="neutral" delta="available" progressVariant="accent" progress={list.length ? (idleCount / list.length) * 100 : 0} />
        <StatCard label="Errors" value={errorCount} deltaDir={errorCount > 0 ? 'down' : 'neutral'} delta={errorCount > 0 ? 'needs attention' : 'all clear'} progressVariant="danger" progress={list.length ? (errorCount / list.length) * 100 : 0} />
      </div>

      <Card style={{ padding: 0 }}>
        {isLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spinner size={32} /></div>
        ) : list.length === 0 ? (
          <EmptyState
            message="No agents registered. Create your first agent to get started."
            icon={
              <svg width="40" height="40" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                <circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
              </svg>
            }
          />
        ) : (
          <Table headers={['Agent', 'Type', 'Model', 'Status', 'Missions', 'Success Rate', 'Credits', 'Actions']}>
            {list.map((agent) => (
              <Tr key={agent.agent_id} onClick={() => navigate(`/agents/${agent.agent_id}`)}>
                <Td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: '50%', flexShrink: 0,
                      background: `${agentTypeColor(agent.agent_type)}22`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 12, fontWeight: 700, color: agentTypeColor(agent.agent_type),
                    }}>
                      {agent.name.slice(0, 1).toUpperCase()}
                    </div>
                    <div>
                      <div style={{ fontWeight: 500 }}>{agent.name}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'JetBrains Mono, monospace' }}>
                        {agent.agent_id.slice(0, 16)}…
                      </div>
                    </div>
                  </div>
                </Td>
                <Td>
                  <span style={{
                    padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                    background: `${agentTypeColor(agent.agent_type)}22`,
                    color: agentTypeColor(agent.agent_type),
                  }}>
                    {agent.agent_type}
                  </span>
                </Td>
                <Td mono>{agent.model}</Td>
                <Td><Badge variant={statusVariant(agent.status)}>{agent.status}</Badge></Td>
                <Td mono>{agent.total_missions ?? 0}</Td>
                <Td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ width: 60, height: 4, background: 'var(--surface-2)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{
                        height: '100%', width: `${(agent.success_rate ?? 0) * 100}%`,
                        background: (agent.success_rate ?? 0) > 0.8 ? 'var(--success)' : 'var(--warning)',
                        borderRadius: 2,
                      }} />
                    </div>
                    <span style={{ fontSize: 12, color: 'var(--text-2)' }}>
                      {Math.round((agent.success_rate ?? 0) * 100)}%
                    </span>
                  </div>
                </Td>
                <Td mono>{(agent.credit_balance ?? 0).toLocaleString()}</Td>
                <Td>
                  <Btn variant="secondary" size="sm" onClick={(e) => { e?.stopPropagation(); navigate(`/agents/${agent.agent_id}`); }}>
                    View
                  </Btn>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>
    </Layout>
  );
}
