import { ArrowRight, Check } from "lucide-react";
import { Link } from "react-router";
import Seo from "../../components/marketing/Seo";

const plans = [
  {
    name: "Free",
    price: "$0",
    cadence: "to get started",
    description: "Build your workspace, connect the basics, and learn the governed mission flow.",
    features: ["Ajenda workspace", "Business memory setup", "Mission planning", "Approval queue", "Monthly included usage"],
    action: "Start free",
    to: "/signup",
  },
  {
    name: "Pro",
    price: "Coming soon",
    cadence: "for active operators",
    description: "For businesses ready to run governed ability-runtime work across connected providers.",
    features: ["Everything in Free", "Ability runtime access", "Connected provider actions", "Expanded usage", "Billing self-service"],
    action: "Create your workspace",
    to: "/signup",
    featured: true,
  },
  {
    name: "Enterprise",
    price: "Let’s talk",
    cadence: "for controlled scale",
    description: "For organizations that need stronger deployment, governance, and operational alignment.",
    features: ["Everything in Pro", "Enterprise deployment planning", "Advanced governance alignment", "Higher-scale usage planning", "Dedicated onboarding path"],
    action: "Start a conversation",
    to: "/signup",
  },
];

export default function PricingPage() {
  return (
    <>
      <Seo title="Pricing — Ajenda AI" description="Start Ajenda AI free and move to governed runtime capabilities as your business is ready." />
      <section className="marketing-page-hero centered">
        <div className="marketing-container marketing-section-heading">
          <span className="marketing-kicker">Simple entry. Controlled expansion.</span>
          <h1>Start with the workflow. Scale into execution.</h1>
          <p>New workspaces begin on Free. Runtime abilities and higher usage belong to paid plans as they become available.</p>
        </div>
      </section>
      <section className="marketing-section pricing-section">
        <div className="marketing-container marketing-pricing-grid">
          {plans.map((plan) => (
            <article className={`marketing-price-card ${plan.featured ? "is-featured" : ""}`} key={plan.name}>
              {plan.featured ? <span className="marketing-plan-label">Designed for real work</span> : null}
              <h2>{plan.name}</h2>
              <strong>{plan.price}</strong>
              <small>{plan.cadence}</small>
              <p>{plan.description}</p>
              <ul>{plan.features.map((feature) => <li key={feature}><Check aria-hidden /> {feature}</li>)}</ul>
              <Link className={plan.featured ? "marketing-button" : "marketing-button-secondary"} to={plan.to}>
                {plan.action} <ArrowRight size={17} />
              </Link>
            </article>
          ))}
        </div>
        <p className="marketing-pricing-note">Exact paid pricing and limits will be published before paid plan activation. No unsupported price is being advertised.</p>
      </section>
    </>
  );
}
