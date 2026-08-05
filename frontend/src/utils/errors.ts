import { extractErrorCode, SESSION_EXPIRED_CLIENT_CODE } from "../auth/sessionLifecycle";
import type { ApiFailure } from "../types";

export interface AuthErrorDetails {
  title?: string;
  message: string;
  code?: string;
  action?: { label: string; href: string };
}

export function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function extractFailureCode(body: unknown): string | undefined {
  return extractErrorCode(body) ?? undefined;
}

function extractFailureMessage(body: unknown): string | undefined {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return undefined;
  }
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (typeof detail === "object" && detail !== null) {
    const structured = detail as { message?: string; code?: string };
    if (typeof structured.message === "string" && structured.message.trim()) {
      return structured.message;
    }
  }
  return undefined;
}

export function authErrorDetails(error: unknown): AuthErrorDetails {
  const message = failureText(error);
  const failure = error as Partial<ApiFailure>;
  const code = typeof failure.body === "object" && failure.body !== null ? extractFailureCode(failure.body) : undefined;

  if (code === "OIDC_ACCESS_DENIED") {
    return {
      title: "Sign-in cancelled",
      message: "Google sign-in was cancelled. Try again when you are ready.",
      code,
      action: { label: "Try again", href: "/signin" },
    };
  }
  if (code === "ACCESS_DENIED") {
    return {
      title: "Authorization cancelled",
      message: "OAuth authorization was cancelled. Try connecting again when you are ready.",
      code,
      action: { label: "Back to credentials", href: "/credentials" },
    };
  }
  if (code === "OAUTH_ERROR") {
    return {
      title: "OAuth connection failed",
      message,
      code,
      action: { label: "Back to credentials", href: "/credentials" },
    };
  }
  if (code === "ACCOUNT_NOT_FOUND") {
    return {
      title: "No matching workspace",
      message,
      code,
      action: { label: "Create account", href: "/signup" },
    };
  }
  if (code === "EMAIL_VERIFICATION_REQUIRED" || message.includes("not verified")) {
    return {
      title: "Email verification required",
      message,
      code: code ?? "EMAIL_VERIFICATION_REQUIRED",
      action: { label: "Verify email", href: "/verify-email" },
    };
  }
  if (
    code === "MISSING_CLIENT_TENANT_SESSION" ||
    code === SESSION_EXPIRED_CLIENT_CODE ||
    code === "AUTHENTICATION_REQUIRED" ||
    code === "INVALID_BEARER_TOKEN"
  ) {
    return {
      title: "Session expired",
      message,
      code,
      action: { label: "Sign in", href: "/signin" },
    };
  }
  if (failure.status === 401) {
    return {
      title: "Authentication failed",
      message,
      code,
      action: { label: "Sign in again", href: "/signin" },
    };
  }
  if (failure.status === 404 && message.toLowerCase().includes("no pending verification")) {
    return {
      title: "Already verified?",
      message: "This email may already be verified. Sign in with Google or an API key to continue.",
      code: "ALREADY_VERIFIED",
      action: { label: "Sign in", href: "/signin" },
    };
  }
  if (failure.status === 429) {
    return {
      title: "Rate limited",
      message,
      code: code ?? "RATE_LIMITED",
    };
  }
  if (failure.status === 402 || code === "QUOTA_EXCEEDED") {
    return {
      title: "Plan limit reached",
      message,
      code: code ?? "QUOTA_EXCEEDED",
      action: { label: "Open billing", href: "/billing" },
    };
  }

  return { message, code };
}

export function failureText(error: unknown): string {
  const maybe = error as Partial<ApiFailure>;
  if (maybe.status === 0) {
    const networkMessage = extractFailureMessage(maybe.body);
    if (networkMessage) {
      return networkMessage;
    }
  }
  if (typeof maybe.status === "number") {
    if (maybe.status === 504) {
      return (
        "Ajenda timed out waiting for the mission interpreter. Local planning often takes 1–3 minutes — " +
        "retry once; if it keeps failing, check that mission-interpreter is healthy and try a shorter mission."
      );
    }
    if (maybe.status === 502 || maybe.status === 503) {
      // Prefer the API's structured message (e.g. INTERPRETER_*) over a generic
      // gateway blurb so operators can act on the real failure.
      const structured = extractFailureMessage(maybe.body);
      const code = extractFailureCode(maybe.body);
      if (structured) {
        return code ? `${structured} (${code})` : structured;
      }
      if (maybe.status === 502) {
        return (
          "Ajenda gateway lost the API mid-request (often during long mission planning). " +
          "Wait a moment and retry Plan mission once."
        );
      }
      return "Ajenda API is temporarily unavailable. Wait a moment and retry.";
    }
    if (maybe.status === 402) {
      const body = maybe.body;
      if (typeof body === "object" && body !== null && "code" in body && (body as { code: string }).code === "QUOTA_EXCEEDED") {
        const quota = body as { field?: string; limit?: number; current?: number; plan?: string; message?: string };
        const field = quota.field?.replace(/_/g, " ") ?? "usage";
        return (
          quota.message ??
          `You have reached your monthly ${field} limit (${quota.current ?? "?"} / ${quota.limit ?? "?"} on the ${quota.plan ?? "current"} plan). Open Billing to upgrade, or wait for the next billing period.`
        );
      }
    }

    const body = maybe.body;
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      const code = extractFailureCode(body);

      if (typeof detail === "string") {
        if (code === "ACCOUNT_NOT_FOUND") {
          return "No Ajenda account matches this Google identity. Create a workspace with the same email, verify it, then try again.";
        }
        if (code === "EMAIL_VERIFICATION_REQUIRED") {
          return "Your email is not verified yet. Finish verification, then sign in with Google again.";
        }
        if (code === "MISSING_TENANT_ID") {
          return `${detail}\n\nTenant-scoped APIs need X-Tenant-Id on every request. In the product UI: sign in at /signin with your tenant UUID and API key (key_id.secret), or finish signup → verify → /promote. Do not open /v1/... URLs directly in the browser address bar.`;
        }
        if (
          code === "MISSING_CLIENT_TENANT_SESSION" ||
          code === SESSION_EXPIRED_CLIENT_CODE ||
          code === "AUTHENTICATION_REQUIRED" ||
          code === "INVALID_BEARER_TOKEN"
        ) {
          return detail;
        }
        if (
          maybe.status === 401 &&
          (detail === "missing authentication credentials" ||
            detail === "malformed api key: expected <key_id>.<secret> format" ||
            detail === "invalid api key")
        ) {
          return "Invalid tenant ID or API key. Use the key_id.secret format from account activation.";
        }
        if (maybe.status === 401 && detail === "invalid bearer token") {
          return "Your sign-in session expired. Sign in again to continue.";
        }
        if (
          (maybe.status === 502 || maybe.status === 503) &&
          (detail.includes("Stripe checkout is unavailable") || detail.includes("Stripe checkout is not configured"))
        ) {
          return `${detail}\n\nGet test keys: https://dashboard.stripe.com/test/apikeys`;
        }
        if (detail === "rate limit exceeded") {
          const retryAfter =
            "retry_after" in body && typeof (body as { retry_after: unknown }).retry_after === "number"
              ? (body as { retry_after: number }).retry_after
              : undefined;
          if (retryAfter && retryAfter > 0) {
            const minutes = Math.max(1, Math.ceil(retryAfter / 60));
            return `Signup is temporarily rate limited. Try again in about ${minutes} minute(s), or use a different email address.`;
          }
          return "Signup is temporarily rate limited. Wait a few minutes or use a different email address.";
        }
        return code ? `${detail} (${code})` : detail;
      }

      if (typeof detail === "object" && detail !== null) {
        const structured = detail as { code?: string; message?: string; field?: string; limit?: number; current?: number; plan?: string };
        if (structured.code === "QUOTA_EXCEEDED" && typeof structured.message === "string") {
          return structured.message;
        }
        if (
          typeof structured.code === "string" &&
          structured.code.startsWith("INTERPRETER_") &&
          typeof structured.message === "string" &&
          structured.message.trim()
        ) {
          return `${structured.message} (${structured.code})`;
        }
        if (
          structured.code === "AUTHENTICATION_REQUIRED" ||
          structured.code === "INVALID_BEARER_TOKEN" ||
          structured.code === SESSION_EXPIRED_CLIENT_CODE
        ) {
          return structured.message ?? "Your sign-in session expired. Sign in again to continue.";
        }
        if (structured.code === "ACCOUNT_NOT_FOUND") {
          return "No Ajenda account matches this Google identity. Create a workspace with the same email, verify it, then try again.";
        }
        if (structured.code === "EMAIL_VERIFICATION_REQUIRED") {
          return "Your email is not verified yet. Finish verification, then sign in with Google again.";
        }
        if (structured.code === "MULTIPLE_TENANTS") {
          return "Multiple workspaces match this Google account. Choose one below to continue.";
        }
        if (structured.code === "MISSION_INTAKE_QUALITY_DENIED" && Array.isArray((detail as { violations?: unknown }).violations)) {
          const violations = (detail as { violations: Array<{ field?: string; reason?: string }> }).violations;
          const lines = violations
            .map((item) => {
              const field = item.field ? `${item.field}: ` : "";
              return `${field}${item.reason ?? "Mission prompt needs more detail."}`;
            })
            .join("\n");
          return lines || structured.message || "Mission intake failed prompt quality gate.";
        }
        if (structured.code === "MISSION_ACTION_NOT_ALLOWED" && typeof structured.message === "string") {
          return `${structured.message} Adjust allowed abilities on the mission or pick a different action.`;
        }
        if (typeof structured.message === "string") {
          return structured.message;
        }
      }

      return `${maybe.message ?? "Request failed"}\n${pretty(detail)}`;
    }
    return `${maybe.message ?? "Request failed"}\n${pretty(body)}`;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return pretty(error);
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}