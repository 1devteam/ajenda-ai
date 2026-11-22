export function resultRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export function resultRows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.flatMap((item) => {
    const row = resultRecord(item);
    return row ? [row] : [];
  }) : [];
}

function resultText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function readableValue(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "Unavailable";
}

function label(value: unknown): string | null {
  return resultText(value)?.replaceAll("_", " ") ?? null;
}

function ResultList({ title, items }: { title: string; items: unknown }) {
  const entries = Array.isArray(items) ? items.filter((item): item is string => resultText(item) !== null) : [];
  const unique = [...new Set(entries)];
  return unique.length ? (
    <div>
      <h3>{title}</h3>
      <ul>{unique.map((item) => <li key={item}>{item}</li>)}</ul>
    </div>
  ) : null;
}

export function GoalEvaluationResult({ evaluation }: { evaluation: Record<string, unknown> }) {
  const scope = evaluation.evaluation_scope;
  const metrics = resultRows(evaluation.kpi_evaluations);
  const confidence = evaluation.confidence;
  return (
    <div aria-label="Goal evaluation result">
      <p><strong>Assessment</strong> {label(evaluation.status) ?? "Unavailable"}</p>
      {scope === "mission_instruction_only" ? <p>Assessment based on the mission instructions. A stored goal was unavailable.</p> : null}
      {scope === "durable_goal" ? <p>Assessment based on the recorded goal context.</p> : null}
      {scope === "provided_goal_context" ? <p>Assessment based on supplied goal data.</p> : null}
      {typeof confidence === "number" && confidence >= 0 && confidence <= 1
        ? <p><strong>Confidence</strong> {Math.round(confidence * 100)}%</p>
        : null}
      <ResultList title="Assessment explanation" items={evaluation.explanations} />
      {metrics.length ? (
        <div>
          <h3>KPI comparisons</h3>
          <ul>{metrics.map((metric, index) => (
            <li key={resultText(metric.kpi_id) ?? index}>
              <strong>{resultText(metric.metric) ?? resultText(metric.kpi_id) ?? "KPI"}</strong>
              {" · Current "}{readableValue(metric.current_value)}
              {" · Target "}{readableValue(metric.target_value)}
              {label(metric.status) ? ` · ${label(metric.status)}` : null}
              {resultText(metric.explanation) ? <div>{resultText(metric.explanation)}</div> : null}
            </li>
          ))}</ul>
        </div>
      ) : null}
      <ResultList title="Progress gaps" items={resultRows(evaluation.progress_gaps).map((row) => row.message)} />
      <ResultList title="Evidence gaps" items={resultRows(evaluation.evidence_gaps).map((row) => row.message)} />
      <ResultList title="Supporting evidence IDs" items={evaluation.supporting_evidence_ids} />
    </div>
  );
}

function researchSourceLabel(row: Record<string, unknown>): string | null {
  if (row.source_scope === "local_fixture" || row.source === "local_fixture" || row.evidence_class === "fixture") {
    return "Fixture evidence";
  }
  if (row.source_scope === "tenant_internal" || row.source === "internal_record" || row.evidence_class === "tenant_owned_record") {
    return "Internal record";
  }
  if (row.source_scope === "public_search") return "Public search result";
  return null;
}

function ResearchObservations({ title, rows, empty, discovery = false }: {
  title: string;
  rows: unknown;
  empty: string;
  discovery?: boolean;
}) {
  if (!Array.isArray(rows)) return null;
  const observations = resultRows(rows);
  return (
    <div>
      <h4>{title}</h4>
      {observations.length ? (
        <ul>{observations.map((row, index) => {
          const source = researchSourceLabel(row);
          const observation = label(row.reason ?? (discovery ? null : row.identity_status));
          return (
            <li key={index}>
              <strong>{resultText(row.company) ?? resultText(row.url) ?? resultText(row.website) ?? "Source observation"}</strong>
              {resultText(row.company) && (resultText(row.url) ?? resultText(row.website))
                ? <div>{resultText(row.url) ?? resultText(row.website)}</div> : null}
              {source ? <div>{source}</div> : null}
              {observation ? <div>{observation}</div> : null}
              {label(row.source_reliability) ? <div>Source classification: {label(row.source_reliability)}</div> : null}
              <ResultList title="Identity gaps" items={row.identity_gaps} />
              <ResultList title={discovery ? "Candidate source URLs" : "Identity evidence URLs"} items={row.identity_evidence_urls} />
            </li>
          );
        })}</ul>
      ) : <p>{empty}</p>}
    </div>
  );
}

export function PublicResearchResult({ report, stages }: {
  report: Record<string, unknown> | null;
  stages: Record<string, unknown>[];
}) {
  const comparisons = resultRows(report?.comparison);
  const opportunities = resultRows(report?.market_opportunities);
  return (
    <div aria-label="Public research result">
      {report ? (
        <div>
          <h3>Research report</h3>
          {report.result_semantics === "valid_empty" ? <p>No companies were verified in this research run.</p> : null}
          {report.evidence_coverage === "incomplete" ? <p>Some source pages could not be fully observed.</p> : null}
          {comparisons.length ? (
            <ul>{comparisons.map((row, index) => (
              <li key={index}>
                <strong>{resultText(row.company) ?? "Company"}</strong>
                {resultText(row.website) ? <div>{resultText(row.website)}</div> : null}
                {label(row.identity_status) ? <div>Identity {label(row.identity_status)}</div> : null}
                {resultText(row.summary) ? <p>{resultText(row.summary)}</p> : null}
                <ResultList title="Sources" items={row.sources} />
              </li>
            ))}</ul>
          ) : null}
          <ResultList title="Market opportunities" items={opportunities.map((row) => row.title)} />
          <ResultList title="Report evidence gaps" items={report.evidence_gaps} />
        </div>
      ) : <p>No research report was recorded.</p>}
      {stages.map((stage, index) => {
        const discovery = stage.stage === "discovery";
        return (
          <div key={resultText(stage.task_id) ?? index}>
            <h3>{discovery ? "Discovery" : "Public identity verification"}{label(stage.status) ? ` · ${label(stage.status)}` : null}</h3>
            {typeof stage.observed_count === "number" && typeof stage.requested_quantity === "number" ? (
              typeof stage.minimum_verified_quantity === "number"
                ? <p>Verified {stage.observed_count} {stage.observed_count === 1 ? "identity" : "identities"}. Minimum {stage.minimum_verified_quantity}, limit {stage.requested_quantity}.</p>
                : <p>Verifier recorded {stage.observed_count} of {stage.requested_quantity} requested identities.</p>
            ) : null}
            {resultText(stage.research_gap) ? <p>{resultText(stage.research_gap)}</p> : null}
            {discovery ? (
              <>
                {stage.public_search_observed === false && !resultText(stage.research_gap)
                  ? <p>No public search provider response was recorded.</p> : null}
                <p>Discovery records candidate sources. Public identity results appear in verification.</p>
                <ResearchObservations discovery title="Candidates found" rows={stage.candidates} empty="No candidate observations were recorded." />
              </>
            ) : (
              <>
                <ResearchObservations title="Verified candidates" rows={stage.verified_candidates} empty="No candidates were verified." />
                <ResearchObservations title="Rejected or unresolved observations" rows={stage.unverified_observations} empty="No rejections or unresolved observations were recorded." />
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
