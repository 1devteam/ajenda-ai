import { Link } from "react-router";
import Card from "../primitives/Card";
import PanelSkeleton from "../states/PanelSkeleton";
import ErrorState from "../states/ErrorState";

export type MetricItem = {
  id: string;
  label: string;
  value: string | number;
  hint?: string;
  to?: string;
};

type MetricsRowProps = {
  metrics: MetricItem[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
};

export default function MetricsRow({ metrics, loading = false, error = null, onRetry }: MetricsRowProps) {
  if (error) {
    return <ErrorState title="Metrics unavailable" description={error} onRetry={onRetry} />;
  }

  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-3 @sm:grid-cols-2 @xl:grid-cols-4" aria-busy="true">
        {Array.from({ length: 4 }).map((_, index) => (
          <Card key={index} className="min-h-[108px]">
            <PanelSkeleton rows={2} compact />
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 @sm:grid-cols-2 @xl:grid-cols-4">
      {metrics.map((metric) => {
        const body = (
          <>
            <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{metric.label}</p>
            <p className="mt-1 font-display text-3xl font-semibold tracking-tight text-zinc-50">
              {metric.value}
            </p>
            {metric.hint ? <p className="mt-1 text-xs text-zinc-500">{metric.hint}</p> : null}
          </>
        );

        if (metric.to) {
          return (
            <Link key={metric.id} to={metric.to} className="cc-focus-ring block rounded-panel">
              <Card elevated className="h-full transition-colors hover:border-zinc-600">
                {body}
              </Card>
            </Link>
          );
        }

        return (
          <Card key={metric.id} elevated>
            {body}
          </Card>
        );
      })}
    </div>
  );
}
