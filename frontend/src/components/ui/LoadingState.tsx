import PanelSkeleton from "../states/PanelSkeleton";

type LoadingStateProps = {
  label?: string;
  rows?: number;
};

export default function LoadingState({ label = "Loading...", rows = 2 }: LoadingStateProps) {
  return (
    <div className="rounded-panel border border-os-border bg-os-surface px-4 py-5 @md:px-5" aria-busy="true">
      <p className="sr-only">{label}</p>
      <PanelSkeleton rows={rows} />
    </div>
  );
}