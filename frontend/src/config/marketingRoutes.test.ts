import { describe, expect, it } from "vitest";
import { PUBLIC_SITE_NAV, PUBLIC_SITE_ROUTES } from "./marketingRoutes";

describe("public site routes", () => {
  it("keeps every public path absolute and unique", () => {
    const paths = Object.values(PUBLIC_SITE_ROUTES).map((route) => route.path);

    expect(paths.every((path) => path.startsWith("/"))).toBe(true);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it("exposes product, pricing, and security in the primary navigation", () => {
    expect(PUBLIC_SITE_NAV.map((route) => route.path)).toEqual([
      "/product",
      "/pricing",
      "/security",
    ]);
  });

  it("keeps legal routes public without crowding the primary navigation", () => {
    expect(PUBLIC_SITE_ROUTES.privacy.navigation).toBe(false);
    expect(PUBLIC_SITE_ROUTES.terms.navigation).toBe(false);
  });
});
