import type { ReactNode } from "react";

type PageHeaderProps = {
  eyebrow?: string;
  title: string;
  lead?: string;
  actions?: ReactNode;
};

export default function PageHeader({ eyebrow, title, lead, actions }: PageHeaderProps) {
  return (
    <header className="cc-page-header">
      <div>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {lead ? <p className="cc-lead">{lead}</p> : null}
      </div>
      {actions ? <div className="cc-page-actions">{actions}</div> : null}
    </header>
  );
}