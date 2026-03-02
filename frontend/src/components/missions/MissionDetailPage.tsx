import React, { useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Layout from '../layout/Layout';
import { Card, CardTitle, Badge, Btn, Spinner } from '../layout/UI';
import { missions } from '../../services/api';
import type { Mission } from '../../types';

function statusVariant(status: string) {
  if (status === 'completed') return 'active';
  if (status === 'executing' || status === 'planning') return 'info';
  if (status === 'failed') return 'error';
  if (status === 'cancelled') return 'inactive';
  return 'pending';
}

function formatDuration(start?: string, end?: string) {
  if (!start) return '—';
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const diff = Math.floor((e - s) / 1000);
  const m = Math.floor(diff / 60);
  const sec = diff % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

export default function MissionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const logRef = useRef<HTMLDivElement>(null);

  const { data: mission, isLoading } = useQuery({
    queryKey: ['mission', id],
    queryFn: () => missions.get(id!),
    refetchInterval: (query) => {
      const m = query.state.data as Mission | undefined;
      if (!m) return 3000;
      return ['executing', 'planning', 'pending'].includes(m.status) ? 3000 : false;
    },
    enabled: !!id,
  });

  const { mutate: cancelMission, isPending: cancelling } = useMutation({
    mutationFn: () => missions.cancel(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mission', id] });
      queryClient.invalidateQueries({ queryKey: ['missions'] });
    },
  });

  // Auto-scroll log to bottom
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [mission]);

  if (isLoading) {
    return (
      <Layout title="Mission Detail">
        <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}><Spinner size={40} /></div>
      </Layout>
    );
  }

  if (!mission) {
    return (
      <Layout title="Mission Not Found">
        <div style={{ color: 'var(--text-2)', padding: 40 }}>Mission not found.</div>
      </Layout>
    );
  }

  const progress = mission.progress_percentage ?? (mission.status === 'completed' ? 100 : mission.status === 'failed' ? 0 : 50);
  const budgetPct = mission.budget_limit ? Math.round((mission.credits_used / mission.budget_limit) * 100) : 0;

  return (
    <Layout
      title={`Missions / ${mission.goal.slice(0, 40)}${mission.goal.length > 40 ? '…' : ''}`}
      actions={
        ['executing', 'planning', 'pending'].includes(mission.status) ? (
          <Btn variant="danger" size="sm" onClick={() => cancelMission()} disabled={cancelling}>
            {cancelling ? 'Cancelling…' : 'Cancel Mission'}
          </Btn>
        ) : (
          <Btn variant="secondary" size="sm" onClick={() => navigate('/missions')}>
            ← Back to Missions
          </Btn>
        )
      }
    >
      {/* Mission header card */}
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>{mission.goal}</div>
            <div style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: 'var(--text-3)', marginBottom: 12 }}>
              {mission.mission_id}
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
              <Badge variant={statusVariant(mission.status)}>{mission.status}</Badge>
              {mission.agent_name && (
                <span style={{ fontSize: 13, color: 'var(--text-2)' }}>Agent: {mission.agent_name}</span>
              )}
              {mission.started_at && (
                <span style={{ fontSize: 13, color: 'var(--text-2)' }}>
                  Duration: {formatDuration(mission.started_at, mission.completed_at)}
                </span>
              )}
              {mission.complexity && (
                <span style={{ fontSize: 13, color: 'var(--text-2)' }}>Complexity: {mission.complexity}</span>
              )}
            </div>
          </div>
          {mission.budget_limit && (
            <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 24 }}>
              <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 4 }}>Budget Used</div>
              <div style={{ fontSize: 24, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>
                {mission.credits_used} <span style={{ fontSize: 14, color: 'var(--text-2)' }}>/ {mission.budget_limit}</span>
              </div>
              <div style={{ width: 160, marginTop: 6 }}>
                <div style={{ height: 4, background: 'var(--surface-2)', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{
                    height: '100%', width: `${Math.min(100, budgetPct)}%`,
                    background: budgetPct > 80 ? 'var(--danger)' : 'var(--warning)',
                    borderRadius: 2, transition: 'width 0.5s',
                  }} />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Progress bar */}
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-2)', marginBottom: 6 }}>
            <span>Progress</span>
            <span>{progress}%</span>
          </div>
          <div style={{ height: 6, background: 'var(--surface-2)', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{
              height: '100%', width: `${progress}%`,
              background: mission.status === 'completed' ? 'var(--success)' : mission.status === 'failed' ? 'var(--danger)' : 'var(--accent)',
              borderRadius: 3, transition: 'width 0.5s ease',
            }} />
          </div>
        </div>
      </Card>

      {/* Two-column: Timeline + Log */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* Execution Timeline */}
        <Card>
          <CardTitle>Execution Timeline</CardTitle>
          {mission.steps && mission.steps.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {mission.steps.map((step, i) => (
                <div key={step.step_id || i} style={{ display: 'flex', gap: 12, paddingBottom: 16, position: 'relative' }}>
                  <div style={{
                    width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 11, fontWeight: 700, zIndex: 1,
                    background: step.status === 'completed' ? 'rgba(34,211,160,0.15)' :
                      step.status === 'running' ? 'rgba(108,99,255,0.15)' :
                      step.status === 'failed' ? 'rgba(239,68,68,0.15)' : 'var(--surface-2)',
                    color: step.status === 'completed' ? 'var(--success)' :
                      step.status === 'running' ? 'var(--accent)' :
                      step.status === 'failed' ? 'var(--danger)' : 'var(--text-3)',
                  }}>
                    {step.status === 'completed' ? '✓' : step.status === 'running' ? '⚡' : step.status === 'failed' ? '✗' : '○'}
                  </div>
                  {i < (mission.steps?.length ?? 0) - 1 && (
                    <div style={{
                      position: 'absolute', left: 13, top: 28, bottom: 0,
                      width: 1, background: 'var(--border)',
                    }} />
                  )}
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{step.description}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>
                      {step.tool_used && `Tool: ${step.tool_used} · `}
                      {step.credits_used ? `${step.credits_used} credits` : ''}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ color: 'var(--text-3)', fontSize: 13 }}>
              {['executing', 'planning'].includes(mission.status)
                ? 'Execution in progress…'
                : 'No step data available.'}
            </div>
          )}
        </Card>

        {/* Live Agent Log */}
        <Card>
          <CardTitle>
            Live Agent Log
            {['executing', 'planning'].includes(mission.status) && (
              <span style={{
                marginLeft: 8, display: 'inline-block',
                width: 6, height: 6, borderRadius: '50%',
                background: 'var(--success)', animation: 'pulse 2s infinite',
              }} />
            )}
          </CardTitle>
          <div
            ref={logRef}
            style={{
              background: 'var(--bg)', borderRadius: 6, padding: 12,
              height: 280, overflowY: 'auto',
              fontFamily: 'JetBrains Mono, monospace', fontSize: 11, lineHeight: 1.8,
            }}
          >
            {mission.status === 'pending' && (
              <div style={{ color: 'var(--text-3)' }}>Waiting for agent assignment…</div>
            )}
            {['executing', 'planning'].includes(mission.status) && (
              <div style={{ color: 'var(--success)' }}>[INFO] Mission active — processing…</div>
            )}
            {mission.result?.output && mission.result.output.split('\n').map((line, i) => (
              <div key={i} style={{ color: 'var(--text-2)' }}>{line}</div>
            ))}
            {mission.status === 'completed' && !mission.result?.output && (
              <div style={{ color: 'var(--success)' }}>[INFO] Mission completed successfully.</div>
            )}
            {mission.status === 'failed' && (
              <div style={{ color: 'var(--danger)' }}>[ERROR] Mission failed.</div>
            )}
          </div>
        </Card>
      </div>

      {/* Result */}
      {mission.result && (
        <Card>
          <CardTitle>Mission Result</CardTitle>
          {mission.result.quality_score !== undefined && (
            <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 13, color: 'var(--text-2)' }}>Quality Score:</span>
              <span style={{ fontSize: 20, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: 'var(--success)' }}>
                {mission.result.quality_score}/10
              </span>
            </div>
          )}
          <div style={{
            background: 'var(--surface-2)', borderRadius: 8, padding: 16,
            fontSize: 13, lineHeight: 1.7, whiteSpace: 'pre-wrap',
            maxHeight: 400, overflowY: 'auto',
          }}>
            {mission.result.summary || mission.result.output || 'No result content available.'}
          </div>
        </Card>
      )}
    </Layout>
  );
}
