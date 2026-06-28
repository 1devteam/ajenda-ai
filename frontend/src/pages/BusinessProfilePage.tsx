import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getBusinessProfile, upsertBusinessProfileFact } from "../api/client";
import { loadSession, sessionToRuntimeConfig } from "../auth/session";
import {
  BUSINESS_PROFILE_FIELDS,
  STANDALONE_PROCESS_STEPS,
  type BusinessProfileField,
} from "../config/businessProfileFields";
import type { BusinessProfileReadResponse } from "../types";
import {
  listFact,
  listFromInput,
  listToInput,
  readProfileList,
  readProfileText,
  textFact,
} from "../utils/businessProfile";
import { failureText } from "../utils/errors";

type FormValues = Record<string, string>;

const SECTION_LABELS: Record<BusinessProfileField["section"], string> = {
  identity: "Business identity",
  contact: "Contact & location",
  market: "Market focus",
  notes: "Operating guidance",
};

function valuesFromProfile(profile: BusinessProfileReadResponse | null): FormValues {
  const facts = profile?.approved_facts ?? {};
  const values: FormValues = {};
  for (const field of BUSINESS_PROFILE_FIELDS) {
    if (field.kind === "list") {
      values[field.category] = listToInput(readProfileList(facts, field.category));
      continue;
    }
    values[field.category] = readProfileText(facts, field.category, field.fallbackKeys);
  }
  return values;
}

function buildFactPayload(field: BusinessProfileField, raw: string): Record<string, unknown> {
  if (field.kind === "list") {
    return listFact(listFromInput(raw));
  }
  return textFact(raw);
}

export default function BusinessProfilePage() {
  const session = loadSession();
  const config = useMemo(
    () => (session ? sessionToRuntimeConfig(session) : null),
    [session?.tenantId, session?.apiKey, session?.accessToken],
  );
  const [profile, setProfile] = useState<BusinessProfileReadResponse | null>(null);
  const [values, setValues] = useState<FormValues>(() => valuesFromProfile(null));
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!config) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    async function load() {
      if (!config) {
        return;
      }
      setLoading(true);
      setError("");
      try {
        const response = await getBusinessProfile(config);
        if (!cancelled) {
          setProfile(response);
          setValues(valuesFromProfile(response));
        }
      } catch (err) {
        if (!cancelled) {
          setError(failureText(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [config]);

  const sections = useMemo(() => {
    const grouped = new Map<BusinessProfileField["section"], BusinessProfileField[]>();
    for (const field of BUSINESS_PROFILE_FIELDS) {
      const current = grouped.get(field.section) ?? [];
      current.push(field);
      grouped.set(field.section, current);
    }
    return grouped;
  }, []);

  const completeness = useMemo(() => {
    const required = ["business_name", "contact_email", "target_customers", "products_services"];
    const filled = required.filter((category) => (values[category] ?? "").trim().length > 0);
    return Math.round((filled.length / required.length) * 100);
  }, [values]);

  function updateValue(category: string, next: string) {
    setValues((current) => ({ ...current, [category]: next }));
    setSuccess("");
  }

  async function handleSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config) {
      return;
    }

    setSaving(true);
    setError("");
    setSuccess("");
    try {
      let latest = profile;
      for (const field of BUSINESS_PROFILE_FIELDS) {
        const raw = values[field.category] ?? "";
        if (!raw.trim()) {
          continue;
        }
        latest = await upsertBusinessProfileFact(config, field.category, {
          approved_fact: buildFactPayload(field, raw),
          provenance_metadata: { source: "business_profile_page" },
        });
      }
      setProfile(latest);
      if (latest) {
        setValues(valuesFromProfile(latest));
      }
      setSuccess("Business profile saved. Standalone missions will use these approved facts.");
    } catch (err) {
      setError(failureText(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="page-shell">
      <section className="hero compact-hero">
        <div>
          <p className="eyebrow">Standalone process</p>
          <h1>Business information</h1>
          <p>
            Configure the Ajenda central brain with your business name, contacts, and market context.
            These approved facts prefill mission briefs and internal standalone workflows without
            requiring external CRM plugins.
          </p>
        </div>
        <div className="status-card">
          <span className={`status-dot ${completeness >= 75 ? "ok" : ""}`} />
          <div>
            <strong>{completeness}% ready</strong>
            <small>{profile?.status === "missing" ? "No profile saved yet" : "Approved facts on file"}</small>
          </div>
        </div>
      </section>

      <section className="standalone-info-layout">
        <aside className="panel standalone-process-panel">
          <div className="panel-heading-row">
            <h2>How standalone works</h2>
          </div>
          <ol className="standalone-process-list">
            {STANDALONE_PROCESS_STEPS.map((step) => (
              <li key={step.title}>
                <strong>{step.title}</strong>
                <span>{step.detail}</span>
              </li>
            ))}
          </ol>
          <div className="callout standalone-callout">
            <p>
              Plugins like HubSpot and Gmail are optional. With a complete business profile, Ajenda
              can run missions using internal records, hybrid retrieval, and web research.
            </p>
            <Link to="/credentials">Manage optional plugins</Link>
          </div>
        </aside>

        <section className="panel standalone-profile-panel">
          <div className="panel-heading-row">
            <h2>Approved business facts</h2>
            {profile?.updated_at ? <small className="muted">Updated {profile.updated_at}</small> : null}
          </div>

          {loading ? <p className="muted">Loading business profile…</p> : null}
          {error ? <p className="error-banner">{error}</p> : null}
          {success ? <p className="success-banner">{success}</p> : null}

          <form className="form-grid standalone-profile-form" onSubmit={handleSave}>
            {Array.from(sections.entries()).map(([section, fields]) => (
              <fieldset key={section} className="standalone-fieldset">
                <legend>{SECTION_LABELS[section]}</legend>
                <div className="standalone-field-grid">
                  {fields.map((field) => (
                    <label key={field.category} className={field.kind === "textarea" ? "span-2" : undefined}>
                      <span>{field.label}</span>
                      <small className="muted">{field.description}</small>
                      {field.kind === "textarea" ? (
                        <textarea
                          className="mission-textarea"
                          value={values[field.category] ?? ""}
                          placeholder={field.placeholder}
                          onChange={(event) => updateValue(field.category, event.target.value)}
                        />
                      ) : (
                        <input
                          type="text"
                          value={values[field.category] ?? ""}
                          placeholder={field.placeholder}
                          onChange={(event) => updateValue(field.category, event.target.value)}
                        />
                      )}
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}

            <div className="action-row">
              <button type="submit" disabled={saving || loading}>
                {saving ? "Saving…" : "Save business profile"}
              </button>
              <small className="muted">
                Facts are tenant-owned and audited. They do not enqueue missions by themselves.
              </small>
            </div>
          </form>
        </section>
      </section>
    </main>
  );
}