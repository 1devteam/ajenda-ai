import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import Seo from "../../components/marketing/Seo";

export default function NotFoundPage() {
  return (
    <main className="marketing-site marketing-not-found">
      <Seo title="Page not found — Ajenda AI" description="The requested Ajenda AI page could not be found." />
      <span>404</span>
      <h1>This mission has no route.</h1>
      <p>The page may have moved, or the address may be incorrect.</p>
      <Link className="marketing-button" to="/"><ArrowLeft size={18} /> Return home</Link>
    </main>
  );
}
