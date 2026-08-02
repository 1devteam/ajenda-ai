import { ArrowRight, Brain, CheckCircle2, ClipboardCheck, FileCheck2, Plug, Rocket, ShieldCheck } from "lucide-react";
import { Link } from "react-router";
import CallToAction from "../../components/marketing/CallToAction";
import ProductPreview from "../../components/marketing/ProductPreview";
import Seo from "../../components/marketing/Seo";

const steps = [
  ["01", "Set the mission", "State the outcome, context, constraints, and capabilities the work may use."],
  ["02", "Govern the plan", "Ajenda checks authority, policy, plan access, and the boundaries attached to the mission."],
  ["03", "Coordinate the work", "Eligible work moves through an authoritative queue and visible execution lifecycle."],
  ["04", "Review the outcome", "Approvals, evidence, and outcome records keep important decisions observable."],
];

const surfaces = [
  { icon: Rocket, title: "Missions", text: "Turn a goal into scoped, trackable work instead of a loose chat thread." },
  { icon: ClipboardCheck, title: "Approvals", text: "Keep consequential actions waiting until the right person makes the call." },
  { icon: Brain, title: "Business memory", text: "Give missions approved context about your organization, audience, and operating preferences." },
  { icon: Plug, title: "Connections", text: "Connect provider credentials through a tenant-scoped, governed interface." },
  { icon: FileCheck2, title: "Outcomes", text: "Preserve evidence and recent results so completed work remains inspectable." },
  { icon: ShieldCheck, title: "Runtime control", text: "Use policy, queue, and lease authority to keep work inside explicit execution boundaries." },
];

export default function ProductPage() {
  return (
    <>
      <Seo title="Product — Ajenda AI" description="Explore Ajenda AI missions, approvals, business memory, connected tools, governed runtime control, and evidence-backed outcomes." />
      <section className="marketing-page-hero">
        <div className="marketing-container marketing-page-hero-grid">
          <div>
            <span className="marketing-kicker">How Ajenda works</span>
            <h1>A command center for work that has to stay accountable.</h1>
            <p>Ajenda connects the goal, the authority to act, the live work, and the outcome in one operating path.</p>
            <Link className="marketing-button" to="/signup">Start free <ArrowRight size={18} /></Link>
          </div>
          <ProductPreview />
        </div>
      </section>

      <section className="marketing-section">
        <div className="marketing-container">
          <div className="marketing-section-heading">
            <span className="marketing-kicker">The operating loop</span>
            <h2>From goal to verifiable outcome.</h2>
          </div>
          <ol className="marketing-steps">
            {steps.map(([number, title, text]) => (
              <li key={number}><span>{number}</span><div><h3>{title}</h3><p>{text}</p></div></li>
            ))}
          </ol>
        </div>
      </section>

      <section className="marketing-section marketing-section-contrast">
        <div className="marketing-container">
          <div className="marketing-section-heading">
            <span className="marketing-kicker">Inside the command center</span>
            <h2>Every surface has a job.</h2>
          </div>
          <div className="marketing-surface-grid">
            {surfaces.map(({ icon: Icon, title, text }) => (
              <article key={title}><Icon aria-hidden /><h3>{title}</h3><p>{text}</p><span><CheckCircle2 /> Built into the product</span></article>
            ))}
          </div>
        </div>
      </section>
      <CallToAction />
    </>
  );
}
