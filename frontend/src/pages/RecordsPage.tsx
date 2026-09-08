import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import {
  getCrmPipeline,
  getCrmRelationships,
  getCrmTimeline,
  listCrmRecords,
  listCrmSuggestions,
  upsertCrmRecord,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import type {
  CrmPipelineResponse,
  CrmRecordItem,
  CrmRelationshipResponse,
  CrmSuggestion,
  CrmTimelineResponse,
} from "../types";


type CrmTab = "contact" | "account" | "opportunity" | "activity" | "task";

const TABS: Array<{ id: CrmTab; label: string }> = [
  { id: "contact", label: "Contacts" },
  { id: "account", label: "Companies" },
  { id: "opportunity", label: "Deals" },
  { id: "activity", label: "Activities" },
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
  const [page, setPage] = useState(0);
  const [records, setRecords] = useState<CrmRecordItem[]>([]);
  const [pipeline, setPipeline] = useState<CrmPipelineResponse | null>(null);
  const [suggestions, setSuggestions] = useState<CrmSuggestion[]>([]);
  const [selected, setSelected] = useState<CrmRecordItem | null>(null);
  const [timeline, setTimeline] = useState<CrmTimelineResponse | null>(null);
  const [relationships, setRelationships] = useState<CrmRelationshipResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editFields, setEditFields] = useState({ name: "", email: "", stage: "", ownerId: "", tags: "" });
  const [noteBody, setNoteBody] = useState("");
  const [followUpTitle, setFollowUpTitle] = useState("");
  const [followUpDueAt, setFollowUpDueAt] = useState("");
  const [actionSaving, setActionSaving] = useState(false);

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
          offset: page * 30,
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
  }, [session, tab, query, stageFilter, page]);

  useEffect(() => {
    void loadRecords();
  }, [loadRecords]);

  useEffect(() => {
    if (!session || !selected) {
      setTimeline(null);
      setRelationships(null);
      return;
    }
    setEditing(false);
    setEditFields({
      name: String(selected.data.name || selected.data.company || ""),
      email: String(selected.data.email || ""),
      stage: String(selected.data.stage || ""),
      ownerId: String(selected.data.owner_id || ""),
      tags: Array.isArray(selected.data.tags) ? selected.data.tags.map(String).join(", ") : "",
    });
    let cancelled = false;
    void (async () => {
      try {
        const [response, relationshipResponse] = await Promise.all([
          getCrmTimeline(session, selected.record_type, selected.id),
          getCrmRelationships(session, selected.record_type, selected.id),
        ]);
        if (!cancelled) {
          setTimeline(response);
          setRelationships(relationshipResponse);
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

  const saveSelected = useCallback(async () => {
    if (!session || !selected) return;
    setSaving(true);
    setError(null);
    try {
      const data = { ...selected.data };
      if (editFields.name.trim()) data.name = editFields.name.trim();
      else delete data.name;
      if (selected.record_type === "contact") {
        if (editFields.email.trim()) data.email = editFields.email.trim();
        else delete data.email;
      }
      if (selected.record_type === "opportunity") {
        if (editFields.stage.trim()) data.stage = editFields.stage.trim();
        else delete data.stage;
      }
      if (editFields.ownerId.trim()) data.owner_id = editFields.ownerId.trim();
      else delete data.owner_id;
      data.tags = editFields.tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean);
      const saved = await upsertCrmRecord(session, selected.record_type, selected.id, { data });
      setSelected(saved);
      setEditing(false);
      await loadRecords();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }, [editFields, loadRecords, selected, session]);

  const createFollowUp = useCallback(async () => {
    if (!session || !selected || !followUpTitle.trim()) return;
    setActionSaving(true);
    setError(null);
    try {
      await upsertCrmRecord(session, "task", crypto.randomUUID(), {
        data: {
          title: followUpTitle.trim(),
          status: "open",
          due_at: followUpDueAt ? new Date(followUpDueAt).toISOString() : undefined,
          related_type: selected.record_type,
          related_id: selected.id,
          source: "crm.operator",
        },
      });
      setFollowUpTitle("");
      setFollowUpDueAt("");
      const response = await getCrmTimeline(session, selected.record_type, selected.id);
      setTimeline(response);
    } catch (err) {
      setError(err);
    } finally {
      setActionSaving(false);
    }
  }, [followUpDueAt, followUpTitle, selected, session]);

  const createNote = useCallback(async () => {
    if (!session || !selected || !noteBody.trim()) return;
    setActionSaving(true);
    setError(null);
    try {
      await upsertCrmRecord(session, "activity", crypto.randomUUID(), {
        data: {
          activity_type: "note",
          subject: "Operator note",
          body: noteBody.trim(),
          related_type: selected.record_type,
          related_id: selected.id,
          source: "crm.operator",
        },
      });
      setNoteBody("");
      const response = await getCrmTimeline(session, selected.record_type, selected.id);
      setTimeline(response);
    } catch (err) {
      setError(err);
    } finally {
      setActionSaving(false);
    }
  }, [noteBody, selected, session]);

  const pipelineTotal = useMemo(
    () => pipeline?.stages.reduce((sum, stage) => sum + stage.count, 0) ?? 0,
    [pipeline],
  );

  return (
    <main>
      <PageHeader
        eyebrow="Results / evidence"
        title="Outcomes and governed records"
        lead="Contacts, deals, timelines, and evidence Ajenda produced while executing your missions."
        actions={
          <Link className="ghost-link" to="/missions">
            Launch mission
          </Link>
        }
      />

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

      <div className="inline-controls">
        <button type="button" className="button secondary" disabled={page === 0 || loading} onClick={() => setPage((value) => value - 1)}>
          Previous
        </button>
        <span className="muted">Page {page + 1}{records.length === 30 ? " · more available" : ""}</span>
        <button type="button" className="button secondary" disabled={loading || records.length < 30} onClick={() => setPage((value) => value + 1)}>
          Next
        </button>
      </div>

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
                <div className="inline-controls">
                  <button type="button" className="button secondary" onClick={() => setEditing((value) => !value)}>
                    {editing ? "Cancel edit" : "Edit record"}
                  </button>
                  {editing ? (
                    <button type="button" className="button" disabled={saving} onClick={() => void saveSelected()}>
                      {saving ? "Saving…" : "Save record"}
                    </button>
                  ) : null}
                </div>
                {editing ? (
                  <div className="form-grid">
                    <label>
                      Name / company
                      <input
                        value={editFields.name}
                        onChange={(event) => setEditFields((fields) => ({ ...fields, name: event.target.value }))}
                      />
                    </label>
                    {selected.record_type === "contact" ? (
                      <label>
                        Email
                        <input
                          type="email"
                          value={editFields.email}
                          onChange={(event) => setEditFields((fields) => ({ ...fields, email: event.target.value }))}
                        />
                      </label>
                    ) : null}
                    {selected.record_type === "opportunity" ? (
                      <label>
                        Stage
                        <input
                          value={editFields.stage}
                          onChange={(event) => setEditFields((fields) => ({ ...fields, stage: event.target.value }))}
                        />
                      </label>
                    ) : null}
                    <label>
                      Owner ID
                      <input
                        value={editFields.ownerId}
                        onChange={(event) => setEditFields((fields) => ({ ...fields, ownerId: event.target.value }))}
                      />
                    </label>
                    <label>
                      Tags
                      <input
                        value={editFields.tags}
                        placeholder="comma, separated"
                        onChange={(event) => setEditFields((fields) => ({ ...fields, tags: event.target.value }))}
                      />
                    </label>
                  </div>
                ) : null}
                <div className="card-grid two-up">
                  <section className="nested-panel">
                    <h3>Add note</h3>
                    <textarea
                      value={noteBody}
                      placeholder="Capture context for the next operator"
                      onChange={(event) => setNoteBody(event.target.value)}
                    />
                    <button
                      type="button"
                      className="button"
                      disabled={actionSaving || !noteBody.trim()}
                      onClick={() => void createNote()}
                    >
                      {actionSaving ? "Saving…" : "Save note"}
                    </button>
                  </section>
                  <section className="nested-panel">
                    <h3>Create follow-up</h3>
                    <input
                      value={followUpTitle}
                      placeholder="Follow-up task"
                      onChange={(event) => setFollowUpTitle(event.target.value)}
                    />
                    <input
                      type="datetime-local"
                      value={followUpDueAt}
                      onChange={(event) => setFollowUpDueAt(event.target.value)}
                    />
                    <button
                      type="button"
                      className="button"
                      disabled={actionSaving || !followUpTitle.trim()}
                      onClick={() => void createFollowUp()}
                    >
                      {actionSaving ? "Saving…" : "Create task"}
                    </button>
                  </section>
                </div>
                <pre className="code-block">{JSON.stringify(selected.data, null, 2)}</pre>
                <h3>Relationships</h3>
                {relationships && relationships.items.length > 0 ? (
                  <ul className="timeline-list">
                    {relationships.items.map((item, index) => {
                      const outgoing = item.from_type === selected.record_type && item.from_id === selected.id;
                      return (
                        <li key={String(item.id || index)}>
                          <strong>{String(item.relationship_type || "related")}</strong>
                          <span>
                            {outgoing ? "→" : "←"} {String(outgoing ? item.to_type : item.from_type)} · {String(outgoing ? item.to_id : item.from_id)}
                          </span>
                          <span className="muted">{String(item.source || "ajenda")}</span>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="muted">No linked records yet.</p>
                )}
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
