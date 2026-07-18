import Card from "../primitives/Card";

type StatCardProps = {
  label: string;
  value: string | number;
  hint?: string;
};

/** Shared metric card for non-dashboard pages; matches MetricsRow styling. */
export default function StatCard({ label, value, hint }: StatCardProps) {
  return (
    <Card elevated>
      <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="mt-2 font-display text-3xl font-semibold text-zinc-50">{value}</p>
      {hint ? <p className="mt-1 text-xs text-zinc-500">{hint}</p> : null}
    </Card>
  );
}
