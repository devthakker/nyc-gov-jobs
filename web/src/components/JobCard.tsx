import { ArrowRight, BriefcaseBusiness, CalendarClock, MapPin } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import type { Job } from "../api/client";
import { formatRelativeDate, formatSalary, locationLabel, workModeLabel } from "../lib/formatters";

type JobCardProps = {
  job: Job;
  number: number;
};

export function JobCard({ job, number }: JobCardProps) {
  const location = useLocation();
  const primaryTrack = job.tracks.find((track) => track.is_primary) ?? job.tracks[0];
  const salary = formatSalary(job);
  const closes = formatRelativeDate(job.closes_on);
  const workMode = workModeLabel(job.work_mode);

  return (
    <article className="job-card" style={{ "--card-index": Math.min(number, 10) } as React.CSSProperties}>
      <div className="job-card__number" aria-hidden="true">
        {String(number).padStart(2, "0")}
      </div>
      <div className="job-card__body">
        <div className="job-card__source">
          <span>{job.source.name}</span>
          {primaryTrack && <span className="track-stamp">{primaryTrack.name}</span>}
        </div>
        <h2>
          <Link to={`/jobs/${job.id}`} state={{ from: `${location.pathname}${location.search}` }}>
            {job.title}
          </Link>
        </h2>
        <p className="job-card__employer">{job.employer.name}</p>
        {job.summary && <p className="job-card__summary">{job.summary}</p>}
        <dl className="job-facts">
          <div>
            <dt><MapPin size={15} aria-hidden="true" /> Location</dt>
            <dd>{locationLabel(job)}</dd>
          </div>
          {(salary || job.employment_type || workMode) && (
            <div>
              <dt><BriefcaseBusiness size={15} aria-hidden="true" /> Terms</dt>
              <dd>{[salary, job.employment_type, workMode].filter(Boolean).join(" · ")}</dd>
            </div>
          )}
          {closes && (
            <div>
              <dt><CalendarClock size={15} aria-hidden="true" /> Closes</dt>
              <dd>{closes}</dd>
            </div>
          )}
        </dl>
      </div>
      <Link
        className="job-card__action"
        to={`/jobs/${job.id}`}
        state={{ from: `${location.pathname}${location.search}` }}
        aria-label={`View ${job.title}`}
      >
        <span>View role</span>
        <ArrowRight size={20} aria-hidden="true" />
      </Link>
    </article>
  );
}
