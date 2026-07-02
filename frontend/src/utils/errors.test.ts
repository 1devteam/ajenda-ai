import { describe, expect, it } from "vitest";
import { authErrorDetails, failureText } from "./errors";

describe("failureText", () => {
  it("maps structured authentication errors", () => {
    const message = failureText({
      status: 401,
      message: "HTTP 401",
      body: {
        detail: {
          code: "AUTHENTICATION_REQUIRED",
          message: "missing authentication credentials",
        },
      },
    });
    expect(message).toBe("missing authentication credentials");
  });

  it("maps structured quota errors", () => {
    const message = failureText({
      status: 402,
      message: "HTTP 402",
      body: {
        detail: {
          code: "QUOTA_EXCEEDED",
          message: "You have reached the tasks_per_month limit (50) for the 'free' plan. Upgrade to continue.",
          field: "tasks_per_month",
          limit: 50,
          current: 49,
          plan: "free",
        },
      },
    });
    expect(message).toContain("tasks_per_month");
  });

  it("maps network failures", () => {
    const message = failureText({
      status: 0,
      message: "Network error",
      body: {
        detail: "Unable to reach the Ajenda API. Check your connection and try again.",
        code: "NETWORK_ERROR",
      },
    });
    expect(message).toContain("Unable to reach the Ajenda API");
  });
});

describe("authErrorDetails", () => {
  it("adds sign-in action for session expiry", () => {
    const details = authErrorDetails({
      status: 401,
      message: "HTTP 401",
      body: {
        detail: {
          code: "INVALID_BEARER_TOKEN",
          message: "invalid bearer token",
        },
      },
    });
    expect(details.title).toBe("Session expired");
    expect(details.action?.href).toBe("/signin");
  });
});