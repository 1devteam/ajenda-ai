import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { getBusinessProfile, upsertBusinessProfileFact } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import {
  demoValuesFromPlaceholders,
  STANDALONE_WIZARD_STEPS,
  WIZARD_REQUIRED_CATEGORIES,
  wizardFieldsForStep,
  type WizardStepId,
} from "../config/standaloneWizard";
import { BUSINESS_PROFILE_FIELDS, type BusinessProfileField } from "../config/businessProfileFields";
import {
  charterFromPersistedProfile,
  charterToFact,
  DEFAULT_OPERATING_CHARTER,
  NEVER_DO_OPTIONS,
  PERFORM_ACTION_OPTIONS,
  PREPARE_ACTION_OPTIONS,
  applyMayPerformToggle,
  applyNeverDoToggle,
  toggleActionList,
  type OperatingCharter,
} from "../config/operatingCharter";
import type { BusinessProfileReadResponse } from "../types";
import { listToInput, readProfileList, readProfileText } from "../utils/businessProfile";
import { saveBusinessProfileFacts } from "../utils/saveBusinessProfileFacts";
import { useOnboardingState } from "../hooks/useOnboardingState";
import ConnectorGrid from "../components/connections/ConnectorGrid";

type FormValues = Record<string, string>;

function valuesFromProfile(profile: BusinessProfileReadResponse | null): FormValues {
  const facts = profile?.approved_facts ?? {};
  const values: FormValues = {};
  for (const field of BUSINESS_PROFILE_FIELDS) {
    if (field.kind === "list") {
      values[field.category] = listToInput(readProfileList(facts, field.category));
    } else {
      values[field.category] = readProfileText(facts, field.category, field.fallbackKeys);
    }
  }
  return values;
}

function charterFromResponse(profile: BusinessProfileReadResponse | null): OperatingCharter {
  const persisted = profile?.operating_charter;
  if (persisted?.status === "active" && persisted.charter) {
    const parsed = charterFromPersistedProfile({ operating_charter: persisted.charter });
    if (parsed) {
      return parsed;
    }
  }
  return { ...DEFAULT_OPERATING_CHARTER, revision: persisted?.revision ?? 0 };
}

function stepIndex(stepId: WizardStepId): number {
  return STANDALONE_WIZARD_STEPS.findIndex((step) => step.id === stepId);
}

function renderField(
  field: BusinessProfileField,
  values: FormValues,
  onChange: (category: string, value: string) => void,
) {
  const value = values[field.category] ?? "";
  const isWide = field.kind === "textarea" || field.kind === "list";
  return (
    <label key={field.category} className={isWide ? "span-2" : undefined}>
      <span>{field.label}</span>
      <small className="muted">{field.description}</small>
      {field.kind === "textarea" || field.kind === "list" ? (
        <textarea
          className="mission-textarea"
          value={value}
          placeholder={field.placeholder}
          onChange={(event) => onChange(field.category, event.target.value)}
        />
      ) : (
        <input
          type="text"
          value={value}
          placeholder={field.placeholder}
          onChange={(event) => onChange(field.category, event.target.value)}
        />
      )}
    </label>
  );
}

export default function StandaloneWizardPage() {
  const navigate = useNavigate();
  const { session } = useAuth();
  const tenantId = session?.tenantId ?? "";
  const onboarding = useOnboardingState(session);

  const [stepId, setStepId] = useState<WizardStepId>("welcome");
  const [values, setValues] = useState<FormValues>({});
  const [profile, setProfile] = useState<BusinessProfileReadResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [charterSaved, setCharterSaved] = useState(false);
  const [charter, setCharter] = useState<OperatingCharter>(DEFAULT_OPERATING_CHARTER);
  const [error, setError] = useState<unknown>(null);

  const currentStep = STANDALONE_WIZARD_STEPS[stepIndex(stepId)] ?? STANDALONE_WIZARD_STEPS[0];
  const currentIndex = stepIndex(stepId);

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
          setCharter(charterFromResponse(response));
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

  function updateValue(category: string, next: string) {
    setValues((current) => ({ ...current, [category]: next }));
    setError(null);
  }

  function applyDemoPreset() {
    setValues(demoValuesFromPlaceholders());
    setError(null);
  }

  function validateStep(step: WizardStepId): string | null {
    if (step === "profile") {
      for (const category of WIZARD_REQUIRED_CATEGORIES) {
        if (!(values[category] ?? "").trim()) {
          return "Business name and contact email are required before continuing.";
        }
      }
    }
    if (step === "market") {
      if (!(values.target_customers ?? "").trim() && !(values.products_services ?? "").trim()) {
        return "Add at least target customers or products & services.";
      }
    }
    return null;
  }

  async function persistProfile() {
    if (!session) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const latest = await saveBusinessProfileFacts(session, values, "standalone_wizard");
      setProfile(latest);
      setSaved(true);
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setSaving(false);
    }
  }

  async function persistCharter() {
    if (!session) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const latest = await upsertBusinessProfileFact(session, "operating_charter", {
        approved_fact: charterToFact(charter),
        provenance_metadata: { source: "standalone_wizard" },
        expected_charter_revision: profile?.operating_charter.revision,
      });
      setProfile(latest);
      setCharter(charterFromResponse(latest));
      setCharterSaved(true);
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setSaving(false);
    }
  }

  async function goNext() {
    const validationError = validateStep(stepId);
    if (validationError) {
      setError(validationError);
      return;
    }

    if (stepId === "notes" && !saved) {
      try {
        await persistProfile();
      } catch {
        return;
      }
    }

    if (stepId === "charter" && !charterSaved) {
      try {
        await persistCharter();
      } catch {
        return;
      }
    }

    const next = STANDALONE_WIZARD_STEPS[currentIndex + 1];
    if (next) {
      setStepId(next.id);
      setError(null);
      return;
    }
    finishWizard();
  }

  function goBack() {
    const previous = STANDALONE_WIZARD_STEPS[currentIndex - 1];
    if (previous) {
      setStepId(previous.id);
      setError(null);
    }
  }

  async function finishWizard() {
    try {
      await onboarding.complete();
      navigate("/missions");
    } catch (err) {
      setError(err);
    }
  }

  const businessName = (values.business_name ?? "").trim() || "your business";

  return (
    <main className="page-shell narrow">
      <section className="hero compact-hero">
        <div>
          <p className="eyebrow">Setup</p>
            <h1>Set up Ajenda for your business</h1>
          <p>
            Add your company context, operating preferences, and optional business connections. You can edit everything later.
          </p>
        </div>
        {onboarding.state?.completed_at ? (
          <div className="status-card">
            <span className="status-dot ok" />
            <div>
              <strong>Completed</strong>
              <small>{onboarding.state.completed_at}</small>
            </div>
          </div>
        ) : null}
      </section>

      <section className="panel wizard-shell">
        <nav className="wizard-stepper" aria-label="Setup progress">
          {STANDALONE_WIZARD_STEPS.map((step, index) => {
            const state =
              index < currentIndex ? "done" : index === currentIndex ? "active" : "upcoming";
            return (
              <button
                key={step.id}
                type="button"
                className={`wizard-step ${state}`}
                onClick={() => index <= currentIndex && setStepId(step.id)}
                disabled={index > currentIndex}
              >
                <span className="wizard-step-index">{index + 1}</span>
                <span className="wizard-step-title">{step.title}</span>
              </button>
            );
          })}
        </nav>

        <div className="wizard-body">
          <header className="wizard-panel-header">
            <h2>{currentStep.title}</h2>
            <p className="muted">{currentStep.detail}</p>
          </header>

          {loading ? <p className="muted">Loading profile…</p> : null}
          <PageErrorAlert error={error} className="error-banner" />
          {saved && stepId !== "welcome" ? (
            <p className="success-banner">
              Profile saved. Internal records sync to <code>profile-account-primary</code> and{" "}
              <code>profile-contact-primary</code> for hybrid retrieval.
            </p>
          ) : null}

          {stepId === "welcome" ? (
            <div className="wizard-welcome">
              <p>
                Tell Ajenda about your company so it can prepare relevant missions. Start with sample values or replace them with your own.
              </p>
              <div className="action-row">
                <button type="button" className="primary-button" onClick={applyDemoPreset}>
                  Use Ajenda AI demo
                </button>
                <Link className="ghost-link" to="/business">
                  Open full business info page
                </Link>
              </div>
            </div>
          ) : null}

          {wizardFieldsForStep(currentStep).length > 0 ? (
            <div className="standalone-field-grid wizard-field-grid">
              {wizardFieldsForStep(currentStep).map((field) => renderField(field, values, updateValue))}
            </div>
          ) : null}

          {stepId === "charter" ? (
            <div className="standalone-field-grid wizard-field-grid charter-grid">
              {profile?.operating_charter.status !== "active" ? (
                <p className="error-banner span-2" role="status">
                  {profile?.operating_charter.status === "invalid"
                    ? `Saved operating charter is invalid: ${profile.operating_charter.error_message ?? "correct it before launch."}`
                    : "No operating charter has been saved for this tenant. These selections are a draft until saved."}
                </p>
              ) : (
                <p className="muted span-2" role="status">
                  Active charter revision {profile.operating_charter.revision}. Ajenda enforces this saved revision.
                </p>
              )}
              <fieldset className="span-2" disabled={loading || saving}>
                <legend>May prepare (read / draft)</legend>
                <div className="checkbox-grid">
                  {PREPARE_ACTION_OPTIONS.map((option) => (
                    <label key={option.action} className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={charter.may_prepare.includes(option.action)}
                        onChange={(event) =>
                          setCharter((current) => ({
                            ...current,
                            may_prepare: toggleActionList(
                              current.may_prepare,
                              option.action,
                              event.target.checked,
                            ),
                          }))
                        }
                      />
                      {option.label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset className="span-2" disabled={loading || saving}>
                <legend>May perform (internal / external writes)</legend>
                <div className="checkbox-grid">
                  {PERFORM_ACTION_OPTIONS.map((option) => (
                    <label key={option.action} className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={charter.may_perform.includes(option.action)}
                        onChange={(event) =>
                          setCharter((current) =>
                            applyMayPerformToggle(current, option.action, event.target.checked),
                          )
                        }
                      />
                      {option.label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset className="span-2" disabled={loading || saving}>
                <legend>Never do</legend>
                <div className="checkbox-grid">
                  {NEVER_DO_OPTIONS.map((option) => (
                    <label key={option.action} className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={charter.never_do.includes(option.action)}
                        onChange={(event) =>
                          setCharter((current) =>
                            applyNeverDoToggle(current, option.action, event.target.checked),
                          )
                        }
                      />
                      {option.label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <label>
                <span>Approval mode</span>
                <select
                  value={charter.approval_mode}
                  disabled={loading || saving}
                  onChange={(event) =>
                    setCharter((current) => ({
                      ...current,
                      approval_mode: event.target.value as OperatingCharter["approval_mode"],
                    }))
                  }
                >
                  <option value="notify_before_external">Notify before external perform</option>
                  <option value="always_notify">Always notify operator</option>
                  <option value="none">No extra notifications</option>
                </select>
              </label>
              <label>
                <span>Escalation email</span>
                <input
                  type="email"
                  disabled={loading || saving}
                  value={charter.escalation_email ?? ""}
                  placeholder="ops@yourcompany.com"
                  onChange={(event) =>
                    setCharter((current) => ({ ...current, escalation_email: event.target.value }))
                  }
                />
              </label>
              <label>
                <span>Escalation phone</span>
                <input
                  type="text"
                  disabled={loading || saving}
                  value={charter.escalation_phone ?? ""}
                  placeholder="+1 512 555 0100"
                  onChange={(event) =>
                    setCharter((current) => ({ ...current, escalation_phone: event.target.value }))
                  }
                />
              </label>
            </div>
          ) : null}

          {stepId === "brain" ? (
            <div className="callout wizard-callout">
              <p>
                <strong>{businessName}</strong> is ready for review. Your company context and operating preferences are saved to this workspace.
              </p>
              <ul className="wizard-checklist">
                <li>Company information is saved</li>
                <li>Operating preferences are saved</li>
                <li>Connections are optional</li>
              </ul>
            </div>
          ) : null}

          {stepId === "plugins" ? (
            <div className="callout wizard-callout">
              <p>
                Connect only the business tools you want Ajenda to use. Each Google connection is separate, and you can continue without connecting anything.
              </p>
              {session ? <ConnectorGrid session={session} onboarding={onboarding.state} /> : null}
            </div>
          ) : null}

          <footer className="wizard-actions">
            <button type="button" className="ghost-button" onClick={goBack} disabled={currentIndex === 0 || saving}>
              Back
            </button>
            {stepId === "plugins" ? (
              <button type="button" className="primary-button" onClick={() => void finishWizard()} disabled={saving}>
                Finish setup
              </button>
            ) : (
              <button
                type="button"
                className="primary-button"
                onClick={() => void goNext()}
                disabled={saving || loading}
              >
                {saving
                  ? "Saving…"
                  : stepId === "notes" && !saved
                    ? "Save & continue"
                    : stepId === "charter" && !charterSaved
                      ? "Save charter & continue"
                      : "Continue"}
              </button>
            )}
          </footer>

          {profile?.updated_at ? (
            <small className="muted wizard-footnote">
              Last profile update: {profile.updated_at}. Edit anytime on{" "}
              <Link to="/business">Business info</Link>.
            </small>
          ) : null}
        </div>
      </section>
    </main>
  );
}
