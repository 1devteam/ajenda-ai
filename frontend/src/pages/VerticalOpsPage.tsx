import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { createVerticalTemplateMission, getBusinessProfileReadiness, listProviderCredentials, listVerticalTemplates } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import type { CustomerSession, ProviderCredentialResponse, VerticalTemplate } from "../types";
import { newIdempotencyKey } from "../utils/errors";
import { buildVerticalPlan, socialConnections, type PlanFields } from "../verticalOps/planModel";
import VerticalPlanReview from "../verticalOps/VerticalPlanReview";

function TemplateForm({ template, session, credentials, connectionsLoading }: {
  template: VerticalTemplate;
  session: CustomerSession;
  credentials: ProviderCredentialResponse[];
  connectionsLoading: boolean;
}) {
  const [fields, setFields] = useState<PlanFields>({ query: "", content: "", platform: "", credentialId: "" });
  const [operationKey, setOperationKey] = useState(newIdempotencyKey);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [missionId, setMissionId] = useState<string | null>(null);
  const [profileReadiness, setProfileReadiness] = useState<Awaited<ReturnType<typeof getBusinessProfileReadiness>> | null>(null);
  const [profileReadinessLoading, setProfileReadinessLoading] = useState(true);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    let cancelled = false;
    setProfileReadinessLoading(true);
    void getBusinessProfileReadiness(session, template.template_id)
      .then((response) => { if (!cancelled) setProfileReadiness(response); })
      .catch((caught) => { if (!cancelled) setError(caught); })
      .finally(() => { if (!cancelled) setProfileReadinessLoading(false); });
    return () => { cancelled = true; };
  }, [session, template.template_id]);
  const defaults = template.steps.filter((step) => step.include_by_default);
  const research = defaults.some((step) => step.action_name === "web.research");
  const social = defaults.some((step) => step.action_name === "gtm.social_publish");
  const connections = socialConnections(credentials, session.tenantId);
  let blocker = "";
  try {
    buildVerticalPlan(template, fields, credentials, session.tenantId, operationKey);
  } catch (caught) {
    blocker = (caught as Error).message;
  }
  if (profileReadinessLoading) blocker = "Checking business profile readiness…";
  else if (!profileReadiness) blocker = "Business profile readiness could not be verified.";
  else if (profileReadiness && !profileReadiness.ready_for_template) {
    blocker = `Complete business profile categories before planning: ${profileReadiness.missing_required_categories.join(", ")}.`;
  }

  function update(name: keyof PlanFields, value: string) {
    setFields((current) => ({ ...current, [name]: value }));
    setOperationKey(newIdempotencyKey());
    setError(null);
    setMissionId(null);
  }

  async function createPlan(event: React.FormEvent) {
    event.preventDefault();
    if (inFlight.current || missionId) return;
    inFlight.current = true;
    setLaunching(true);
    setError(null);
    try {
      const body = buildVerticalPlan(template, fields, credentials, session.tenantId, operationKey);
      const response = await createVerticalTemplateMission(session, body, { idempotencyKey: operationKey });
      if (response.queued || response.template_id !== template.template_id || !response.mission_id) {
        throw new Error("The server returned an unexpected plan result. Check mission activity before retrying.");
      }
      if (mounted.current) setMissionId(response.mission_id);
    } catch (caught) {
      if (mounted.current) setError(caught);
    } finally {
      inFlight.current = false;
      if (mounted.current) setLaunching(false);
    }
  }

  return (
    <article className="panel space-y-3">
      <h2>{template.display_name}</h2>
      <p className="muted">{template.description}</p>
      <p>{defaults.length} planned step(s){!template.allows_runtime_queue ? " · Planning only; execution unavailable" : ""}</p>
      {profileReadiness && !profileReadiness.ready_for_template ?
        <p role="status" className="field-hint">Missing profile categories: {profileReadiness.missing_required_categories.join(", ")}</p> : null}
      <form className="form-grid" onSubmit={(event) => void createPlan(event)}>
        <fieldset disabled={launching || !!missionId} className="space-y-3">
          {research ? <label>Research question
            <textarea required maxLength={500} value={fields.query} onChange={(event) => update("query", event.target.value)} />
            <span className="field-hint">Searches approved internal information. Include the company or topic to investigate.</span>
          </label> : null}
          {social ? <>
            <label>Post content
              <textarea required maxLength={280} value={fields.content} onChange={(event) => update("content", event.target.value)} />
            </label>
            <label>Platform
              <input required maxLength={80} value={fields.platform} onChange={(event) => update("platform", event.target.value)} />
              <span className="field-hint">Use the platform supported by your publishing connection.</span>
            </label>
            <label>Publishing connection
              <select required value={fields.credentialId} onChange={(event) => update("credentialId", event.target.value)}>
                <option value="">Choose a connection</option>
                {connections.map((item) => <option key={item.credential_id} value={item.credential_id}>{item.credential_id}</option>)}
              </select>
            </label>
            {connectionsLoading ? <p>Checking publishing connections…</p> : connections.length === 0 ?
              <p role="status">Social planning is unavailable without a compatible publishing connection. Self-service social publishing setup is not available yet; ask your workspace administrator. LinkedIn read connections cannot publish.</p> : null}
            <p className="field-hint">Creates a plan for review. Publishing requires separate authorization.</p>
          </> : null}
        </fieldset>
        {blocker && !missionId ? <p className="field-hint">{blocker}</p> : null}
        <button type="submit" className="button" disabled={launching || !!missionId || !!blocker || (social && connectionsLoading)}>
          {launching ? "Creating plan…" : missionId ? "Plan created" : "Create mission plan"}
        </button>
      </form>
      <PageErrorAlert error={error} />
      {missionId ? <div role="status" className="success-banner">
        <p>Plan saved for review. No work was queued.</p>
        <Link to={`/vertical-ops?mission=${encodeURIComponent(missionId)}`}>Review saved plan</Link>
      </div> : null}
    </article>
  );
}

function TemplateWorkspace({ session }: { session: CustomerSession }) {
  const [templates, setTemplates] = useState<VerticalTemplate[]>([]);
  const [credentials, setCredentials] = useState<ProviderCredentialResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [connectionsLoading, setConnectionsLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [connectionError, setConnectionError] = useState<unknown>(null);
  useEffect(() => {
    let cancelled = false;
    setConnectionsLoading(true);
    setCredentials([]);
    setConnectionError(null);
    void listVerticalTemplates(session)
      .then((response) => { if (!cancelled) setTemplates(response.templates); })
      .catch((caught) => { if (!cancelled) setError(caught); })
      .finally(() => { if (!cancelled) setLoading(false); });
    void listProviderCredentials(session)
      .then((response) => { if (!cancelled) setCredentials(response.credentials); })
      .catch((caught) => { if (!cancelled) setConnectionError(caught); })
      .finally(() => { if (!cancelled) setConnectionsLoading(false); });
    return () => { cancelled = true; };
  }, [session]);
  return <main className="page-shell">
    <PageHeader title="Vertical operations" lead="Choose a plan, provide its details, then review the saved work." />
    <PageErrorAlert error={error} />
    {connectionError ? <section><p>Publishing connections could not be loaded. Research and other plans remain available.</p><PageErrorAlert error={connectionError} /></section> : null}
    {loading ? <p>Loading templates…</p> : !error && templates.length === 0 ? <p>No templates are available.</p> : null}
    <section className="grid gap-4 md:grid-cols-2" aria-label="Vertical templates">
      {templates.map((template) => <TemplateForm key={template.template_id} template={template} session={session} credentials={credentials} connectionsLoading={connectionsLoading} />)}
    </section>
  </main>;
}

export default function VerticalOpsPage() {
  const { session } = useAuth();
  const [params] = useSearchParams();
  const missionId = params.get("mission");
  if (!session) return <main><p>Sign in to view vertical operations.</p></main>;
  // A tenant switch discards drafts, connection selections, results and pending reads.
  return missionId
    ? <VerticalPlanReview key={`${session.tenantId}:${missionId}`} session={session} missionId={missionId} />
    : <TemplateWorkspace key={session.tenantId} session={session} />;
}
