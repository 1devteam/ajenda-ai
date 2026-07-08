type FlowStep = {
  id: string;
  label: string;
  count: number;
};

type MissionFlowProps = {
  steps: FlowStep[];
  activeStepId?: string;
};

export default function MissionFlow({ steps, activeStepId }: MissionFlowProps) {
  return (
    <div className="cc-mission-flow">
      {steps.map((step) => (
        <div
          key={step.id}
          className={`cc-flow-step${activeStepId === step.id ? " active" : ""}`}
        >
          <strong>{step.label}</strong>
          <span>{step.count}</span>
        </div>
      ))}
    </div>
  );
}