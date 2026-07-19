export type BusinessProfileFieldKind = "text" | "textarea" | "list";

export type BusinessProfileField = {
  category: string;
  label: string;
  description: string;
  kind: BusinessProfileFieldKind;
  placeholder?: string;
  fallbackKeys?: string[];
  section: "identity" | "contact" | "market" | "notes";
};

export const BUSINESS_PROFILE_FIELDS: BusinessProfileField[] = [
  {
    category: "business_name",
    label: "Business name",
    description: "Legal or trading name used in mission briefs and internal records.",
    kind: "text",
    placeholder: "Ajenda AI",
    fallbackKeys: ["name"],
    section: "identity",
  },
  {
    category: "primary_contact_name",
    label: "Primary contact",
    description: "Owner or operator name for outreach and mission context.",
    kind: "text",
    placeholder: "Ajenda Operator",
    section: "identity",
  },
  {
    category: "contact_email",
    label: "Contact email",
    description: "Main business email for replies and operator notifications.",
    kind: "text",
    placeholder: "hello@ajenda.ai",
    section: "contact",
  },
  {
    category: "contact_phone",
    label: "Contact phone",
    description: "Primary phone number for customer or operator follow-up.",
    kind: "text",
    placeholder: "+1 512 555 0100",
    section: "contact",
  },
  {
    category: "website",
    label: "Website",
    description: "Public site used for web research and lead enrichment.",
    kind: "text",
    placeholder: "https://ajenda.ai",
    section: "contact",
  },
  {
    category: "service_area",
    label: "Service area",
    description: "Geography or territory your standalone missions should prioritize.",
    kind: "text",
    placeholder: "Global multi-tenant SaaS",
    fallbackKeys: ["business_address", "address"],
    section: "contact",
  },
  {
    category: "target_customers",
    label: "Target customers",
    description: "Who you sell to. One segment per line.",
    kind: "list",
    placeholder: "Ops leaders automating governed missions\nTeams needing audit trails and tenant isolation",
    section: "market",
  },
  {
    category: "products_services",
    label: "Products & services",
    description: "What you offer. One offering per line.",
    kind: "list",
    placeholder: "Governed mission runtime\nHybrid retrieval over internal records",
    fallbackKeys: ["services", "offerings"],
    section: "market",
  },
  {
    category: "operator_notes",
    label: "Standalone operating notes",
    description: "Standing guidance for Ajenda brain missions without external plugins.",
    kind: "textarea",
    placeholder: "Prefer internal CRM records. Do not send outbound email without approval.",
    section: "notes",
  },
];

export const STANDALONE_PROCESS_STEPS = [
  {
    title: "Business profile",
    detail: "Approved facts here prefill mission briefs and standalone brain context.",
  },
  {
    title: "Internal records",
    detail: "Ajenda AI demo seeds profile-backed accounts and a sample prospect pipeline in tenant_internal_records.",
  },
  {
    title: "Hybrid retrieval",
    detail: "Missions can search governed internal memory plus ephemeral mission chunks.",
  },
  {
    title: "Optional plugins",
    detail: "Connect Gmail, SMTP email, HubSpot, and other adapters only when you need external systems.",
  },
] as const;