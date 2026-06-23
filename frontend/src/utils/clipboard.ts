export async function copyToClipboard(value: string): Promise<boolean> {
  const text = value.trim();
  if (!text) {
    return false;
  }

  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}