import type { BrainMissionCapstoneStep, BrainMissionTemplate } from "./brainMissionTemplates";

export type BrainMissionApiSpec = {
  mission_id: string;
  mission: string;
  outcome: string;
  action: string;
  tier: string;
  side_effect_class: string;
  input: Record<string, unknown>;
  optional_credential: boolean;
};

/** UI-only capstone guide steps; kept client-side because they drive interactive workflow. */
export const CAPSTONE_MISSION_OVERRIDES: Record<string, Partial<BrainMissionTemplate>> = {
  M11: {
    capstone: true,
    requiresCredential: true,
    provider: "external_email",
    capstoneSteps: [
      {
        step: 1,
        label: "Research prospect",
        action: "sales.research",
        description: "Brain-first research against internal records (CRM plugin optional).",
        input: { lead: { company: "Northwind Logistics", domain: "northwind-logistics.example" } },
      },
      {
        step: 2,
        label: "Draft introduction",
        action: "gtm.email_draft",
        description: "Generate pitch email artifact (LLM when configured).",
        input: {
          recipient: "ops@northwind-logistics.example",
          topic: "Ajenda clerical worker pilot",
          tone: "professional",
          context: { goal: "Capstone step 2 — governed draft." },
        },
      },
      {
        step: 3,
        label: "Approve in review queue",
        action: "review_queue",
        description: "Refresh the draft review queue below and approve the artifact for send.",
        input: {},
      },
      {
        step: 4,
        label: "Send approved draft",
        action: "gtm.email_send",
        description: "Send using ajenda-email or Gmail with artifact_id from the approved draft.",
        input: {
          to: "ops@northwind-logistics.example",
          context: { capstone: true },
        },
        requiresCredential: true,
        provider: "external_email",
      },
      {
        step: 5,
        label: "Log in CRM",
        action: "gtm.crm_upsert",
        description: "Record the outreach in internal pipeline / platform HubSpot.",
        input: {
          record_type: "contact",
          data: {
            email: "jordan.lee@northwind-logistics.example",
            firstname: "Jordan",
            lastname: "Lee",
            company: "Northwind Logistics",
          },
        },
      },
    ] satisfies BrainMissionCapstoneStep[],
  },
};

function missionTitle(mission: string, missionId: string): string {
  const prefix = `${missionId} — `;
  if (mission.startsWith(prefix)) {
    return mission.slice(prefix.length);
  }
  if (mission.startsWith(`${missionId} - `)) {
    return mission.slice(`${missionId} - `.length);
  }
  return mission;
}

export function mapBrainMissionsFromApi(missions: BrainMissionApiSpec[]): BrainMissionTemplate[] {
  return missions.map((item) => {
    const override = CAPSTONE_MISSION_OVERRIDES[item.mission_id] ?? {};
    return {
      missionId: item.mission_id,
      title: missionTitle(item.mission, item.mission_id),
      description: item.outcome,
      action: item.action,
      tier: item.tier,
      input: item.input,
      ...(item.optional_credential ? { requiresCredential: true } : {}),
      ...override,
    };
  });
}