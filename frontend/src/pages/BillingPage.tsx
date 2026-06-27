import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { createCheckout, createPortal, getAccountBilling } from "../api/client";
import { loadSession, sessionToRuntimeConfig } from "../auth/session";
import type { AccountBillingResponse } from "../types";
import { failureText } from "../utils/errors";

export default function BillingPage() {
  const session = loadSession();
  const location = useLocation();
  const [billing, setBilling] = useState<AccountBillingResponse | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (location.pathname.endsWith("/success")) {
      setNotice("Checkout completed. Stripe webhook may take a moment to sync your plan.");
    } else if (location.pathname.endsWith("/cancel")) {
      setNotice("Checkout canceled. You can try again when ready.");
    }
  }, [location.pathname]);

  useEffect(() => {
    if (!session) {
      return;
    }

    let cancelled = false;

    async function load() {
      if (!session) {
        return;
      }
      try {
        const response = await getAccountBilling(session);
        if (!cancelled) {
          setBilling(response);
        }
      } catch (err) {
        if (!cancelled) {
          setError(failureText(err));
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [session?.tenantId, session?.apiKey]);

  async function runAction<T>(label: string, callback: () => Promise<T>): Promise<T | null> {
    if (!session) {
      return null;
    }
    setLoading(label);
    setError("");
    try {
      return await callback();
    } catch (err) {
      setError(failureText(err));
      return null;
    } finally {
      setLoading(null);
    }
  }

  async function handleCheckout() {
    if (!session) {
      return;
    }
    const response = await runAction("Creating checkout", () =>
      createCheckout(sessionToRuntimeConfig(session), "pro"),
    );
    if (response) {
      window.location.href = response.checkout_url;
    }
  }

  async function handlePortal() {
    if (!session) {
      return;
    }
    const response = await runAction("Opening portal", () => createPortal(sessionToRuntimeConfig(session)));
    if (response) {
      window.location.href = response.portal_url;
    }
  }

  const currentPlan = billing?.plan ?? session?.plan ?? "free";
  const onPro = currentPlan === "pro" || currentPlan === "enterprise";

  return (
    <main className="page-shell">
      <section className="hero compact-hero">
        <div>
          <p className="eyebrow">Billing</p>
          <h1>Subscription &amp; invoices</h1>
          <p>
            Self-serve checkout upgrades to <strong>Pro</strong>, which unlocks AI task execution and GTM
            abilities. Starter is webhook-only and is assigned by sales or admin — not sold here.
          </p>
        </div>
        <div className="status-card">
          <span className={`status-dot ${billing?.has_billing_account ? "ok" : ""}`} />
          <div>
            <strong>{billing?.has_billing_account ? "Stripe linked" : "No Stripe customer"}</strong>
            <small>Current plan {currentPlan}</small>
          </div>
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <h2>Upgrade to Pro</h2>
          <ul className="muted">
            <li>Ability runtime — queue and run AI tasks</li>
            <li>GTM actions on pro/enterprise plans</li>
            <li>Higher mission and API quotas than free</li>
          </ul>
          <button type="button" onClick={() => void handleCheckout()} disabled={loading !== null || onPro}>
            {onPro ? "Already on Pro or higher" : "Start Pro checkout"}
          </button>
          <p className="muted">
            Requires an operational API key. If you just verified email, finish{" "}
            <Link to="/promote">account activation</Link> first.
          </p>
        </div>

        <div className="panel">
          <h2>Manage subscription</h2>
          <p className="muted">
            {billing?.has_billing_account
              ? "Open the Stripe customer portal to update payment method or cancel."
              : "Complete a checkout first to create your Stripe customer record."}
          </p>
          <button
            type="button"
            onClick={() => void handlePortal()}
            disabled={loading !== null || !billing?.has_billing_account}
          >
            Open billing portal
          </button>
        </div>
      </section>

      {onPro ? (
        <section className="notice-banner success-panel">
          <strong>Plan active: {currentPlan}</strong>
          <span>Runtime abilities and higher quotas are enabled for this workspace.</span>
        </section>
      ) : null}

      {notice ? <div className="notice-banner">{notice}</div> : null}
      {loading ? <div className="toast">Working: {loading}</div> : null}
      {error ? (
        <div className="inline-error">
          <pre>{error}</pre>
        </div>
      ) : null}
    </main>
  );
}