import Seo from "../../components/marketing/Seo";

export default function PrivacyPage() {
  return (
    <>
      <Seo title="Privacy Policy — Ajenda AI" description="Ajenda AI privacy policy for website visitors and product users." />
      <article className="marketing-legal marketing-container">
        <span className="marketing-kicker">Legal</span>
        <h1>Privacy Policy</h1>
        <p className="legal-effective">Effective July 18, 2026</p>
        <p>This policy explains how Ajenda AI handles information when you visit our website, create a workspace, connect a provider, or use the product.</p>
        <h2>Information we collect</h2>
        <p>We may collect account and workspace details, authentication identifiers, business information you choose to store, provider connection metadata, mission inputs, execution records, approvals, outcomes, usage information, and technical logs needed to operate and secure the service.</p>
        <h2>How we use information</h2>
        <p>We use information to provide and secure the service, authenticate users, enforce tenant and permission boundaries, execute requested missions, support billing, diagnose failures, prevent abuse, improve product reliability, and communicate about the account.</p>
        <h2>Connected services</h2>
        <p>When you connect another provider, Ajenda uses the credentials and data made available under the permissions you authorize. Provider access is used to perform requested and permitted product functions. Your use of a connected provider also remains subject to that provider’s terms and privacy practices.</p>
        <h2>How information is shared</h2>
        <p>We do not sell personal information. Information may be processed by infrastructure, authentication, email, billing, observability, and integration providers needed to deliver the service. We may also disclose information when legally required or necessary to protect users, the service, or others.</p>
        <h2>Retention and deletion</h2>
        <p>Information is retained for as long as needed to provide the service, meet security and legal obligations, resolve disputes, and enforce agreements. Retention can vary by record type. Account and deletion requests may be submitted through the support channel available in the product.</p>
        <h2>Security</h2>
        <p>Ajenda uses technical and organizational safeguards designed around tenant isolation, scoped authentication, policy controls, authoritative execution, and auditability. No online service can guarantee absolute security.</p>
        <h2>Your choices</h2>
        <p>You may update workspace information, revoke or delete provider credentials, manage available account settings, and request access, correction, or deletion where applicable.</p>
        <h2>Changes</h2>
        <p>We may update this policy as the service or legal requirements change. We will post the revised policy with a new effective date.</p>
        <h2>Contact</h2>
        <p>Privacy questions and requests can be submitted through the support channel shown in your Ajenda AI account.</p>
      </article>
    </>
  );
}
