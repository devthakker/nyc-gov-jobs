import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpenCheck,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  GraduationCap,
  MapPin,
  WalletCards,
} from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";
import { APIError, getJob } from "../api/client";
import { ErrorPanel } from "../components/StatusViews";
import { formatDate, formatSalary, locationLabel, workModeLabel } from "../lib/formatters";

export function JobDetailPage() {
  const { jobId = "" } = useParams();
  const location = useLocation();
  const backTo = (location.state as { from?: string } | null)?.from ?? "/";
  const query = useQuery({
    queryKey: ["job", jobId],
    queryFn: ({ signal }) => getJob(jobId, signal),
    enabled: Boolean(jobId),
  });

  if (query.isLoading) {
    return (
      <div className="detail-loading" role="status">
        <span>Opening the file</span><i /><i /><i />
      </div>
    );
  }
  if (query.isError) {
    const notFound = query.error instanceof APIError && query.error.status === 404;
    return (
      <section className="detail-error">
        <Link className="back-link" to={backTo}><ArrowLeft size={17} /> Back to the index</Link>
        <ErrorPanel
          message={notFound ? "This listing may have moved or expired." : query.error.message}
          onRetry={() => query.refetch()}
        />
      </section>
    );
  }

  const job = query.data;
  if (!job) return null;
  const salary = formatSalary(job);
  const workMode = workModeLabel(job.work_mode);
  const applyUrl = job.apply_url ?? job.canonical_url;

  return (
    <article className="job-detail">
      <div className="detail-topbar">
        <Link className="back-link" to={backTo}><ArrowLeft size={17} /> Back to the index</Link>
        <span>File no. {job.external_id}</span>
      </div>

      <header className="detail-hero">
        <div className="detail-hero__main">
          <span className="detail-source">{job.source.name}</span>
          <h1>{job.title}</h1>
          <p>{job.employer.name}</p>
          <div className="detail-track-row">
            {job.tracks.map((track) => (
              <span className={track.is_primary ? "is-primary" : ""} key={track.slug}>
                {track.is_primary && <small>Primary</small>}{track.name}
              </span>
            ))}
          </div>
        </div>
        <div className="detail-hero__action">
          <span className="eyebrow">Official application</span>
          <p>Review the source posting before submitting your materials.</p>
          <a href={applyUrl} target="_blank" rel="noreferrer">
            Apply on employer site <ArrowUpRight size={19} aria-hidden="true" />
          </a>
        </div>
      </header>

      <div className="detail-grid">
        <aside className="detail-facts" aria-label="Job details">
          <h2>At a glance</h2>
          <dl>
            <div><dt><Building2 size={17} /> Employer</dt><dd>{job.employer.name}</dd></div>
            <div><dt><MapPin size={17} /> Location</dt><dd>{locationLabel(job)}</dd></div>
            {salary && <div><dt><WalletCards size={17} /> Listed pay</dt><dd>{salary}</dd></div>}
            {(job.employment_type || workMode) && (
              <div><dt><BriefcaseBusiness size={17} /> Work</dt><dd>{[job.employment_type, workMode].filter(Boolean).join(" · ")}</dd></div>
            )}
            {(job.posted_at || job.opens_on) && (
              <div><dt><CalendarDays size={17} /> Posted</dt><dd>{formatDate(job.posted_at ?? job.opens_on)}</dd></div>
            )}
            {job.closes_on && <div><dt><CalendarDays size={17} /> Apply by</dt><dd>{formatDate(job.closes_on)}</dd></div>}
            {job.education_level && <div><dt><GraduationCap size={17} /> Education</dt><dd>{job.education_level}</dd></div>}
          </dl>
          <div className="source-note">
            <span>Data note</span>
            <p>Last checked {formatDate(job.last_seen_at)} from the employer’s public listing.</p>
          </div>
        </aside>

        <div className="detail-content">
          {(job.summary || job.description_text) && (
            <section>
              <span className="section-index">01 / The role</span>
              <h2>What you’ll be stepping into</h2>
              {job.summary && <p className="detail-lede">{job.summary}</p>}
              {job.description_text && <div className="source-copy">{job.description_text}</div>}
            </section>
          )}

          {(job.requirements.length > 0 || job.requirements_text) && (
            <section>
              <span className="section-index">02 / Qualifications</span>
              <h2>What the employer is looking for</h2>
              {job.requirements.map((requirement, index) => (
                <div className="requirement" key={`${requirement.type}-${index}`}>
                  <BookOpenCheck size={20} aria-hidden="true" />
                  <div>
                    {requirement.type && <h3>{requirement.type}</h3>}
                    <p>{requirement.text}</p>
                  </div>
                </div>
              ))}
              {job.requirements.length === 0 && job.requirements_text && (
                <div className="source-copy">{job.requirements_text}</div>
              )}
            </section>
          )}

          {(job.licenses.length > 0 || job.experience_years_min != null) && (
            <section>
              <span className="section-index">03 / Credentials</span>
              <h2>Experience and licenses</h2>
              {job.experience_years_min != null && <p>Minimum experience: {job.experience_years_min} years.</p>}
              {job.licenses.map((license) => <p key={license.name}>{license.name}</p>)}
            </section>
          )}
        </div>
      </div>
    </article>
  );
}
