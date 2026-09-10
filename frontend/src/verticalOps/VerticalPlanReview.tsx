import { useEffect, useState } from "react";
import { Link } from "react-router";
import { getMissionLifecycle } from "../api/client";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import type { CustomerSession, MissionLifecycleReadResponse } from "../types";

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export default function VerticalPlanReview({ session, missionId }: { session: CustomerSession; missionId: string }) {
  const [lifecycle, setLifecycle] = useState<MissionLifecycleReadResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let cancelled = false;
    setLifecycle(null);
    setError(null);
    void getMissionLifecycle(session, missionId).then((response) => {
      if (response.mission.tenant_id !== session.tenantId || response.mission.mission_id !== missionId) {
        throw new Error("The saved plan does not belong to this workspace or mission.");
      }
      const graph = response.task_graph;
      const templateId = record(graph?.metadata).template_id;
      if (typeof templateId !== "string" || !templateId.startsWith("vertical.") || !Array.isArray(graph?.nodes)) {
        throw new Error("A saved vertical plan is not available for this mission.");
      }
      if (!cancelled) setLifecycle(response);
    }).catch((caught) => { if (!cancelled) setError(caught); });
    return () => { cancelled = true; };
  }, [session, missionId]);
  const nodes = (lifecycle?.task_graph?.nodes ?? []) as unknown[];
  return <main className="page-shell">
    <PageHeader title="Review saved plan" lead={lifecycle?.mission.objective ?? "Loading saved mission…"} />
    <Link to="/vertical-ops">Back to vertical operations</Link>
    <PageErrorAlert error={error} />
    {lifecycle ? <section className="panel space-y-3">
      <p>Mission status: {lifecycle.mission.status}</p>
      <p>This view shows the saved plan. Execution and any required approvals are separate steps.</p>
      {record(lifecycle.task_graph?.metadata).allows_runtime_queue === false ? <p>Planning only: execution is unavailable for this template.</p> : null}
      <ol>
        {nodes.map((value, index) => {
          const node = record(value);
          const input = record(record(node.input_contract).tool_input);
          return <li key={String(node.node_key ?? index)} className="space-y-3">
            <h2>{String(node.title ?? `Step ${index + 1}`)}</h2>
            <p>{String(node.description ?? "")}</p>
            <dl>
              {([['query', 'Research question'], ['platform', 'Platform'], ['content', 'Post content']] as const).map(([key, label]) =>
                typeof input[key] === "string" ? <div key={key}><dt>{label}</dt><dd className="whitespace-pre-wrap">{input[key]}</dd></div> : null,
              )}
            </dl>
          </li>;
        })}
      </ol>
    </section> : null}
  </main>;
}
