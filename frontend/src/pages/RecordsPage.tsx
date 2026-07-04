import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  getCrmPipeline,
  getCrmTimeline,
  listCrmRecords,
  listCrmSuggestions,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import type {
  CrmPipelineResponse,
  CrmRecordItem,
  CrmSuggestion,
  CrmTimelineResponse,
} from "../types";


type CrmTab = "contact" | "account" | "opportunity" | "task";

const TABS: Array<{ id: CrmTab; label: string }> = [
  { id: "contact", label: "Contacts" },
  { id: "account", label: "Companies" },
  { id: "opportunity", label: "Deals" },
  { id: "task", label: "Tasks" },
];

function recordTitle(item: CrmRecordItem): string {
  const data = item.data;
  if (item.record_type === "contact") {
    return String(data.name || data.email || item.id);
  }
  if (item.record_type === "account") {
    return String(data.name || data.domain || item.id);
  }
  if (item.record_type === "opportunity") {
    return String(data.name || item.id);
  }
  return String(data.title || data.subject || item.id);
}

function recordMeta(item: CrmRecordItem): string {
  const data = item.data;
  if (item.record_type === "contact") {
    return String(data.email || data.account_id || "—");
  }
  if (item.record_type === "account") {
    return String(data.domain || data.industry || "—");
  }
  if (item.record_type === "opportunity") {
    return String(data.stage || "—");
  }
  return String(data.status || data.due_at || "—");
}

export default function RecordsPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<CrmTab>("contact");
  const [query, setQuery] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  const [records, setRecords] = useState<CrmRecordItem[]>([]);
  const [pipeline, setPipeline] = useState<CrmPipelineResponse | null>(null);
  const [suggestions, setSuggestions] = useState<CrmSuggestion[]>([]);
  const [selected, setSelected] = useState<CrmRecordItem | null>(null);
  const [timeline, setTimeline] = useState<CrmTimelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const loadRecords = useCallback(async () => {
    if (!session) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [recordResponse, pipelineResponse, suggestionResponse] = await Promise.all([
        listCrmRecords(session, {
          recordType: tab,
          query: query.trim() || undefined,
          stage: tab === "opportunity" && stageFilter ? stageFilter : undefined,
          limit: 30,
        }),
        getCrmPipeline(session),
        listCrmSuggestions(session),
      ]);
      setRecords(recordResponse.items);
      setPipeline(pipelineResponse);
      setSuggestions(suggestionResponse.items);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [session, tab, query, stageFilter]);

  useEffect(() => {
    void loadRecords();
  }, [loadRecords]);

  useEffect(() => {
    if (!session || !selected) {
      setTimeline(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const response = await getCrmTimeline(session, selected.record_type, selected.id);
        if (!cancelled) {
          setTimeline(response);
        }
      } catch (err) {
        if (!cancelled) {
          setTimeline(null);
          setError(err);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session, selected]);

  const pipelineTotal = useMemo(
    () => pipeline?.stages.reduce((sum, stage) => sum + stage.count, 0) ?? 0,
    [pipeline],
  );

  return (
    <main className="page-shell">
      <header className="page-header">
        <div>
          <h1>Records</h1>
          <p className="page-lead">
            Ajenda light CRM — contacts, companies, deals, and mission-driven activity timelines.
          </p>
        </div>
        <Link className="button secondary" to="/tasks">
          Run missions
        </Link>
      </header>

      <PageErrorAlert error={error} />

      <section className="panel">
        <h2>Pipeline</h2>
        <p className="muted">{pipelineTotal} open deals across governed internal records.</p>
        <div className="card-grid two-up">
          {(pipeline?.stages ?? []).map((stage) => (
            <button
              key={stage.stage}
              type="button"
              className="proof-card"
              onClick={() => {
                setTab("opportunity");
                setStageFilter(stage.stage);
              }}
            >
              <strong>{stage.stage}</strong>
              <span>{stage.count} deal(s)</span>
            </button>
          ))}
        </div>
      </section>

      {suggestions.length > 0 ? (
        <section className="panel">
          <h2>Suggested missions</h2>
          <div className="card-grid two-up">
            {suggestions.map((item) => (
              <div className="proof-card" key={item.suggestion_id}>
                <strong>{item.title}</strong>
                <span>{item.description}</span>
                <span className="muted">Action: {item.mission_action}</span>
                <Link className="button secondary" to="/tasks">
                  Open Tasks
                </Link>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="inline-controls">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? "button" : "button secondary"}
              onClick={() => {
                setTab(item.id);
                setStageFilter("");
                setSelected(null);
              }}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="inline-controls">
          <input
            aria-label="Search records"
            placeholder="Search records"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {tab === "opportunity" ? (
            <input
              aria-label="Filter by stage"
              placeholder="Filter stage (e.g. outreach)"
              value={stageFilter}
              onChange={(event) => setStageFilter(event.target.value)}
            />
          ) : null}
          <button type="button" className="button secondary" onClick={() => void loadRecords()}>
            Refresh
          </button>
        </div>

        <div className="records-layout">
          <div className="records-list">
            {loading ? <p>Loading records…</p> : null}
            {!loading && records.length === 0 ? <p className="muted">No records found.</p> : null}
            {records.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`proof-card ${selected?.id === item.id ? "selected" : ""}`}
                onClick={() => setSelected(item)}
              >
                <strong>{recordTitle(item)}</strong>
                <span>{recordMeta(item)}</span>
              </button>
            ))}
          </div>

          <div className="records-detail panel">
            {selected ? (
              <>
                <h2>{recordTitle(selected)}</h2>
                <p className="muted">
                  {selected.record_type} · {selected.id}
                </p>
                <pre className="code-block">{JSON.stringify(selected.data, null, 2)}</pre>
                <h3>Timeline</h3>
                {timeline && timeline.items.length > 0 ? (
                  <ul className="timeline-list">
                    {timeline.items.map((item, index) => (
                      <li key={String(item.id || index)}>
                        <strong>{String(item.type || "activity")}</strong>
                        <span>{String(item.subject || "")}</span>
                        <span className="muted">{String(item.occurred_at || "")}</span>
                        <p>{String(item.body || "")}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">No activities yet — run a mission or approve a draft to populate timeline.</p>
                )}
              </>
            ) : (
              <p className="muted">Select a record to view details and timeline.</p>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}