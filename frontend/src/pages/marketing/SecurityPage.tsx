import { DatabaseZap, FileSearch, KeyRound, Network, ShieldCheck, UserCheck } from "lucide-react";
import CallToAction from "../../components/marketing/CallToAction";
import Seo from "../../components/marketing/Seo";

const safeguards = [
  { icon: UserCheck, title: "Tenant isolation", text: "Tenant context is enforced across HTTP, service, repository, and database boundaries." },
  { icon: KeyRound, title: "Scoped authentication", text: "OIDC and API-key paths resolve identity and permissions inside a validated tenant envelope." },
  { icon: ShieldCheck, title: "Policy before execution", text: "Governance and authorization can deny work or place it into human review before admission." },
  { icon: Network, title: "Authoritative execution", text: "Queue-backed admission and worker leases control which eligible work may execute." },
  { icon: DatabaseZap, title: "Bounded recovery", text: "Recovery paths are designed to be observable and to avoid silently corrupting execution state." },
  { icon: FileSearch, title: "Evidence and auditability", text: "Outcomes, governance events, and runtime evidence preserve what happened and why." },
];

export default function SecurityPage() {
  return (
    <>
      <Seo title="Security and governance — Ajenda AI" description="Learn how Ajenda AI approaches tenant isolation, authentication, policy gates, authoritative execution, recovery, evidence, and auditability." />
      <section className="marketing-page-hero security-hero">
        <div className="marketing-container marketing-security-intro">
          <div className="security-orbit" aria-hidden><ShieldCheck /></div>
          <div>
            <span className="marketing-kicker">Security and governance</span>
            <h1>Control is part of the runtime—not a promise around it.</h1>
            <p>Ajenda is designed so tenant scope, policy, execution authority, and evidence stay attached to the work from admission through outcome.</p>
          </div>
        </div>
      </section>
      <section className="marketing-section">
        <div className="marketing-container marketing-security-grid">
          {safeguards.map(({ icon: Icon, title, text }) => <article key={title}><Icon /><h2>{title}</h2><p>{text}</p></article>)}
        </div>
      </section>
      <section className="marketing-section marketing-section-contrast">
        <div className="marketing-container marketing-principles">
          <div><span>01</span><h2>Fail closed</h2><p>Missing authority or an unavailable required dependency should stop eligible work from being treated as safe.</p></div>
          <div><span>02</span><h2>Keep humans in control</h2><p>Consequential paths can pause for explicit review instead of treating autonomy as an all-or-nothing switch.</p></div>
          <div><span>03</span><h2>Prove the outcome</h2><p>Release and operational confidence should come from runtime evidence, not descriptions or assumptions.</p></div>
        </div>
      </section>
      <CallToAction />
    </>
  );
}
