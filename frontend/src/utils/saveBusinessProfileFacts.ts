import { upsertBusinessProfileFact } from "../api/client";
import { BUSINESS_PROFILE_FIELDS, type BusinessProfileField } from "../config/businessProfileFields";
import type { BusinessProfileReadResponse, CustomerSession } from "../types";
import { listFact, listFromInput, textFact } from "./businessProfile";

export type ProfileFormValues = Record<string, string>;

function buildFactPayload(field: BusinessProfileField, raw: string): Record<string, unknown> {
  if (field.kind === "list") {
    return listFact(listFromInput(raw));
  }
  return textFact(raw);
}

export async function saveBusinessProfileFacts(
  session: CustomerSession,
  values: ProfileFormValues,
  source: string,
): Promise<BusinessProfileReadResponse | null> {
  let latest: BusinessProfileReadResponse | null = null;
  for (const field of BUSINESS_PROFILE_FIELDS) {
    const raw = values[field.category] ?? "";
    if (!raw.trim()) {
      continue;
    }
    latest = await upsertBusinessProfileFact(session, field.category, {
      approved_fact: buildFactPayload(field, raw),
      provenance_metadata: { source },
    });
  }
  return latest;
}