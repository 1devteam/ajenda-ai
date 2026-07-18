import Button from "../primitives/Button";

type ErrorStateProps = {
  title: string;
  description?: string;
  critical?: boolean;
  onRetry?: () => void;
  retryLabel?: string;
};

export default function ErrorState({
  title,
  description,
  critical = false,
  onRetry,
  retryLabel = "Try again",
}: ErrorStateProps) {
  const accent = critical ? "text-crimson-bright" : "text-semantic-warning";
  const border = critical ? "border-crimson/40" : "border-semantic-warning/30";

  return (
    <div
      role="alert"
      className={`flex flex-col items-center gap-3 rounded-panel border ${border} bg-os-surface px-4 py-8 text-center @md:px-6`}
    >
      <span className={`text-2xl ${accent}`} aria-hidden>
        {critical ? "✕" : "!"}
      </span>
      <strong className="text-base text-zinc-100">{title}</strong>
      {description ? <p className="max-w-sm text-sm text-zinc-400">{description}</p> : null}
      {onRetry ? (
        <Button variant={critical ? "danger" : "subtle"} onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}