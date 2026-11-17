type EmailReference = { id?: unknown; thread_id?: unknown };

export function EmailReferences({ messages, sourceObservations }: { messages: unknown[]; sourceObservations?: unknown }) {
  const rows = messages.filter((item): item is EmailReference => Boolean(item && typeof item === "object"));
  const observations = Array.isArray(sourceObservations)
    ? sourceObservations.filter((item): item is { real?: unknown } => Boolean(item && typeof item === "object"))
    : [];
  const source = observations.some((item) => item.real === false)
    ? "simulated or mixed"
    : observations.length > 0 && observations.every((item) => item.real === true)
      ? "provider read reported"
      : "unverified";
  return (
    <div>
      <p className="callout">Message content was not retrieved. These are message references only.</p>
      <p>Source status: {source}.</p>
      {rows.length ? (
        <ul>
          {rows.map((item, index) => (
            <li key={`${String(item.id ?? "reference")}-${index}`}>
              Message ID: {String(item.id ?? "unavailable")} · Thread ID: {String(item.thread_id ?? "unavailable")}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No message references were returned. The inbox state is not established here.</p>
      )}
    </div>
  );
}
