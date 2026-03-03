/**
 * RevenuePage — Sales Pipeline Dashboard
 *
 * Displays the full revenue pipeline: KPI stats, leads table, open opportunities,
 * and closed deals. Supports adding new leads and running the AI qualification
 * pipeline directly from the UI.
 *
 * Built with Pride for Obex Blackvault
 */
import React, { useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Layout from '../layout/Layout';
import {
  StatCard, Card, CardTitle, Btn, Badge, Table, Tr, Td,
  Spinner, EmptyState, Input, Textarea,
} from '../layout/UI';
import { revenue } from '../../services/api';
import type { Lead, Opportunity, Deal, LeadStatus, OpportunityStatus } from '../../types';

// ─── Helpers ────────────────────────────────────────────────────────────────

function fmt(n?: number): string {
  if (n === undefined || n === null) return '—';
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toLocaleString()}`;
}

function pct(n?: number): string {
  if (n === undefined || n === null) return '—';
  return `${Math.round(n * 100)}%`;
}

function relDate(iso?: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return 'today';
  if (days === 1) return '1d ago';
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
}

const LEAD_BADGE: Record<LeadStatus, { variant: 'active' | 'pending' | 'info' | 'inactive' | 'error'; label: string }> = {
  new:          { variant: 'info',     label: 'New' },
  contacted:    { variant: 'pending',  label: 'Contacted' },
  qualified:    { variant: 'active',   label: 'Qualified' },
  disqualified: { variant: 'error',    label: 'Disqualified' },
  converted:    { variant: 'active',   label: 'Converted' },
};

const OPP_BADGE: Record<OpportunityStatus, { variant: 'active' | 'pending' | 'info' | 'inactive' | 'error'; label: string }> = {
  open:          { variant: 'info',    label: 'Open' },
  proposal_sent: { variant: 'pending', label: 'Proposal Sent' },
  negotiating:   { variant: 'pending', label: 'Negotiating' },
  closed_won:    { variant: 'active',  label: 'Won' },
  closed_lost:   { variant: 'error',   label: 'Lost' },
};

// ─── Add Lead Modal ──────────────────────────────────────────────────────────

interface AddLeadModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

function AddLeadModal({ onClose, onSuccess }: AddLeadModalProps) {
  const [form, setForm] = useState({
    company_name: '',
    industry: '',
    company_size: '',
    contact_name: '',
    contact_email: '',
    website: '',
    notes: '',
  });
  const [error, setError] = useState('');

  const mutation = useMutation({
    mutationFn: () => revenue.createLead(form),
    onSuccess: () => { onSuccess(); onClose(); },
    onError: (e: Error) => setError(e.message),
  });

  const set = (k: string) => (v: string) => setForm(f => ({ ...f, [k]: v }));

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)', padding: 28, width: 480, maxHeight: '90vh',
        overflowY: 'auto',
      }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 20 }}>Add New Lead</div>

        <Input label="Company Name *" value={form.company_name} onChange={set('company_name')} placeholder="Acme Corp" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Input label="Industry" value={form.industry} onChange={set('industry')} placeholder="retail" />
          <Input label="Company Size" value={form.company_size} onChange={set('company_size')} placeholder="smb / mid / enterprise" />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Input label="Contact Name" value={form.contact_name} onChange={set('contact_name')} placeholder="Jane Smith" />
          <Input label="Contact Email" value={form.contact_email} onChange={set('contact_email')} placeholder="jane@acme.com" />
        </div>
        <Input label="Website" value={form.website} onChange={set('website')} placeholder="https://acme.com" />
        <Textarea label="Notes" value={form.notes} onChange={set('notes')} placeholder="Initial context, referral source, etc." rows={3} />

        {error && (
          <div style={{ color: 'var(--danger)', fontSize: 12, marginBottom: 12 }}>{error}</div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <Btn variant="secondary" onClick={onClose}>Cancel</Btn>
          <Btn
            variant="primary"
            onClick={() => mutation.mutate()}
            disabled={!form.company_name.trim() || mutation.isPending}
          >
            {mutation.isPending ? 'Adding…' : 'Add Lead'}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ─── Qualify Lead Modal ──────────────────────────────────────────────────────

interface QualifyModalProps {
  lead: Lead;
  onClose: () => void;
  onSuccess: () => void;
}

function QualifyModal({ lead, onClose, onSuccess }: QualifyModalProps) {
  const [vp, setVp] = useState('');
  const [icp, setIcp] = useState('');
  const [result, setResult] = useState<{ qualification_score: number; notes?: string } | null>(null);
  const [error, setError] = useState('');

  const mutation = useMutation({
    mutationFn: () => revenue.qualifyLead(lead.id, {
      value_proposition: vp,
      ideal_customer_profile: icp,
    }),
    onSuccess: (data) => {
      setResult({ qualification_score: data.qualification_score });
      onSuccess();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)', padding: 28, width: 480,
      }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>
          AI Qualify: {lead.company_name}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 20 }}>
          The Revenue Agent will score this lead and create an opportunity if qualified.
        </div>

        {result ? (
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <div style={{ fontSize: 48, fontWeight: 700, color: result.qualification_score >= 0.7 ? 'var(--success)' : 'var(--warning)' }}>
              {Math.round(result.qualification_score * 100)}
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 4 }}>Qualification Score</div>
            <div style={{ marginTop: 16 }}>
              <Btn variant="primary" onClick={onClose}>Done</Btn>
            </div>
          </div>
        ) : (
          <>
            <Textarea
              label="Value Proposition"
              value={vp}
              onChange={setVp}
              placeholder="What problem do we solve for them?"
              rows={3}
            />
            <Textarea
              label="Ideal Customer Profile"
              value={icp}
              onChange={setIcp}
              placeholder="SMB retail companies with 10-200 employees..."
              rows={3}
            />
            {error && <div style={{ color: 'var(--danger)', fontSize: 12, marginBottom: 12 }}>{error}</div>}
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <Btn variant="secondary" onClick={onClose}>Cancel</Btn>
              <Btn
                variant="primary"
                onClick={() => mutation.mutate()}
                disabled={!vp.trim() || !icp.trim() || mutation.isPending}
              >
                {mutation.isPending ? (
                  <><Spinner size={14} /> Qualifying…</>
                ) : 'Run AI Qualification'}
              </Btn>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function RevenuePage() {
  const qc = useQueryClient();
  const [showAddLead, setShowAddLead] = useState(false);
  const [qualifyLead, setQualifyLead] = useState<Lead | null>(null);
  const [activeTab, setActiveTab] = useState<'leads' | 'pipeline' | 'deals'>('leads');
  const [leadFilter, setLeadFilter] = useState<string>('');

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['revenue'] });
  }, [qc]);

  // Data queries
  const { data: dash, isLoading: dashLoading } = useQuery({
    queryKey: ['revenue', 'dashboard'],
    queryFn: revenue.dashboard,
    refetchInterval: 30_000,
  });

  const { data: leadsData, isLoading: leadsLoading } = useQuery({
    queryKey: ['revenue', 'leads', leadFilter],
    queryFn: () => revenue.listLeads({ status: leadFilter || undefined, limit: 50 }),
    refetchInterval: 15_000,
  });

  const { data: pipelineData, isLoading: pipelineLoading } = useQuery({
    queryKey: ['revenue', 'pipeline'],
    queryFn: () => revenue.pipeline({ limit: 50 }),
    refetchInterval: 15_000,
  });

  const { data: dealsData, isLoading: dealsLoading } = useQuery({
    queryKey: ['revenue', 'deals'],
    queryFn: () => revenue.listDeals({ limit: 50 }),
    refetchInterval: 15_000,
  });

  const leads: Lead[] = leadsData?.items || [];
  const opportunities: Opportunity[] = pipelineData?.items || [];
  const deals: Deal[] = dealsData?.items || [];

  const tabs = [
    { key: 'leads',    label: `Leads (${leadsData?.total ?? '…'})` },
    { key: 'pipeline', label: `Pipeline (${pipelineData?.total ?? '…'})` },
    { key: 'deals',    label: `Deals (${dealsData?.total ?? '…'})` },
  ] as const;

  return (
    <Layout
      title="Revenue Pipeline"
      subtitle="AI-powered sales pipeline — from lead discovery to closed deals"
      actions={
        <Btn variant="primary" onClick={() => setShowAddLead(true)}>
          + Add Lead
        </Btn>
      }
    >
      {/* KPI Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16, marginBottom: 24 }}>
        {dashLoading ? (
          Array.from({ length: 6 }).map((_, i) => (
            <div key={i} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 90 }}>
              <Spinner />
            </div>
          ))
        ) : (
          <>
            <StatCard label="Total Leads"       value={dash?.total_leads ?? 0} />
            <StatCard label="Qualified"         value={dash?.qualified_leads ?? 0}
              delta={dash?.total_leads ? `${Math.round((dash.qualified_leads / dash.total_leads) * 100)}% rate` : undefined}
              deltaDir="neutral" />
            <StatCard label="Pipeline Value"    value={fmt(dash?.total_pipeline_value)} progressVariant="accent"
              progress={dash?.total_pipeline_value ? Math.min(100, (dash.total_pipeline_value / 500000) * 100) : 0} />
            <StatCard label="Proposals Sent"    value={dash?.proposals_sent ?? 0} />
            <StatCard label="Deals Closed"      value={dash?.deals_closed ?? 0} />
            <StatCard label="Total Revenue"     value={fmt(dash?.total_revenue)}
              delta={dash?.conversion_rate ? `${pct(dash.conversion_rate)} conv.` : undefined}
              deltaDir={dash?.conversion_rate && dash.conversion_rate > 0.2 ? 'up' : 'neutral'}
              progressVariant="success"
              progress={dash?.total_revenue ? Math.min(100, (dash.total_revenue / 100000) * 100) : 0} />
          </>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)', paddingBottom: 0 }}>
        {tabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '8px 16px', fontSize: 13, fontWeight: 500,
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: activeTab === tab.key ? 'var(--accent)' : 'var(--text-2)',
              borderBottom: activeTab === tab.key ? '2px solid var(--accent)' : '2px solid transparent',
              marginBottom: -1, fontFamily: 'inherit',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Leads Tab */}
      {activeTab === 'leads' && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
            <CardTitle>Leads</CardTitle>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
              {(['', 'new', 'contacted', 'qualified', 'disqualified'] as const).map(s => (
                <Btn
                  key={s}
                  size="sm"
                  variant={leadFilter === s ? 'primary' : 'secondary'}
                  onClick={() => setLeadFilter(s)}
                >
                  {s === '' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)}
                </Btn>
              ))}
            </div>
          </div>

          {leadsLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spinner /></div>
          ) : leads.length === 0 ? (
            <EmptyState message="No leads yet. Add your first lead to get started." />
          ) : (
            <Table headers={['Company', 'Industry', 'Size', 'Contact', 'Score', 'Status', 'Added', 'Actions']}>
              {leads.map(lead => {
                const badge = LEAD_BADGE[lead.status] || { variant: 'inactive' as const, label: lead.status };
                return (
                  <Tr key={lead.id}>
                    <Td>
                      <div style={{ fontWeight: 600 }}>{lead.company_name}</div>
                      {lead.website && (
                        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
                          <a href={lead.website} target="_blank" rel="noopener noreferrer"
                            style={{ color: 'var(--accent)', textDecoration: 'none' }}>
                            {lead.website.replace(/^https?:\/\//, '')}
                          </a>
                        </div>
                      )}
                    </Td>
                    <Td>{lead.industry || '—'}</Td>
                    <Td>{lead.company_size || '—'}</Td>
                    <Td>
                      <div>{lead.contact_name || '—'}</div>
                      {lead.contact_email && (
                        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{lead.contact_email}</div>
                      )}
                    </Td>
                    <Td mono>
                      {lead.qualification_score !== undefined && lead.qualification_score !== null
                        ? (
                          <span style={{
                            color: lead.qualification_score >= 0.7 ? 'var(--success)'
                              : lead.qualification_score >= 0.4 ? 'var(--warning)'
                              : 'var(--danger)',
                          }}>
                            {Math.round(lead.qualification_score * 100)}
                          </span>
                        )
                        : '—'}
                    </Td>
                    <Td><Badge variant={badge.variant}>{badge.label}</Badge></Td>
                    <Td>{relDate(lead.created_at)}</Td>
                    <Td>
                      {lead.status === 'new' || lead.status === 'contacted' ? (
                        <Btn size="sm" variant="primary" onClick={() => setQualifyLead(lead)}>
                          Qualify
                        </Btn>
                      ) : (
                        <Btn size="sm" variant="ghost" onClick={() => setQualifyLead(lead)}>
                          Re-qualify
                        </Btn>
                      )}
                    </Td>
                  </Tr>
                );
              })}
            </Table>
          )}
        </Card>
      )}

      {/* Pipeline Tab */}
      {activeTab === 'pipeline' && (
        <Card>
          <CardTitle>Open Opportunities</CardTitle>
          {pipelineLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spinner /></div>
          ) : opportunities.length === 0 ? (
            <EmptyState message="No open opportunities. Qualify a lead to create one." />
          ) : (
            <Table headers={['Title', 'Value', 'Probability', 'Expected Close', 'Status', 'Stage']}>
              {opportunities.map(opp => {
                const badge = OPP_BADGE[opp.status] || { variant: 'inactive' as const, label: opp.status };
                return (
                  <Tr key={opp.id}>
                    <Td>
                      <div style={{ fontWeight: 600 }}>{opp.title}</div>
                    </Td>
                    <Td mono>{fmt(opp.value)}</Td>
                    <Td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{
                          height: 4, width: 60, background: 'var(--surface-2)',
                          borderRadius: 2, overflow: 'hidden',
                        }}>
                          <div style={{
                            height: '100%',
                            width: `${Math.round(opp.probability * 100)}%`,
                            background: opp.probability >= 0.7 ? 'var(--success)'
                              : opp.probability >= 0.4 ? 'var(--warning)'
                              : 'var(--danger)',
                            borderRadius: 2,
                          }} />
                        </div>
                        <span style={{ fontSize: 12, color: 'var(--text-2)' }}>{pct(opp.probability)}</span>
                      </div>
                    </Td>
                    <Td>{opp.expected_close_date ? new Date(opp.expected_close_date).toLocaleDateString() : '—'}</Td>
                    <Td><Badge variant={badge.variant}>{badge.label}</Badge></Td>
                    <Td>{opp.stage || '—'}</Td>
                  </Tr>
                );
              })}
            </Table>
          )}
        </Card>
      )}

      {/* Deals Tab */}
      {activeTab === 'deals' && (
        <Card>
          <CardTitle>Closed Deals</CardTitle>
          {dealsLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spinner /></div>
          ) : deals.length === 0 ? (
            <EmptyState message="No deals closed yet. Run the full pipeline saga to close your first deal." />
          ) : (
            <Table headers={['Title', 'Value', 'Status', 'Closed']}>
              {deals.map(deal => (
                <Tr key={deal.id}>
                  <Td><div style={{ fontWeight: 600 }}>{deal.title}</div></Td>
                  <Td mono>{fmt(deal.value)}</Td>
                  <Td>
                    <Badge variant={deal.status === 'won' ? 'active' : deal.status === 'lost' ? 'error' : 'pending'}>
                      {deal.status}
                    </Badge>
                  </Td>
                  <Td>{relDate(deal.closed_at || deal.created_at)}</Td>
                </Tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      {/* Modals */}
      {showAddLead && (
        <AddLeadModal onClose={() => setShowAddLead(false)} onSuccess={refresh} />
      )}
      {qualifyLead && (
        <QualifyModal lead={qualifyLead} onClose={() => setQualifyLead(null)} onSuccess={refresh} />
      )}
    </Layout>
  );
}
