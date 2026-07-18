import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

export default function CallToAction() {
  return (
    <section className="marketing-section marketing-cta-section">
      <div className="marketing-container marketing-cta">
        <div>
          <span className="marketing-kicker">Your next goal starts here</span>
          <h2>Give the work a mission. Keep the decisions in your hands.</h2>
        </div>
        <Link className="marketing-button" to="/signup">
          Start free <ArrowRight size={18} aria-hidden />
        </Link>
      </div>
    </section>
  );
}
