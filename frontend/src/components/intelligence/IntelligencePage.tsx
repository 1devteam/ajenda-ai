import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import Layout from '../layout/Layout';
import { Card, CardTitle, Btn, Textarea } from '../layout/UI';
import { missions } from '../../services/api';

const QUICK_MISSIONS = [
  {
    label: 'Market Research',
    goal: 'Research the current state of the AI agent market in 2025. Identify top players, market size, growth trends, and key differentiators. Provide a structured report with executive summary.',
  },
  {
    label: 'Code Analysis',
    goal: 'Analyze best practices for building production-grade Python async APIs with FastAPI. Cover authentication, rate limiting, error handling, observability, and deployment patterns.',
  },
  {
    label: 'Competitive Analysis',
    goal: 'Analyze the competitive landscape for multi-agent AI platforms. Compare AutoGPT, CrewAI, LangGraph, and Microsoft AutoGen on architecture, capabilities, and enterprise readiness.',
  },
  {
    label: 'Technical Report',
    goal: 'Write a technical report on the trade-offs between different vector database solutions (Pinecone, Weaviate, Qdrant, pgvector) for a production RAG system handling 10M+ documents.',
  },
];

export default function IntelligencePage() {
  const [goal, setGoal] = useState('');
  const [launched, setLaunched] = useState<string | null>(null);
  const navigate = useNavigate();

  const { mutate, isPending, error } = useMutation({
    mutationFn: (g: string) => missions.create({ goal: g, tenant_id: 'default' }),
    onSuccess: (data) => {
      setLaunched(data.mission_id);
    },
  });

  return (
    <Layout
      title="Intelligence"
      subtitle="Quick mission launcher and knowledge operations"
    >
      {/* Quick launch */}
      <Card style={{ marginBottom: 16 }}>
        <CardTitle>Quick Mission Launch</CardTitle>
        <Textarea
          value={goal}
          onChange={setGoal}
          placeholder="Describe your intelligence request in detail…"
          rows={4}
        />
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <Btn
            variant="primary"
            onClick={() => { if (goal.trim()) mutate(goal); }}
            disabled={isPending || !goal.trim()}
          >
            {isPending ? 'Launching…' : '⚡ Launch Mission'}
          </Btn>
          {launched && (
            <Btn variant="secondary" onClick={() => navigate(`/missions/${launched}`)}>
              View Mission →
            </Btn>
          )}
          {error && (
            <span style={{ color: 'var(--danger)', fontSize: 12 }}>{(error as Error).message}</span>
          )}
        </div>
      </Card>

      {/* Quick mission templates */}
      <div style={{ marginBottom: 8, fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)' }}>
        Quick Templates
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {QUICK_MISSIONS.map(qm => (
          <Card
            key={qm.label}
            style={{ cursor: 'pointer', transition: 'border-color 0.15s' }}
            className="hover-card"
          >
            <div style={{ fontWeight: 600, marginBottom: 6 }}>{qm.label}</div>
            <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6, marginBottom: 12 }}>
              {qm.goal.slice(0, 120)}…
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Btn variant="ghost" size="sm" onClick={() => setGoal(qm.goal)}>
                Use Template
              </Btn>
              <Btn variant="primary" size="sm" onClick={() => mutate(qm.goal)} disabled={isPending}>
                Launch →
              </Btn>
            </div>
          </Card>
        ))}
      </div>
    </Layout>
  );
}
