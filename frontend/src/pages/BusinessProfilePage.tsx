import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getBusinessProfile } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import {
  BUSINESS_PROFILE_FIELDS,
  STANDALONE_PROCESS_STEPS,
  type BusinessProfileField,
} from "../config/businessProfileFields";
import type { BusinessProfileReadResponse } from "../types";
import {
  listToInput,
  readProfileList,
  readProfileText,
} from "../utils/businessProfile";
import { saveBusinessProfileFacts } from "../utils/saveBusinessProfileFacts";

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

export default function BusinessProfilePage() {
  const { session } = useAuth();
  const [profile, setProfile] = useState<BusinessProfileReadResponse | null>(null);
  const [values, setValues] = useState<FormValues>(() => valuesFromProfile(null));
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<"profile" | "goals" | "knowledge" | "preferences">("profile");

  useEffect(() => {
    if (!session) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    async function load() {
      if (!session) {
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const response = await getBusinessProfile(session);
        if (!cancelled) {
          setProfile(response);
          setValues(valuesFromProfile(response));
        }
      } catch (err) {
        if (!cancelled) {
          setError(err);
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
  }, [session?.tenantId, session?.apiKey, session?.accessToken]);

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
    if (!session) {
      return;
    }

    setSaving(true);
    setError(null);
    setSuccess("");
    try {
      const latest = await saveBusinessProfileFacts(session, values, "business_profile_page");
      setProfile(latest);
      if (latest) {
        setValues(valuesFromProfile(latest));
      }
      setSuccess("Business profile saved. Standalone missions will use these approved facts.");
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  const tabSections: Record<typeof activeTab, BusinessProfileField["section"][]> = {
    profile: ["identity", "contact"],
    goals: ["market"],
    knowledge: ["market", "notes"],
    preferences: ["notes"],
  };

  return (
    <main>
      <PageHeader
        eyebrow="Business memory"
        title="Approved business context"
        lead={`${completeness}% profile ready — facts Ajenda reuses across missions, retrieval, and outreach.`}
      />

      <div className="cc-tabs">
        {(
          [
            ["profile", "Profile"],
            ["goals", "Goals"],
            ["knowledge", "Knowledge"],
            ["preferences", "Preferences"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`cc-tab${activeTab === id ? " active" : ""}`}
            onClick={() => setActiveTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

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
              Plugins like HubSpot, Gmail, and SMTP email are optional. With a complete business profile, Ajenda
              can run missions using internal records, hybrid retrieval, and web research.
            </p>
            <Link to="/setup">Run setup wizard</Link>
            <Link to="/credentials">Manage optional plugins</Link>
          </div>
        </aside>

        <section className="panel standalone-profile-panel">
          <div className="panel-heading-row">
            <h2>Approved business facts</h2>
            {profile?.updated_at ? <small className="muted">Updated {profile.updated_at}</small> : null}
          </div>

          {loading ? <p className="muted">Loading business profile…</p> : null}
          <PageErrorAlert error={error} className="error-banner" />
          {success ? <p className="success-banner">{success}</p> : null}

          <form className="form-grid standalone-profile-form" onSubmit={handleSave}>
            {Array.from(sections.entries())
              .filter(([section]) => tabSections[activeTab].includes(section))
              .map(([section, fields]) => (
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