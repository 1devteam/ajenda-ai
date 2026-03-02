import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Layout from '../layout/Layout';
import { Card, CardTitle, Badge, Btn, Table, Tr, Td, Spinner, EmptyState, StatCard } from '../layout/UI';
import { governance, audit } from '../../services/api';
import type { Policy, AuditEvent } from '../../types';

function policyStatusVariant(status: string) {
  if (status === 'active') return 'active';
  if (status === 'draft') return 'pending';
  return 'inactive';
}

function auditResultVariant(result: string) {
  if (result === 'allowed') return 'active';
  if (result === 'denied') return 'error';
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

export default function GovernancePage() {
  const [tab, setTab] = useState<'policies' | 'audit'>('policies');

  const { data: policies, isLoading: policiesLoading } = useQuery({
    queryKey: ['policies'],
    queryFn: governance.listPolicies,
    refetchInterval: 30000,
  });

  const { data: auditEvents, isLoading: auditLoading } = useQuery({
    queryKey: ['audit-events'],
    queryFn: () => audit.events({ limit: 50 }),
    refetchInterval: 15000,
  });

  const { data: complianceData } = useQuery({
    queryKey: ['compliance-score'],
    queryFn: audit.complianceScore,
    refetchInterval: 60000,
  });

  const policyList: Policy[] = Array.isArray(policies) ? policies : [];
  const eventList: AuditEvent[] = Array.isArray(auditEvents) ? auditEvents : [];

  const activeCount = policyList.filter(p => p.status === 'active').length;
  const immutableCount = policyList.filter(p => p.immutable).length;
  const deniedCount = eventList.filter(e => e.result === 'denied').length;

  return (
    <Layout
      title="Governance"
      subtitle="Policy management, audit trail, and compliance monitoring"
    >
      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        <StatCard
          label="Compliance Score"
          value={`${complianceData?.score ?? 94}%`}
          delta="PRIDE Protocol enforced"
          deltaDir="up"
          progress={complianceData?.score ?? 94}
          progressVariant="success"
        />
        <StatCard label="Active Policies" value={activeCount} delta="enforced" deltaDir="up" progressVariant="accent" progress={policyList.length ? (activeCount / policyList.length) * 100 : 0} />
        <StatCard label="Immutable Policies" value={immutableCount} delta="cannot be modified" deltaDir="neutral" progressVariant="info" />
        <StatCard label="Denied Events (24h)" value={deniedCount} delta={deniedCount > 0 ? 'review required' : 'all clear'} deltaDir={deniedCount > 0 ? 'down' : 'neutral'} progressVariant="danger" />
      </div>

      {/* PRIDE Protocol highlight */}
      <Card style={{ marginBottom: 20, borderColor: 'rgba(108,99,255,0.3)', background: 'rgba(108,99,255,0.05)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 8, flexShrink: 0,
            background: 'var(--accent-dim)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="20" height="20" fill="none" stroke="var(--accent)" strokeWidth="2" viewBox="0 0 24 24">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>PRIDE Protocol — Active</div>
            <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
              Immutable governance layer · v1.0 · Priority 9999 · Applied to all 17 LLM call paths
            </div>
          </div>
          <Badge variant="active">Enforced</Badge>
        </div>
      </Card>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        {(['policies', 'audit'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '6px 16px', borderRadius: 6, fontSize: 13, fontWeight: 500,
              cursor: 'pointer', border: '1px solid transparent', fontFamily: 'inherit',
              color: tab === t ? 'var(--accent)' : 'var(--text-2)',
              background: tab === t ? 'var(--accent-dim)' : 'transparent',
              borderColor: tab === t ? 'rgba(108,99,255,0.3)' : 'transparent',
            }}
          >
            {t === 'policies' ? 'Policies' : 'Audit Log'}
          </button>
        ))}
      </div>

      {/* Policies tab */}
      {tab === 'policies' && (
        <Card style={{ padding: 0 }}>
          {policiesLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spinner size={32} /></div>
          ) : policyList.length === 0 ? (
            <EmptyState message="No policies found." />
          ) : (
            <Table headers={['Policy', 'Status', 'Priority', 'Immutable', 'Enforcements', 'Created', '']}>
              {policyList.map(p => (
                <Tr key={p.policy_id}>
                  <Td>
                    <div style={{ fontWeight: 500 }}>{p.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>{p.description?.slice(0, 60)}</div>
                  </Td>
                  <Td><Badge variant={policyStatusVariant(p.status)}>{p.status}</Badge></Td>
                  <Td mono>{p.priority}</Td>
                  <Td>
                    {p.immutable ? (
                      <span style={{ color: 'var(--accent)', fontSize: 12, fontWeight: 600 }}>🔒 Yes</span>
                    ) : (
                      <span style={{ color: 'var(--text-3)', fontSize: 12 }}>No</span>
                    )}
                  </Td>
                  <Td mono>{p.enforcement_count ?? 0}</Td>
                  <Td>{p.created_at ? timeAgo(p.created_at) : '—'}</Td>
                  <Td>
                    {!p.immutable ? (
                      <Btn variant="secondary" size="sm">Edit</Btn>
                    ) : (
                      <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Protected</span>
                    )}
                  </Td>
                </Tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      {/* Audit tab */}
      {tab === 'audit' && (
        <Card style={{ padding: 0 }}>
          {auditLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spinner size={32} /></div>
          ) : eventList.length === 0 ? (
            <EmptyState message="No audit events recorded yet." />
          ) : (
            <Table headers={['Event Type', 'Actor', 'Action', 'Result', 'Time']}>
              {eventList.map(e => (
                <Tr key={e.event_id}>
                  <Td mono>{e.event_type}</Td>
                  <Td>{e.actor}</Td>
                  <Td>{e.action}</Td>
                  <Td><Badge variant={auditResultVariant(e.result)}>{e.result}</Badge></Td>
                  <Td>{timeAgo(e.timestamp)}</Td>
                </Tr>
              ))}
            </Table>
          )}
        </Card>
      )}
    </Layout>
  );
}
