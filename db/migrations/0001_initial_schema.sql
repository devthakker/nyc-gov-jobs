CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TABLE sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key varchar(64) NOT NULL UNIQUE,
    name text NOT NULL,
    base_url text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    sync_interval_minutes integer NOT NULL DEFAULT 1440
        CHECK (sync_interval_minutes > 0),
    adapter_version text,
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(configuration) = 'object'),
    last_attempt_at timestamptz,
    last_success_at timestamptz,
    consecutive_failures integer NOT NULL DEFAULT 0
        CHECK (consecutive_failures >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (key ~ '^[a-z][a-z0-9_]*$'),
    CHECK (base_url ~ '^https?://')
);

CREATE TABLE employers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_employer_id uuid REFERENCES employers(id) ON DELETE SET NULL,
    name text NOT NULL,
    normalized_name text NOT NULL,
    website_url text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (normalized_name),
    CHECK (website_url IS NULL OR website_url ~ '^https?://')
);

CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    employer_id uuid REFERENCES employers(id) ON DELETE SET NULL,
    external_id text NOT NULL,
    title text NOT NULL,
    normalized_title text,
    summary text,
    description_text text,
    requirements_text text,
    requirements jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(requirements) = 'array'),
    canonical_url text NOT NULL,
    apply_url text,
    source_category text,
    source_department text,
    source_agency text,
    location_text text,
    city text,
    borough text,
    region text,
    state varchar(2),
    postal_code text,
    salary_min numeric(14, 2),
    salary_max numeric(14, 2),
    salary_currency varchar(3),
    salary_period text,
    salary_raw text,
    employment_type text,
    schedule text,
    work_mode text,
    experience_level text,
    experience_years_min numeric(4, 1),
    education_level text,
    licenses jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(licenses) = 'array'),
    posted_at timestamptz,
    opens_on date,
    closes_on date,
    status text NOT NULL DEFAULT 'active',
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    last_changed_at timestamptz NOT NULL DEFAULT now(),
    content_hash varchar(64) NOT NULL,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(raw_payload) = 'object'),
    source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(source_metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    search_document tsvector GENERATED ALWAYS AS (
        to_tsvector(
            'english',
            coalesce(title, '') || ' ' ||
            coalesce(normalized_title, '') || ' ' ||
            coalesce(summary, '') || ' ' ||
            coalesce(description_text, '') || ' ' ||
            coalesce(requirements_text, '') || ' ' ||
            coalesce(source_category, '') || ' ' ||
            coalesce(source_department, '') || ' ' ||
            coalesce(source_agency, '') || ' ' ||
            coalesce(location_text, '')
        )
    ) STORED,
    UNIQUE (source_id, external_id),
    CHECK (btrim(external_id) <> ''),
    CHECK (btrim(title) <> ''),
    CHECK (canonical_url ~ '^https?://'),
    CHECK (apply_url IS NULL OR apply_url ~ '^https?://'),
    CHECK (state IS NULL OR state ~ '^[A-Z]{2}$'),
    CHECK (salary_min IS NULL OR salary_min >= 0),
    CHECK (salary_max IS NULL OR salary_max >= 0),
    CHECK (salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max),
    CHECK (salary_currency IS NULL OR salary_currency ~ '^[A-Z]{3}$'),
    CHECK (salary_period IS NULL OR salary_period IN
        ('hour', 'day', 'week', 'month', 'year', 'other')),
    CHECK (work_mode IS NULL OR work_mode IN
        ('on_site', 'hybrid', 'remote', 'unknown')),
    CHECK (experience_years_min IS NULL OR experience_years_min >= 0),
    CHECK (status IN ('active', 'expired', 'removed', 'unknown')),
    CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CHECK (closes_on IS NULL OR opens_on IS NULL OR closes_on >= opens_on)
);

CREATE INDEX jobs_status_idx ON jobs(status);
CREATE INDEX jobs_source_status_idx ON jobs(source_id, status);
CREATE INDEX jobs_employer_idx ON jobs(employer_id);
CREATE INDEX jobs_closes_on_idx ON jobs(closes_on) WHERE closes_on IS NOT NULL;
CREATE INDEX jobs_last_seen_at_idx ON jobs(last_seen_at);
CREATE INDEX jobs_search_document_idx ON jobs USING gin(search_document);

CREATE TABLE job_versions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    observed_at timestamptz NOT NULL DEFAULT now(),
    content_hash varchar(64) NOT NULL,
    changed_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
    normalized_snapshot jsonb NOT NULL
        CHECK (jsonb_typeof(normalized_snapshot) = 'object'),
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(raw_payload) = 'object'),
    CHECK (content_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX job_versions_job_observed_idx
    ON job_versions(job_id, observed_at DESC);

CREATE TABLE tracks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug varchar(96) NOT NULL UNIQUE,
    name text NOT NULL UNIQUE,
    description text NOT NULL,
    taxonomy_version text NOT NULL DEFAULT '1.0',
    active boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (slug ~ '^[a-z][a-z0-9-]*$')
);

CREATE TABLE job_tracks (
    job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE RESTRICT,
    is_primary boolean NOT NULL DEFAULT false,
    confidence numeric(4, 3) NOT NULL,
    method text NOT NULL,
    reason text,
    taxonomy_version text NOT NULL DEFAULT '1.0',
    review_status text NOT NULL DEFAULT 'unreviewed',
    reviewed_at timestamptz,
    reviewed_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, track_id),
    CHECK (confidence >= 0 AND confidence <= 1),
    CHECK (method IN ('source_map', 'rule', 'model', 'human')),
    CHECK (review_status IN ('unreviewed', 'approved', 'rejected', 'needs_review')),
    CHECK ((reviewed_at IS NULL) = (reviewed_by IS NULL))
);

CREATE UNIQUE INDEX job_tracks_one_primary_idx
    ON job_tracks(job_id) WHERE is_primary;
CREATE INDEX job_tracks_track_idx ON job_tracks(track_id, is_primary);
CREATE INDEX job_tracks_review_idx ON job_tracks(review_status);

CREATE TABLE sync_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL DEFAULT 'running',
    discovered_count integer NOT NULL DEFAULT 0,
    inserted_count integer NOT NULL DEFAULT 0,
    updated_count integer NOT NULL DEFAULT 0,
    unchanged_count integer NOT NULL DEFAULT 0,
    skipped_count integer NOT NULL DEFAULT 0,
    failed_count integer NOT NULL DEFAULT 0,
    error_summary text,
    diagnostics jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(diagnostics) = 'object'),
    CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK (discovered_count >= 0),
    CHECK (inserted_count >= 0),
    CHECK (updated_count >= 0),
    CHECK (unchanged_count >= 0),
    CHECK (skipped_count >= 0),
    CHECK (failed_count >= 0)
);

CREATE INDEX sync_runs_source_started_idx
    ON sync_runs(source_id, started_at DESC);
CREATE INDEX sync_runs_status_idx ON sync_runs(status);

CREATE TABLE newsletter_issues (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject text NOT NULL,
    filters jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(filters) = 'object'),
    status text NOT NULL DEFAULT 'draft',
    rendered_at timestamptz,
    sent_at timestamptz,
    recipient_count integer NOT NULL DEFAULT 0,
    content_hash varchar(64),
    error_summary text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('draft', 'rendered', 'sending', 'sent', 'failed')),
    CHECK (recipient_count >= 0),
    CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
    CHECK (sent_at IS NULL OR rendered_at IS NOT NULL)
);

CREATE TABLE newsletter_issue_jobs (
    newsletter_issue_id uuid NOT NULL
        REFERENCES newsletter_issues(id) ON DELETE CASCADE,
    job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    position integer NOT NULL CHECK (position > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (newsletter_issue_id, job_id),
    UNIQUE (newsletter_issue_id, position)
);

CREATE TRIGGER sources_set_updated_at
BEFORE UPDATE ON sources
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER employers_set_updated_at
BEFORE UPDATE ON employers
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER jobs_set_updated_at
BEFORE UPDATE ON jobs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER tracks_set_updated_at
BEFORE UPDATE ON tracks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER job_tracks_set_updated_at
BEFORE UPDATE ON job_tracks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER newsletter_issues_set_updated_at
BEFORE UPDATE ON newsletter_issues
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE VIEW active_jobs AS
SELECT *
FROM jobs
WHERE status = 'active'
  AND (closes_on IS NULL OR closes_on >= CURRENT_DATE);

COMMENT ON VIEW active_jobs IS
    'Jobs explicitly active and not past a known closing date.';
