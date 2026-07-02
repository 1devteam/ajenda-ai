import { describe, expect, it } from "vitest";
import { sessionFromOidcResponse } from "./session";

describe("sessionFromOidcResponse", () => {
  it("persists refresh token expiry metadata", () => {
    const now = Date.now();
    const session = sessionFromOidcResponse({
      access_token: "access",
      refresh_token: "refresh",
      expires_in: 3600,
      refresh_expires_in: 86_400,
      tenant_id: "tenant-1",
      email: "user@example.com",
      org_name: "Acme",
      slug: "acme",
      plan: "free",
    });

    expect(session.refreshExpiresAt).toBeDefined();
    const refreshExpiresMs = new Date(session.refreshExpiresAt!).getTime();
    expect(refreshExpiresMs).toBeGreaterThan(now + 80_000_000);
    expect(refreshExpiresMs).toBeLessThan(now + 90_000_000);
  });
});