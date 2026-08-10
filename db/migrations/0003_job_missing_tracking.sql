ALTER TABLE jobs
    ADD COLUMN consecutive_misses integer NOT NULL DEFAULT 0
        CHECK (consecutive_misses >= 0),
    ADD COLUMN missing_since_at timestamptz;

CREATE INDEX jobs_missing_tracking_idx
    ON jobs(source_id, consecutive_misses, missing_since_at)
    WHERE status NOT IN ('expired', 'removed');

UPDATE sources
SET configuration = configuration ||
    '{"removal_grace_runs": 3, "removal_grace_hours": 48}'::jsonb;
