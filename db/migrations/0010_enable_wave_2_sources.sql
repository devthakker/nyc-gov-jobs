UPDATE sources
SET enabled = true,
    adapter_version = '1.0.0'
WHERE key IN ('amtrak', 'northwell');

