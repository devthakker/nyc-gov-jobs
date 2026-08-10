import { Link } from "react-router-dom";

export function Brand() {
  return (
    <Link className="brand" to="/" aria-label="Job Tracks home">
      <span className="brand__mark" aria-hidden="true">
        <span>J</span>
        <span>T</span>
      </span>
      <span className="brand__name">
        <strong>Job Tracks</strong>
        <small>New York Opportunity Desk</small>
      </span>
    </Link>
  );
}
