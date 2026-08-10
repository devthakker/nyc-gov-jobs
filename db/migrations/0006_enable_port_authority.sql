UPDATE sources
SET enabled = true,
    configuration = configuration || jsonb_build_object(
        'collection_backend', 'Port Authority public Jobvite board',
        'coverage_scope', 'Openings published on the official Jobvite board'
    )
WHERE key = 'port_authority';
