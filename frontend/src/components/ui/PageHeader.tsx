import type { ReactNode } from "react";

type PageHeaderProps = {
  eyebrow?: string;
  title: string;
  lead?: string;
  actions?: ReactNode;
};

export default function PageHeader({ eyebrow, title, lead, actions }: PageHeaderProps) {
  return (
    <header className="mb-6 flex flex-col gap-4 @lg:mb-8 @lg:flex-row @lg:items-end @lg:justify-between">
      <div className="min-w-0">
        {eyebrow ? (
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-brand-accent">{eyebrow}</p>
        ) : null}
        <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-zinc-50 @md:text-3xl">
          {title}
        </h1>
        {lead ? <p className="mt-2 max-w-2xl text-sm leading-relaxed text-zinc-400 @md:text-base">{lead}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}