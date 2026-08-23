import { useCallback, useEffect, useState } from "react";
import {
  completeAccountOnboarding,
  getAccountOnboarding,
  updateAccountOnboardingPreference,
} from "../api/client";
import type { AccountOnboardingResponse, CustomerSession } from "../types";

export function useOnboardingState(session: CustomerSession | null) {
  const [state, setState] = useState<AccountOnboardingResponse | null>(null);
  const [loading, setLoading] = useState(Boolean(session));
  const [error, setError] = useState<unknown>(null);
  const [reminderDismissed, setReminderDismissed] = useState(false);

  const reload = useCallback(async () => {
    if (!session) {
      setState(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const next = await getAccountOnboarding(session);
      setState(next);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    setReminderDismissed(false);
    void reload();
  }, [reload]);

  const dismissForSession = useCallback(() => setReminderDismissed(true), []);

  const suppressPrompt = useCallback(async () => {
    if (!session) return;
    const next = await updateAccountOnboardingPreference(session, true);
    setState(next);
    setReminderDismissed(true);
  }, [session]);

  const complete = useCallback(async () => {
    if (!session) return null;
    const next = await completeAccountOnboarding(session);
    setState(next);
    return next;
  }, [session]);

  const shouldShowReminder = Boolean(
    session && state && state.human_member && !state.completed && !state.suppress_prompt && !reminderDismissed,
  );

  return { state, loading, error, reload, complete, dismissForSession, suppressPrompt, shouldShowReminder };
}
