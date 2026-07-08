import type { ReactNode } from "react";
import StatusBadge from "./StatusBadge";

type IntegrationCardProps = {
  name: string;
  description: string;
  status: "connected" | "connect" | "needs_attention" | "coming_soon";
  children?: ReactNode;
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
      return "Connect";
  }
}

export default function IntegrationCard({ name, description, status, children }: IntegrationCardProps) {
  return (
    <article className="cc-integration-card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", alignItems: "flex-start" }}>
        <h3>{name}</h3>
        <StatusBadge
          status={status === "connected" ? "connected" : status === "needs_attention" ? "needs_attention" : "planned"}
          label={statusLabel(status)}
        />
      </div>
      <p className="muted" style={{ margin: "0 0 0.75rem", fontSize: "0.85rem" }}>
        {description}
      </p>
      {children}
    </article>
  );
}