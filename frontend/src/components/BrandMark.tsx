import { Link } from "react-router-dom";

type BrandMarkProps = {
  to?: string;
  compact?: boolean;
  className?: string;
  onClick?: () => void;
  "aria-label"?: string;
};

/** Canonical product wordmark: ajenda-ai (no split-color styling). */
export default function BrandMark({
  to = "/dashboard",
  compact = false,
  className = "",
  onClick,
  "aria-label": ariaLabel = "ajenda-ai home",
}: BrandMarkProps) {
  const mark = (
    <span
      className={`font-display font-semibold tracking-tight text-zinc-100 ${
        compact ? "text-base" : "text-lg"
      } ${className}`.trim()}
    >
      {compact ? "a" : "ajenda-ai"}
    </span>
  );

  if (!to) {
    return mark;
  }

  return (
    <Link
      to={to}
      onClick={onClick}
      aria-label={ariaLabel}
      className="cc-focus-ring rounded-sm text-inherit no-underline"
    >
      {mark}
    </Link>
  );
}
