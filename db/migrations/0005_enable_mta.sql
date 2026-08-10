UPDATE sources
SET enabled = true,
    configuration = configuration || jsonb_build_object(
        'collection_backend', 'MTA public Jobvite board',
        'coverage_scope', 'Openings published on the Jobvite-hosted board'
    )
WHERE key = 'mta';
