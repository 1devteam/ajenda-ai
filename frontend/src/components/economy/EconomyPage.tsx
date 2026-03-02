import React from 'react';
import { useQuery } from '@tanstack/react-query';
import Layout from '../layout/Layout';
import { Card, CardTitle, Spinner, EmptyState, StatCard, Table, Tr, Td } from '../layout/UI';
import { economy } from '../../services/api';
import type { Transaction } from '../../types';

function txTypeColor(type: string) {
  if (type === 'earned') return 'var(--success)';
  if (type === 'spent') return 'var(--danger)';
  if (type === 'penalty') return 'var(--warning)';
  return 'var(--text-2)';
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

export default function EconomyPage() {
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['economy-stats'],
    queryFn: () => economy.stats('default'),
    refetchInterval: 30000,
  });

  const { data: txList, isLoading: txLoading } = useQuery({
    queryKey: ['transactions'],
    queryFn: () => economy.transactions({ limit: 50 }),
    refetchInterval: 15000,
  });

  const transactions: Transaction[] = Array.isArray(txList) ? txList : [];

  return (
    <Layout
      title="Economy"
      subtitle="Credit allocation, spending, and agent economic activity"
    >
      {/* Stats */}
      {statsLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spinner size={32} /></div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
          <StatCard
            label="Total Credits Issued"
            value={(stats?.total_credits_issued ?? 0).toLocaleString()}
            deltaDir="up"
            delta="lifetime"
          />
          <StatCard
            label="Total Spent"
            value={(stats?.total_credits_spent ?? 0).toLocaleString()}
            deltaDir="down"
            delta="lifetime"
            progressVariant="warning"
            progress={stats?.total_credits_issued ? (stats.total_credits_spent / stats.total_credits_issued) * 100 : 0}
          />
          <StatCard
            label="Avg Mission Cost"
            value={(stats?.avg_mission_cost ?? 0).toFixed(1)}
            deltaDir="neutral"
            delta="per mission"
          />
          <StatCard
            label="Active Agents"
            value={stats?.active_agents ?? 0}
            deltaDir="up"
            delta="spending"
            progressVariant="success"
          />
        </div>
      )}

      {/* Top spenders */}
      {stats?.top_spenders && stats.top_spenders.length > 0 && (
        <Card style={{ marginBottom: 16 }}>
          <CardTitle>Top Spenders</CardTitle>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {stats.top_spenders.map((s, i) => (
              <div key={s.agent_id} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 20, textAlign: 'right', color: 'var(--text-3)', fontSize: 12 }}>#{i + 1}</div>
                <div style={{ flex: 1, fontSize: 13, fontWeight: 500 }}>{s.agent_name || s.agent_id}</div>
                <div style={{ fontSize: 13, fontFamily: 'JetBrains Mono, monospace', color: 'var(--warning)' }}>
                  {s.credits_spent.toLocaleString()} credits
                </div>
                <div style={{ width: 120, height: 4, background: 'var(--surface-2)', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{
                    height: '100%',
                    width: `${stats.total_credits_spent ? (s.credits_spent / stats.total_credits_spent) * 100 : 0}%`,
                    background: 'var(--warning)', borderRadius: 2,
                  }} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Transactions */}
      <Card style={{ padding: 0 }}>
        <div style={{ padding: '16px 20px 0', borderBottom: '1px solid var(--border)' }}>
          <CardTitle>Transaction History</CardTitle>
        </div>
        {txLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spinner size={32} /></div>
        ) : transactions.length === 0 ? (
          <EmptyState message="No transactions recorded yet." />
        ) : (
          <Table headers={['Agent', 'Type', 'Amount', 'Description', 'Mission', 'Time']}>
            {transactions.map(tx => (
              <Tr key={tx.transaction_id}>
                <Td>{tx.agent_name || tx.agent_id}</Td>
                <Td>
                  <span style={{ color: txTypeColor(tx.type), fontSize: 12, fontWeight: 600 }}>
                    {tx.type.toUpperCase()}
                  </span>
                </Td>
                <Td mono>
                  <span style={{ color: txTypeColor(tx.type) }}>
                    {tx.type === 'spent' || tx.type === 'penalty' ? '-' : '+'}
                    {tx.amount.toLocaleString()}
                  </span>
                </Td>
                <Td>{tx.description}</Td>
                <Td mono>{tx.mission_id ? tx.mission_id.slice(0, 16) + '…' : '—'}</Td>
                <Td>{timeAgo(tx.created_at)}</Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>
    </Layout>
  );
}
