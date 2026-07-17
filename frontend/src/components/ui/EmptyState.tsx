import type { ReactNode } from "react";

type EmptyStateProps = {
  title: string;
  description?: string;
  icon?: string;
  action?: ReactNode;
};

export default function EmptyState({ title, description, icon, action }: EmptyStateProps) {
  return (
    <div
      role="status"
      className="flex flex-1 flex-col items-center justify-center gap-3 px-4 py-10 text-center @md:px-6"
    >
      {icon ? (
        <span className="text-2xl text-zinc-500" aria-hidden>
          {icon}
        </span>
      ) : null}
      <strong className="text-base text-zinc-200">{title}</strong>
      {description ? <p className="max-w-sm text-sm text-zinc-500">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}