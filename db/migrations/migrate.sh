#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    name text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

for migration in /migrations/[0-9][0-9][0-9][0-9]_*.sql; do
    [ -f "$migration" ] || continue
    filename=$(basename "$migration")
    version=${filename%%_*}

    applied=$(psql -v ON_ERROR_STOP=1 -Atc \
        "SELECT 1 FROM schema_migrations WHERE version = '$version'")
    if [ "$applied" = "1" ]; then
        echo "Already applied: $filename"
        continue
    fi

    echo "Applying: $filename"
    {
        echo "BEGIN;"
        cat "$migration"
        printf "\nINSERT INTO schema_migrations (version, name) VALUES ('%s', '%s');\n" \
            "$version" "$filename"
        echo "COMMIT;"
    } | psql -v ON_ERROR_STOP=1
done

echo "Database migrations are current."
