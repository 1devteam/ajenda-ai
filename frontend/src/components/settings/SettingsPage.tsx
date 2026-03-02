import React from 'react';
import Layout from '../layout/Layout';
import { Card, CardTitle } from '../layout/UI';

export default function SettingsPage() {
  return (
    <Layout title="Settings" subtitle="Platform configuration and API access">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Card>
          <CardTitle>API Access</CardTitle>
          <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.7, marginBottom: 12 }}>
            The full REST API is available at the base URL below. All endpoints require a Bearer token.
          </div>
          <div style={{
            background: 'var(--bg)', borderRadius: 6, padding: '10px 14px',
            fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: 'var(--accent)',
            marginBottom: 12,
          }}>
            https://nested-ai.net/api/v1
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
            Interactive docs: <a href="https://nested-ai.net/api/v1/docs" target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>
              /api/v1/docs
            </a>
          </div>
        </Card>

        <Card>
          <CardTitle>LLM Providers</CardTitle>
          {[
            { name: 'OpenAI', models: 'gpt-4o, gpt-4o-mini', status: true },
            { name: 'Anthropic', models: 'claude-3-5-sonnet', status: true },
            { name: 'Google', models: 'gemini-1.5-pro', status: true },
          ].map(p => (
            <div key={p.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-2)' }}>{p.models}</div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--success)' }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--success)' }} />
                Configured
              </div>
            </div>
          ))}
        </Card>

        <Card>
          <CardTitle>PRIDE Protocol</CardTitle>
          <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.7 }}>
            The PRIDE Protocol is an immutable governance layer applied to all 17 LLM call paths in the system.
            It cannot be disabled, modified, or removed via the API. Changes require a code deployment.
          </div>
          <div style={{ marginTop: 12, padding: '10px 14px', background: 'var(--accent-dim)', borderRadius: 6, border: '1px solid rgba(108,99,255,0.2)' }}>
            <div style={{ fontSize: 12, fontFamily: 'JetBrains Mono, monospace', color: 'var(--accent)' }}>
              Policy ID: citadel.pride.v1<br />
              Version: 1.0<br />
              Priority: 9999<br />
              Immutable: true<br />
              Coverage: 17/17 call paths
            </div>
          </div>
        </Card>

        <Card>
          <CardTitle>Observability</CardTitle>
          {[
            { name: 'Langfuse', detail: 'LLM call tracing and cost tracking', url: 'https://cloud.langfuse.com', status: true },
            { name: 'Prometheus', detail: 'Metrics collection', url: 'https://nested-ai.net:9090', status: true },
            { name: 'Grafana', detail: 'Dashboards and alerting', url: 'https://nested-ai.net:3000', status: true },
            { name: 'Jaeger', detail: 'Distributed tracing', url: 'https://nested-ai.net:16686', status: true },
          ].map(s => (
            <div key={s.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{s.name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-2)' }}>{s.detail}</div>
              </div>
              <a href={s.url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>
                Open ↗
              </a>
            </div>
          ))}
        </Card>
      </div>
    </Layout>
  );
}
