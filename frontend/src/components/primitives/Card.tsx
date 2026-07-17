import type { HTMLAttributes, ReactNode } from "react";

type CardProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  elevated?: boolean;
  interactive?: boolean;
};

export default function Card({
  children,
  elevated = false,
  interactive = false,
  className = "",
  ...rest
}: CardProps) {
  const surface = elevated ? "cc-panel-elevated" : "cc-panel";
  const interact = interactive
    ? "transition-transform duration-150 ease-out hover:-translate-y-0.5 motion-reduce:transform-none"
    : "";

  return (
    <div className={`@container ${surface} p-4 @md:p-5 ${interact} ${className}`.trim()} {...rest}>
      {children}
    </div>
  );
}
