export const PUBLIC_SITE_ROUTES = {
  home: { path: "/", label: "Home", navigation: false },
  product: { path: "/product", label: "Product", navigation: true },
  pricing: { path: "/pricing", label: "Pricing", navigation: true },
  security: { path: "/security", label: "Security", navigation: true },
  privacy: { path: "/privacy", label: "Privacy", navigation: false },
  terms: { path: "/terms", label: "Terms", navigation: false },
} as const;

export const PUBLIC_SITE_NAV = Object.values(PUBLIC_SITE_ROUTES).filter((route) => route.navigation);
