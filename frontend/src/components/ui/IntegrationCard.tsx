import type { ReactNode } from "react";
import StatusBadge from "./StatusBadge";

type IntegrationCardProps = {
  name: string;
  description: string;
  status: "connected" | "connect" | "needs_attention" | "coming_soon";
  children?: ReactNode;
  onActivate?: () => void;
  disabled?: boolean;
};

function statusLabel(status: IntegrationCardProps["status"]): string {
  switch (status) {
    case "connected":
      return "Connected";
    case "needs_attention":
      return "Needs attention";
    case "coming_soon":
      return "Coming soon";
    default:
      return "Available";
  }
}

function badgeStatus(status: IntegrationCardProps["status"]): string {
  switch (status) {
    case "connected":
      return "completed";
    case "needs_attention":
      return "pending";
    case "coming_soon":
      return "planned";
    default:
      return "running";
  }
}

export default function IntegrationCard({
  name,
  description,
  status,
  children,
  onActivate,
  disabled = false,
}: IntegrationCardProps) {
  const clickable = Boolean(onActivate) && !disabled && status !== "coming_soon";
  return (
    <article
      className={`cc-integration-card${clickable ? " cc-integration-card-clickable" : ""}`}
      onClick={clickable ? onActivate : undefined}
      onKeyDown={
        clickable
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onActivate?.();
              }
            }
          : undefined
      }
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", alignItems: "flex-start" }}>
        <h3>{name}</h3>
        <StatusBadge status={badgeStatus(status)} label={statusLabel(status)} />
      </div>
      <p className="muted" style={{ margin: "0 0 0.75rem", fontSize: "0.85rem" }}>
        {description}
      </p>
      <div
        onClick={(event) => {
          // Keep nested buttons from double-firing the card handler.
          event.stopPropagation();
        }}
      >
        {children}
      </div>
    </article>
  );
}
