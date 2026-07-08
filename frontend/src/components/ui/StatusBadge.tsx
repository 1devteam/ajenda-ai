type StatusBadgeProps = {
  status: string;
  label?: string;
};

function toneForStatus(status: string): string {
  const normalized = status.toLowerCase();
  if (["completed", "active", "healthy", "approved", "connected", "success"].some((s) => normalized.includes(s))) {
    return "cc-badge-success";
  }
  if (["pending_review", "waiting", "review", "needs_attention", "warning"].some((s) => normalized.includes(s))) {
    return "cc-badge-review";
  }
  if (["running", "processing", "executing", "queued"].some((s) => normalized.includes(s))) {
    return "cc-badge-running";
  }
  if (["failed", "denied", "error", "revoked"].some((s) => normalized.includes(s))) {
    return "cc-badge-danger";
  }
  if (["planned", "draft", "partial"].some((s) => normalized.includes(s))) {
    return "cc-badge-warning";
  }
  return "cc-badge-neutral";
}

export default function StatusBadge({ status, label }: StatusBadgeProps) {
  return (
    <span className={`cc-badge ${toneForStatus(status)}`}>
      {label ?? status.replace(/_/g, " ")}
    </span>
  );
}