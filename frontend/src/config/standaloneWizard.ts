import { BUSINESS_PROFILE_FIELDS, type BusinessProfileField } from "./businessProfileFields";

export type WizardStepId = "welcome" | "profile" | "market" | "notes" | "charter" | "brain" | "plugins";

export type WizardStep = {
  id: WizardStepId;
  title: string;
  detail: string;
  fieldCategories?: string[];
};

const fieldByCategory = new Map(BUSINESS_PROFILE_FIELDS.map((field) => [field.category, field]));

export function wizardFieldsForStep(step: WizardStep): BusinessProfileField[] {
  if (!step.fieldCategories?.length) {
    return [];
  }
  return step.fieldCategories
    .map((category) => fieldByCategory.get(category))
    .filter((field): field is BusinessProfileField => field !== undefined);
}

export const STANDALONE_WIZARD_STEPS: WizardStep[] = [
  {
    id: "welcome",
    title: "Welcome",
    detail: "A short setup so missions start with the right company context.",
  },
  {
    id: "profile",
    title: "Your company",
    detail: "Tell Ajenda who you are and how to reach you.",
    fieldCategories: [
      "business_name",
      "primary_contact_name",
      "contact_email",
      "contact_phone",
      "website",
    ],
  },
  {
    id: "market",
    title: "Customers & services",
    detail: "Tell Ajenda who you serve and what you provide.",
    fieldCategories: ["service_area", "target_customers", "products_services"],
  },
  {
    id: "notes",
    title: "Business context",
    detail: "Add any notes that help Ajenda prepare useful work.",
    fieldCategories: ["operator_notes"],
  },
  {
    id: "charter",
    title: "How Ajenda should operate",
    detail: "Choose what Ajenda may prepare automatically and which actions need your approval.",
  },
  {
    id: "brain",
    title: "Review",
    detail: "Review your setup before finishing.",
  },
  {
    id: "plugins",
    title: "Connect your tools",
    detail: "Connect optional business tools. You can continue without any connections.",
  },
];

export const WIZARD_REQUIRED_CATEGORIES = ["business_name", "contact_email"] as const;

export function demoValuesFromPlaceholders(): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of BUSINESS_PROFILE_FIELDS) {
    if (field.placeholder) {
      values[field.category] = field.placeholder;
    }
  }
  return values;
}
