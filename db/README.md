# Local PostgreSQL database

The pilot database runs entirely in Docker. No PostgreSQL client or Python
database package is installed globally.

## Start and migrate

```bash
docker compose up -d postgres
docker compose run --rm migrate
```

PostgreSQL is available only on `127.0.0.1:5433` by default. Settings live in
the ignored `.env` file; `.env.example` documents the required variables.

## Check status and migrations

```bash
docker compose ps postgres
docker compose exec postgres psql -U jobtracks -d jobtracks \
  -c "SELECT version, name, applied_at FROM schema_migrations ORDER BY version;"
```

## Open a SQL shell

```bash
docker compose exec postgres psql -U jobtracks -d jobtracks
```

## Stop without deleting data

```bash
docker compose stop postgres
```

The `postgres-data` named volume persists across stop/start and container
recreation. Do not use `docker compose down -v` unless intentionally deleting
the local pilot database.

## Add a migration

Create the next zero-padded SQL file in `db/migrations`, for example:

```text
0003_add_job_locations.sql
```

Then run `docker compose run --rm migrate`. Each file is applied once inside a
transaction and recorded in `schema_migrations`.

The migrations create the canonical job tables, seed the sources and
occupational tracks, add conservative missing-job tracking, and store private
newsletter subscribers plus their track preferences. Subscriber rows are never
available through a public list endpoint. See
[`docs/CANONICAL_JOB_CONTRACT.md`](../docs/CANONICAL_JOB_CONTRACT.md) for field
and lifecycle definitions.
