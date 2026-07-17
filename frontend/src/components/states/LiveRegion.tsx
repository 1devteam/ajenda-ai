import type { ReactNode } from "react";

type LiveRegionProps = {
  message: string;
  politeness?: "polite" | "assertive";
  children?: ReactNode;
};

export default function LiveRegion({
  message,
  politeness = "polite",
  children,
}: LiveRegionProps) {
  return (
    <>
      <div role="status" aria-live={politeness} aria-atomic="true" className="sr-only">
        {message}
      </div>
      {children}
    </>
  );
}