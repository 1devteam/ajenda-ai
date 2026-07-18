import { Check, ClipboardCheck, Database, Plug, Rocket, ShieldCheck } from "lucide-react";

const missions = [
  { title: "Research qualified prospects", status: "Running", tone: "running" },
  { title: "Draft personalized follow-ups", status: "Review", tone: "review" },
  { title: "Prepare weekly pipeline brief", status: "Planned", tone: "planned" },
];

export default function ProductPreview() {
  return (
    <div className="product-preview" aria-label="Ajenda AI Command Center preview">
      <div className="preview-topbar">
        <span className="preview-brand">ajenda-ai</span>
        <span className="preview-status"><i /> System online</span>
      </div>
      <div className="preview-body">
        <aside className="preview-sidebar" aria-hidden>
          <span className="is-active"><Rocket /> Missions</span>
          <span><ClipboardCheck /> Approvals</span>
          <span><Database /> Outcomes</span>
          <span><Plug /> Connections</span>
        </aside>
        <div className="preview-main">
          <div className="preview-heading">
            <div>
              <span>Command center</span>
              <strong>Good morning. Here’s what Ajenda is handling.</strong>
            </div>
            <span className="preview-governed"><ShieldCheck /> Governed</span>
          </div>
          <div className="preview-stats">
            <span><small>Active missions</small><strong>6</strong></span>
            <span><small>Approvals waiting</small><strong>1</strong></span>
            <span><small>Completed today</small><strong>4</strong></span>
          </div>
          <div className="preview-work">
            <div className="preview-work-header"><strong>Active work</strong><small>Live mission data</small></div>
            {missions.map((mission) => (
              <div className="preview-mission" key={mission.title}>
                <span><Check aria-hidden /> {mission.title}</span>
                <small className={`preview-pill ${mission.tone}`}>{mission.status}</small>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
