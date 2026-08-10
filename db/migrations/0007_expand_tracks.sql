INSERT INTO tracks (slug, name, description, taxonomy_version, sort_order)
VALUES
    ('engineering-architecture-planning', 'Engineering, architecture, and planning',
     'Professional engineering, architecture, estimating, infrastructure design, and planning roles.',
     '1.1', 35),
    ('legal-compliance-policy', 'Legal, compliance, and policy',
     'Legal practice and support, regulatory compliance, investigations, contracts, and policy analysis.',
     '1.1', 95)
ON CONFLICT (slug) DO UPDATE
SET name = EXCLUDED.name,
    description = EXCLUDED.description,
    taxonomy_version = EXCLUDED.taxonomy_version,
    sort_order = EXCLUDED.sort_order,
    active = true;

UPDATE tracks
SET taxonomy_version = '1.1'
WHERE taxonomy_version = '1.0';
