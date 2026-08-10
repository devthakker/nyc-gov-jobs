import { ArrowUpRight, Mail } from "lucide-react";
import { Link, Outlet } from "react-router-dom";
import { Brand } from "./Brand";

export function Layout() {
  return (
    <div className="site-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="site-header">
        <Brand />
        <div className="site-header__note">
          <span className="live-dot" aria-hidden="true" />
          Local pilot · public listings
        </div>
        <nav className="site-header__actions" aria-label="Primary navigation">
          <Link className="header-link header-link--dispatch" to="/newsletter">
            Get alerts <Mail size={14} aria-hidden="true" />
          </Link>
          <a className="header-link header-link--api" href="http://localhost:8000/docs" target="_blank" rel="noreferrer">
            Data API <ArrowUpRight size={14} aria-hidden="true" />
          </a>
        </nav>
      </header>

      <main id="main-content">
        <Outlet />
      </main>

      <footer className="site-footer">
        <div>
          <span className="eyebrow">A practical pilot</span>
          <p>
            Job Tracks gathers public listings and organizes them into approachable career paths.
          </p>
        </div>
        <div className="site-footer__aside">
          <p>Always confirm requirements and deadlines on the employer’s official posting.</p>
          <Link to="/newsletter">Get the weekly opportunity dispatch →</Link>
        </div>
      </footer>
    </div>
  );
}
