import type { Job, JobDetail, Source, Stats, Track } from "../api/client";

export const jobFixture: Job = {
  id: "11111111-1111-4111-8111-111111111111",
  external_id: "TEST-101",
  title: "Help Desk Technician",
  summary: "Support staff and workplace technology.",
  canonical_url: "https://example.test/jobs/TEST-101",
  apply_url: "https://example.test/jobs/TEST-101/apply",
  source: { key: "mta", name: "Metropolitan Transportation Authority", last_success_at: "2026-08-10T12:00:00Z" },
  employer: { name: "New York City Transit" },
  location: { text: "Brooklyn, NY", city: "Brooklyn", state: "NY" },
  salary: { minimum: 60000, maximum: 75000, currency: "USD", period: "year", display_text: "$60,000–$75,000" },
  source_category: "Technology",
  employment_type: "Full-time",
  work_mode: "hybrid",
  posted_at: "2026-08-10T12:00:00Z",
  closes_on: "2026-09-10",
  status: "active",
  tracks: [
    {
      slug: "it-data-cybersecurity",
      name: "IT, data, and cybersecurity",
      is_primary: true,
      confidence: 0.91,
      review_status: "unreviewed",
    },
  ],
  first_seen_at: "2026-08-10T12:00:00Z",
  last_seen_at: "2026-08-10T12:00:00Z",
  last_changed_at: "2026-08-10T12:00:00Z",
};

export const jobDetailFixture: JobDetail = {
  ...jobFixture,
  description_text: "Resolve tickets and support users.",
  requirements_text: "One year of technical support experience.",
  requirements: [{ type: "Minimum qualifications", text: "One year of experience." }],
  licenses: [{ name: "Driver license" }],
  experience_years_min: 1,
  education_level: "High school",
};

export const trackFixture: Track = {
  slug: "it-data-cybersecurity",
  name: "IT, data, and cybersecurity",
  description: "Technical support, software, systems, and data.",
  taxonomy_version: "1.1",
  sort_order: 20,
  job_count: 2,
  primary_job_count: 2,
  needs_review_count: 0,
};

export const sourceFixture: Source = {
  key: "mta",
  name: "Metropolitan Transportation Authority",
  base_url: "https://careers.mta.org/search/jobs",
  enabled: true,
  adapter_version: "1.0.0",
  last_attempt_at: "2026-08-10T12:00:00Z",
  last_success_at: "2026-08-10T12:00:00Z",
  consecutive_failures: 0,
  active_job_count: 2,
  total_job_count: 2,
  latest_sync_status: "succeeded",
};

export const statsFixture: Stats = {
  generated_at: "2026-08-10T12:00:00Z",
  total_jobs: 2,
  active_jobs: 2,
  expired_jobs: 0,
  removed_jobs: 0,
  unknown_jobs: 0,
  unclassified_active_jobs: 0,
  jobs_needing_review: 0,
  enabled_sources: 1,
  active_tracks: 1,
  latest_source_success_at: "2026-08-10T12:00:00Z",
  primary_track_counts: [{ slug: trackFixture.slug, name: trackFixture.name, job_count: 2 }],
};
