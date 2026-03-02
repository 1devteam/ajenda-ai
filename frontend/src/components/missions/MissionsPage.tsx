import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import Layout from '../layout/Layout';
import { Card, CardTitle, Badge, Btn, Table, Tr, Td, Spinner, EmptyState, Textarea, Input } from '../layout/UI';
import { missions } from '../../services/api';
import type { Mission } from '../../types';

function statusVariant(status: string) {
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

function NewMissionModal({ onClose }: { onClose: () => void }) {
  const [goal, setGoal] = useState('');
  const [budget, setBudget] = useState('');
  const [error, setError] = useState('');
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const { mutate, isPending } = useMutation({
    mutationFn: () => missions.create({
      goal,
      tenant_id: 'default',
      budget_limit: budget ? parseInt(budget) : undefined,
    }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['missions'] });
      queryClient.invalidateQueries({ queryKey: ['missions-recent'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      onClose();
      navigate(`/missions/${data.mission_id}`);
    },
    onError: (err: Error) => setError(err.message),
  });

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }} onClick={onClose}>
      <div
        style={{
          background: 'var(--surface)', border: '1px solid var(--border-2)',
          borderRadius: 'var(--radius-lg)', padding: 28, width: 520, maxWidth: '90vw',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 20 }}>Launch New Mission</div>

        <Textarea
          label="Mission Goal"
          value={goal}
          onChange={setGoal}
          placeholder="Describe the mission objective in detail. The more specific, the better the result."
          rows={5}
        />

        <Input
          label="Budget Limit (credits, optional)"
          value={budget}
          onChange={setBudget}
          placeholder="e.g. 500"
          type="number"
        />

        {error && (
          <div style={{ color: 'var(--danger)', fontSize: 12, marginBottom: 12 }}>{error}</div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
          <Btn variant="secondary" onClick={onClose}>Cancel</Btn>
          <Btn
            variant="primary"
            onClick={() => { if (goal.trim()) mutate(); else setError('Mission goal is required.'); }}
            disabled={isPending}
          >
            {isPending ? 'Launching…' : 'Launch Mission'}
          </Btn>
        </div>
      </div>
    </div>
  );
}

export default function MissionsPage() {
  const [showNew, setShowNew] = useState(false);
  const [filter, setFilter] = useState('all');
  const navigate = useNavigate();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['missions', filter],
    queryFn: () => missions.list({ limit: 50, ...(filter !== 'all' ? { status: filter } : {}) }),
    refetchInterval: 10000,
  });

  const missionList: Mission[] = Array.isArray(data) ? data : (data as { items?: Mission[] })?.items || [];

  const filters = ['all', 'executing', 'planning', 'completed', 'failed', 'pending'];

  return (
    <Layout
      title="Missions"
      subtitle="All agent missions — active, completed, and queued"
      actions={
        <Btn variant="primary" onClick={() => setShowNew(true)}>
          <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
            <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New Mission
        </Btn>
      }
    >
      {showNew && <NewMissionModal onClose={() => setShowNew(false)} />}

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 20 }}>
        {filters.map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: '5px 12px', borderRadius: 6, fontSize: 12, fontWeight: 500,
              cursor: 'pointer', border: '1px solid transparent', fontFamily: 'inherit',
              color: filter === f ? 'var(--accent)' : 'var(--text-2)',
              background: filter === f ? 'var(--accent-dim)' : 'transparent',
              borderColor: filter === f ? 'rgba(108,99,255,0.3)' : 'transparent',
              transition: 'all 0.15s',
            }}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
        <Btn variant="ghost" size="sm" onClick={() => refetch()} style={{ marginLeft: 'auto' }}>
          ↻ Refresh
        </Btn>
      </div>

      <Card style={{ padding: 0 }}>
        {isLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spinner size={32} /></div>
        ) : missionList.length === 0 ? (
          <EmptyState
            message="No missions found. Launch your first mission to get started."
            icon={
              <svg width="40" height="40" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
            }
          />
        ) : (
          <Table headers={['Mission', 'Agent', 'Status', 'Progress', 'Credits', 'Duration', 'Created', '']}>
            {missionList.map((m) => {
              const progress = m.progress_percentage ?? (m.status === 'completed' ? 100 : m.status === 'failed' ? 0 : 50);
              const progressColor = m.status === 'completed' ? 'success' : m.status === 'failed' ? 'danger' : 'accent';
              const duration = m.started_at && m.completed_at
                ? `${Math.round((new Date(m.completed_at).getTime() - new Date(m.started_at).getTime()) / 1000)}s`
                : m.started_at ? 'Running…' : '—';

              return (
                <Tr key={m.mission_id} onClick={() => navigate(`/missions/${m.mission_id}`)}>
                  <Td>
                    <div style={{ fontWeight: 500, maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {m.goal.slice(0, 60)}{m.goal.length > 60 ? '…' : ''}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'JetBrains Mono, monospace', marginTop: 2 }}>
                      {m.mission_id.slice(0, 20)}…
                    </div>
                  </Td>
                  <Td>{m.agent_name || m.agent_id || '—'}</Td>
                  <Td><Badge variant={statusVariant(m.status)}>{m.status}</Badge></Td>
                  <Td>
                    <div style={{ width: 100 }}>
                      <div style={{ height: 4, background: 'var(--surface-2)', borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{
                          height: '100%', width: `${progress}%`,
                          background: progressColor === 'success' ? 'var(--success)' : progressColor === 'danger' ? 'var(--danger)' : 'var(--accent)',
                          borderRadius: 2, transition: 'width 0.5s',
                        }} />
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 3 }}>{progress}%</div>
                    </div>
                  </Td>
                  <Td mono>{m.credits_used ?? 0}</Td>
                  <Td>{duration}</Td>
                  <Td>{m.created_at ? timeAgo(m.created_at) : '—'}</Td>
                  <Td>
                    <Btn variant="secondary" size="sm" onClick={(e) => { e?.stopPropagation(); navigate(`/missions/${m.mission_id}`); }}>
                      {m.status === 'completed' ? 'Results' : 'View'}
                    </Btn>
                  </Td>
                </Tr>
              );
            })}
          </Table>
        )}
      </Card>
    </Layout>
  );
}
