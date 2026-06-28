const STORAGE_PREFIX = "ajenda.standaloneWizard";

export function wizardStorageKey(tenantId: string): string {
  return `${STORAGE_PREFIX}.${tenantId}.completedAt`;
}

export function readWizardCompletedAt(tenantId: string): string | null {
  try {
    return localStorage.getItem(wizardStorageKey(tenantId));
  } catch {
    return null;
  }
}

export function markWizardCompleted(tenantId: string): void {
  try {
    localStorage.setItem(wizardStorageKey(tenantId), new Date().toISOString());
  } catch {
    // Ignore storage failures; wizard can still finish in-session.
  }
}

export function clearWizardCompletion(tenantId: string): void {
  try {
    localStorage.removeItem(wizardStorageKey(tenantId));
  } catch {
    // Ignore storage failures.
  }
}