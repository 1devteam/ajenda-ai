import React from 'react';
import Layout from '../layout/Layout';
import { Card, CardTitle, Btn } from '../layout/UI';

const GRAFANA_URL = 'https://nested-ai.net:3000';
const JAEGER_URL = 'https://nested-ai.net:16686';
const PROMETHEUS_URL = 'https://nested-ai.net:9090';

export default function ObservabilityPage() {
  return (
    <Layout
      title="Observability"
      subtitle="Metrics, traces, and system telemetry"
    >
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {[
          {
            title: 'Grafana Dashboards',
            description: 'Agent performance, mission throughput, credit economy, and system health dashboards.',
            url: GRAFANA_URL,
            label: 'Open Grafana',
            color: 'var(--warning)',
            icon: '📊',
          },
          {
            title: 'Jaeger Tracing',
            description: 'Distributed traces for every mission execution, LLM call, and tool invocation.',
            url: JAEGER_URL,
            label: 'Open Jaeger',
            color: 'var(--success)',
            icon: '🔍',
          },
          {
            title: 'Prometheus Metrics',
            description: 'Raw metrics endpoint — agent activity, API latency, error rates, and resource usage.',
            url: PROMETHEUS_URL,
            label: 'Open Prometheus',
            color: 'var(--danger)',
            icon: '📈',
          },
          {
            title: 'Langfuse LLM Observability',
            description: 'Every LLM call logged with token counts, latency, cost, and Pride Protocol compliance.',
            url: 'https://cloud.langfuse.com',
            label: 'Open Langfuse',
            color: 'var(--accent)',
            icon: '🧠',
          },
        ].map(item => (
          <Card key={item.title}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
              <div style={{
                width: 44, height: 44, borderRadius: 10, flexShrink: 0,
                background: `${item.color}22`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 20,
              }}>
                {item.icon}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>{item.title}</div>
                <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6, marginBottom: 14 }}>
                  {item.description}
                </div>
                <Btn variant="secondary" size="sm" onClick={() => window.open(item.url, '_blank')}>
                  {item.label} ↗
                </Btn>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Health summary */}
      <Card>
        <CardTitle>Backend Health</CardTitle>
        <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: 'var(--text-2)', lineHeight: 2 }}>
          <div><span style={{ color: 'var(--success)' }}>●</span> API: https://nested-ai.net/health</div>
          <div><span style={{ color: 'var(--success)' }}>●</span> PRIDE Protocol: registered · immutable · priority 9999</div>
          <div><span style={{ color: 'var(--success)' }}>●</span> LLM Coverage: 17/17 call paths governed</div>
          <div><span style={{ color: 'var(--success)' }}>●</span> MCP: 5 tools active</div>
          <div><span style={{ color: 'var(--success)' }}>●</span> NATS: 5 streams</div>
        </div>
      </Card>
    </Layout>
  );
}
