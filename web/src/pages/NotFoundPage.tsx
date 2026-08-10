import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="not-found">
      <span>404 / Off track</span>
      <h1>This route doesn’t lead to an opportunity.</h1>
      <Link to="/"><ArrowLeft size={18} /> Return to the job index</Link>
    </section>
  );
}
