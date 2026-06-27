import type { ApiFailure } from "../types";

export function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function failureText(error: unknown): string {
  const maybe = error as Partial<ApiFailure>;
  if (typeof maybe.status === "number") {
    const body = maybe.body;
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      const code =
        "code" in body && typeof (body as { code: unknown }).code === "string"
          ? (body as { code: string }).code
          : undefined;

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
        if (code === "MISSING_CLIENT_TENANT_SESSION") {
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
        const structured = detail as { code?: string; message?: string };
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