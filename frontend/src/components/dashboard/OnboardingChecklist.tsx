import { Link } from "react-router-dom";
import { Check, Circle } from "lucide-react";
import type { ChecklistStep } from "../../dashboard/dashboardModel";
import Card from "../primitives/Card";

type OnboardingChecklistProps = {
  steps: ChecklistStep[];
};

export default function OnboardingChecklist({ steps }: OnboardingChecklistProps) {
  const doneCount = steps.filter((step) => step.done).length;
  const next = steps.find((step) => !step.done);

  return (
    <Card elevated className="mb-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="font-display text-lg font-semibold text-zinc-100">Get started</h2>
          <p className="mt-1 text-sm text-zinc-500">
            {doneCount} of {steps.length} steps done
            {next ? ` — next: ${next.label.toLowerCase()}` : ""}
          </p>
        </div>
      </div>
      <ol className="flex flex-col gap-2">
        {steps.map((step, index) => (
          <li key={step.id}>
            <Link
              to={step.to}
              className={`cc-focus-ring flex min-h-12 items-start gap-3 rounded-lg border px-3 py-3 transition-colors @md:px-4 ${
                step.done
                  ? "border-semantic-success/20 bg-semantic-success/5 text-zinc-400"
                  : next?.id === step.id
                    ? "border-brand-accent/40 bg-brand-accent/5 text-zinc-100"
                    : "border-os-border bg-os-bg/40 text-zinc-200 hover:border-zinc-600"
              }`}
            >
              <span className="mt-0.5 shrink-0" aria-hidden>
                {step.done ? (
                  <Check className="h-5 w-5 text-semantic-success" />
                ) : (
                  <Circle className="h-5 w-5 text-zinc-500" />
                )}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold">
                  {index + 1}. {step.label}
                </span>
                <span className="mt-0.5 block text-xs text-zinc-500">{step.description}</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </Card>
  );
}
