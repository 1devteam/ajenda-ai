import type { HTMLAttributes, ReactNode } from "react";

/**
 * Subtle CSS motion wrapper. Prefer Card/Button transitions for most UI.
 * Kept for interactive list rows that need opt-in lift without Framer cost.
 */
type MotionWrapperProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  hoverLift?: boolean;
  pressScale?: boolean;
};

export default function MotionWrapper({
  children,
  hoverLift = false,
  pressScale = false,
  className = "",
  ...props
}: MotionWrapperProps) {
  const motionClasses = [
    hoverLift
      ? "transition-transform duration-150 ease-out hover:-translate-y-0.5 motion-reduce:transform-none"
      : "",
    pressScale ? "active:scale-[0.99] motion-reduce:active:scale-100" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={`${motionClasses} ${className}`.trim()} {...props}>
      {children}
    </div>
  );
}
