import { ArrowRight, CheckCircle2, Eye, Hand, Link2, ShieldCheck, Sparkles, Target } from "lucide-react";
import { Link } from "react-router-dom";
import CallToAction from "../../components/marketing/CallToAction";
import ProductPreview from "../../components/marketing/ProductPreview";
import Seo from "../../components/marketing/Seo";

const capabilities = [
  {
    icon: Target,
    title: "Start with an outcome",
    text: "Describe what the business needs. Ajenda turns the goal into a mission with visible work and boundaries.",
  },
  {
    icon: Hand,
    title: "Approve what matters",
    text: "Sensitive or consequential actions pause for review instead of silently crossing the line.",
  },
  {
    icon: Eye,
    title: "See what happened",
    text: "Follow active work, review evidence, and keep a durable record of outcomes and decisions.",
  },
];

export default function HomePage() {
  return (
    <>
      <Seo
        title="Ajenda AI — Governed AI work for your business"
        description="Turn business goals into governed missions, connected work, human approvals, and verifiable outcomes with Ajenda AI."
      />
      <section className="marketing-hero">
        <div className="marketing-container marketing-hero-grid">
          <div className="marketing-hero-copy">
            <div className="marketing-proof-line"><Sparkles size={16} /> AI that works with your business, not around it</div>
            <h1>Turn business goals into <em>governed work.</em></h1>
            <p>
              Ajenda plans missions, coordinates connected tools, asks for approval when it should,
              and records outcomes you can inspect.
            </p>
            <div className="marketing-hero-actions">
              <Link className="marketing-button" to="/signup">
                Start free <ArrowRight size={18} aria-hidden />
              </Link>
              <Link className="marketing-button-secondary" to="/product">
                See how it works
              </Link>
            </div>
            <div className="marketing-trust-row" aria-label="Product principles">
              <span><CheckCircle2 /> Human review</span>
              <span><CheckCircle2 /> Tenant isolation</span>
              <span><CheckCircle2 /> Evidence-backed outcomes</span>
            </div>
          </div>
          <ProductPreview />
        </div>
      </section>

      <section className="marketing-signal-strip" aria-label="Ajenda workflow">
        <div className="marketing-container">
          <span>Goal</span><i />
          <span>Mission</span><i />
          <span>Governed work</span><i />
          <span>Approval</span><i />
          <span>Outcome</span>
        </div>
      </section>

      <section className="marketing-section">
        <div className="marketing-container">
          <div className="marketing-section-heading">
            <span className="marketing-kicker">From instruction to outcome</span>
            <h2>Useful autonomy without the blind spots.</h2>
            <p>Ajenda gives business work a clear operating path, with human control built into the moments that matter.</p>
          </div>
          <div className="marketing-feature-grid">
            {capabilities.map(({ icon: Icon, title, text }, index) => (
              <article className="marketing-feature-card" key={title}>
                <span className="marketing-card-number">0{index + 1}</span>
                <Icon aria-hidden />
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="marketing-section marketing-section-contrast">
        <div className="marketing-container marketing-split">
          <div className="marketing-section-heading align-left">
            <span className="marketing-kicker">One command center</span>
            <h2>Your business context, work, and decisions stay connected.</h2>
            <p>
              Ajenda combines business memory with missions, approvals, connected providers, and outcomes so each piece of work has context and accountability.
            </p>
            <Link className="marketing-inline-link" to="/product">Explore the product <ArrowRight size={17} /></Link>
          </div>
          <div className="marketing-control-stack">
            <div><span><ShieldCheck /></span><strong>Governance before execution</strong><small>Policy and authorization are evaluated before work enters the runtime.</small></div>
            <div><span><Link2 /></span><strong>Tools with explicit boundaries</strong><small>Connections extend Ajenda without replacing its approval and evidence controls.</small></div>
            <div><span><Sparkles /></span><strong>Business memory with oversight</strong><small>Approved facts help future missions understand how your organization operates.</small></div>
          </div>
        </div>
      </section>

      <CallToAction />
    </>
  );
}
