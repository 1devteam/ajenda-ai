import { BUSINESS_PROFILE_FIELDS, STANDALONE_PROCESS_STEPS, type BusinessProfileField } from "./businessProfileFields";

export type WizardStepId = "welcome" | "profile" | "market" | "notes" | "brain" | "plugins";

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
    detail: "Set up the Ajenda central brain for standalone missions without external CRM plugins.",
  },
  {
    id: "profile",
    title: STANDALONE_PROCESS_STEPS[0].title,
    detail: STANDALONE_PROCESS_STEPS[0].detail,
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
    title: "Market focus",
    detail: "Tell missions who you sell to and what you offer.",
    fieldCategories: ["service_area", "target_customers", "products_services"],
  },
  {
    id: "notes",
    title: "Operating guidance",
    detail: "Standing rules for brain missions. Saving projects facts into searchable internal records.",
    fieldCategories: ["operator_notes"],
  },
  {
    id: "brain",
    title: STANDALONE_PROCESS_STEPS[1].title,
    detail: STANDALONE_PROCESS_STEPS[1].detail,
  },
  {
    id: "plugins",
    title: STANDALONE_PROCESS_STEPS[3].title,
    detail: STANDALONE_PROCESS_STEPS[3].detail,
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