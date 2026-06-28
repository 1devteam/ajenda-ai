export type BusinessProfileFact = Record<string, unknown>;

export function readProfileText(
  facts: Record<string, unknown>,
  category: string,
  fallbackKeys: string[] = [],
): string {
  const keys = [category, ...fallbackKeys];
  for (const key of keys) {
    const value = facts[key];
    if (typeof value === "string") {
      const text = value.trim();
      if (text) {
        return text;
      }
    }
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const record = value as Record<string, unknown>;
      for (const nested of ["value", "default", "name"]) {
        const candidate = record[nested];
        if (typeof candidate === "string") {
          const text = candidate.trim();
          if (text) {
            return text;
          }
        }
      }
    }
  }
  return "";
}

export function readProfileList(facts: Record<string, unknown>, category: string): string[] {
  const value = facts[category];
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    for (const nested of ["items", "values", "segments", "services"]) {
      const list = record[nested];
      if (Array.isArray(list)) {
        return list.map((item) => String(item).trim()).filter(Boolean);
      }
    }
    if (typeof record.value === "string") {
      const text = record.value.trim();
      if (text) {
        return text
          .split(",")
          .map((item: string) => item.trim())
          .filter(Boolean);
      }
    }
  }
  if (typeof value === "string") {
    const text = value.trim();
    if (text) {
      return text
        .split(",")
        .map((item: string) => item.trim())
        .filter(Boolean);
    }
  }
  return [];
}

export function textFact(value: string): BusinessProfileFact {
  return { value: value.trim() };
}

export function listFact(values: string[]): BusinessProfileFact {
  const items = values.map((item) => item.trim()).filter(Boolean);
  return { items };
}

export function listFromInput(raw: string): string[] {
  return raw
    .split(/\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function listToInput(values: string[]): string {
  return values.join("\n");
}