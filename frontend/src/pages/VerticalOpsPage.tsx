import { useEffect, useState } from "react";
import { createVerticalTemplateMission, listVerticalTemplates } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import type { VerticalTemplate } from "../types";

export default function VerticalOpsPage() {
  const { session } = useAuth();
  const [templates, setTemplates] = useState<VerticalTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [launching, setLaunching] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    void listVerticalTemplates(session)
      .then((response) => setTemplates(response.templates))
      .catch(setError)
      .finally(() => setLoading(false));
  }, [session]);

  async function createPlan(template: VerticalTemplate) {
    if (!session) return;
    setLaunching(template.template_id);
    setError(null);
    setResult(null);
    try {
      const response = await createVerticalTemplateMission(session, {
        template_id: template.template_id,
        mission_objective: template.objective_template,
      });
      setResult(`Plan created: ${response.mission_id}`);
    } catch (caught) {
      setError(caught);
    } finally {
      setLaunching(null);
    }
  }

  return (
    <main className="page-shell">
      <PageHeader title="Vertical operations" lead="Choose a governed vertical plan and stage it for mission review." />
      {error ? <PageErrorAlert error={error} /> : null}
      {result ? <p className="success-banner">{result}. No runtime tasks were queued.</p> : null}
      {loading ? <p className="muted">Loading server templates…</p> : null}
      <section className="grid gap-4 md:grid-cols-2" aria-label="Vertical templates">
        {templates.map((template) => (
          <article key={template.template_id} className="panel space-y-3">
            <div>
              <p className="eyebrow">{template.role_key} · {template.phase}</p>
              <h2>{template.display_name}</h2>
              <p className="muted">{template.description}</p>
            </div>
            <p className="text-xs text-zinc-400">{template.steps.length} steps · {template.authority_class}</p>
            <button
              type="button"
              className="button"
              disabled={launching === template.template_id}
              onClick={() => void createPlan(template)}
            >
              {launching === template.template_id ? "Creating plan…" : "Create mission plan"}
            </button>
          </article>
        ))}
      </section>
    </main>
  );
}
