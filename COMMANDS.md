# Job Tracks Pilot — Command Reference

This file collects the commands used to operate the local scraper, PostgreSQL
database, and Mailpit newsletter test environment.

Run commands from the project directory:

```bash
cd "/Users/devin/Documents/GitHub/ula-demo"
```

## First-time setup

Create the local environment file once. Do not run this again if you have
already customized `.env`.

```bash
cp .env.example .env
```

Build the Python worker image:

```bash
docker compose build worker
```

Start PostgreSQL and apply all database migrations:

```bash
docker compose up -d postgres
docker compose run --rm migrate
```

## Start, stop, and restart Docker services

Start PostgreSQL, the jobs API, website, and Mailpit:

```bash
docker compose up -d postgres api web mailpit
```

Check service status:

```bash
docker compose ps
```

Stop the containers while preserving them and their data:

```bash
docker compose stop
```

Start those stopped containers again:

```bash
docker compose start
```

The following is the most reliable restart command. It starts existing
containers or recreates missing containers while retaining the named database
and Mailpit volumes:

```bash
docker compose up -d postgres api web mailpit
```

Stop and remove the containers without deleting their named data volumes:

```bash
docker compose down
```

After `docker compose down`, recreate the services with:

```bash
docker compose up -d postgres api web mailpit
docker compose run --rm migrate
```

View recent logs:

```bash
docker compose logs --tail 100 postgres
docker compose logs --tail 100 mailpit
docker compose logs --tail 100 api
docker compose logs --tail 100 web
```

Follow logs until pressing `Ctrl+C`:

```bash
docker compose logs -f postgres api web mailpit
```

## Jobs API and newsletter signup

Build and start the API:

```bash
docker compose build api
docker compose up -d postgres api
```

Open the interactive documentation:

- <http://localhost:8000/docs>

Check service health and fetch active jobs:

```bash
curl "http://localhost:8000/api/v1/health"
curl "http://localhost:8000/api/v1/jobs?page_size=5"
```

Search and filter by occupational track:

```bash
curl "http://localhost:8000/api/v1/jobs?q=help%20desk&sort=relevance"
curl "http://localhost:8000/api/v1/jobs?track=it-data-cybersecurity&state=NY"
```

Fetch tracks, source health, and catalog statistics:

```bash
curl "http://localhost:8000/api/v1/tracks"
curl "http://localhost:8000/api/v1/sources"
curl "http://localhost:8000/api/v1/stats"
```

Create or update a weekly all-tracks subscription:

```bash
curl -X POST "http://localhost:8000/api/v1/newsletter/subscriptions" \
  -H "Content-Type: application/json" \
  -d '{"email":"preview@example.com","name":"Preview","frequency":"weekly","all_tracks":true,"track_slugs":[],"consent":true}'
```

Create or update a focused subscription:

```bash
curl -X POST "http://localhost:8000/api/v1/newsletter/subscriptions" \
  -H "Content-Type: application/json" \
  -d '{"email":"preview@example.com","frequency":"weekly","all_tracks":false,"track_slugs":["it-data-cybersecurity","customer-service"],"consent":true}'
```

Restart or stop only the API:

```bash
docker compose restart api
docker compose stop api
```

## Job-search website

Build and start the website with its API and database:

```bash
docker compose build web
docker compose up -d postgres api web
```

Open the site:

- <http://localhost:4000>

Stop, start, restart, or inspect the website container:

```bash
docker compose stop web
docker compose start web
docker compose restart web
docker compose logs -f web
```

Run the frontend tests and production build inside Docker:

```bash
docker compose run --rm --no-deps web npm test
docker compose run --rm --no-deps web npm run build
```

Regenerate TypeScript API types after changing the FastAPI models:

```bash
docker run --rm --network ula-demo_default \
  -v "/Users/devin/Documents/GitHub/ula-demo/web:/app:rw" \
  -v ula-demo_web-node-modules:/app/node_modules \
  -w /app ula-demo-web \
  npx openapi-typescript http://api:8000/openapi.json -o src/api/schema.d.ts
```

## Database migrations

Apply any migrations that have not yet run:

```bash
docker compose run --rm migrate
```

List applied migrations:

```bash
docker compose exec postgres psql -U jobtracks -d jobtracks \
  -c "SELECT version, name, applied_at FROM schema_migrations ORDER BY version;"
```

Open an interactive PostgreSQL shell:

```bash
docker compose exec postgres psql -U jobtracks -d jobtracks
```

Exit the PostgreSQL shell with:

```text
\q
```

## Synchronize job sources

Run a complete NYSDOL apprenticeship sync:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source nysdol_apprenticeships
```

Run a complete NYC City Jobs sync:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source nyc_jobs
```

Run a complete MTA sync:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source mta
```

Run a complete Port Authority sync:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source port_authority
```

Run a complete NewYork-Presbyterian sync. This paginates the official search
and loads each public detail page:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source newyork_presbyterian
```

Run a complete StateJobsNY sync. This reads the statewide vacancy table and
then loads each vacancy detail page, so it can take several minutes:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source statejobsny
```

Run a complete Amtrak sync. This paginates the main board, maps official Amtrak
job families, and loads each posting's public detail page:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source amtrak
```

Run a complete Northwell Health sync. The official public search API already
contains detail-level job data:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source northwell
```

Run a complete CUNY sync. This reads the official sitemap and then loads the
public detail data for every listed job:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source cuny
```

Run a complete Resorts World NYC sync. This paginates the official Workday
board and loads each posting's detail response:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source resorts_world_nyc
```

Run a full refresh of all ten implemented sources, stopping immediately if a
source fails:

```bash
for source in \
  nysdol_apprenticeships nyc_jobs mta port_authority \
  newyork_presbyterian statejobsny amtrak northwell \
  cuny resorts_world_nyc
do
  docker compose run --rm worker python -m app.cli sync \
    --source "$source" || break
done
docker compose run --rm worker python -m app.cli classify
```

Each successful complete sync stores its source counts and completeness flag in
`sync_runs`. A failed or partial run does not reconcile unseen jobs.

Run small Wave 2 smoke tests without missing-job reconciliation:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source amtrak \
  --limit 3

docker compose run --rm worker python -m app.cli sync \
  --source northwell \
  --limit 3

docker compose run --rm worker python -m app.cli classify \
  --source amtrak

docker compose run --rm worker python -m app.cli classify \
  --source northwell
```

Run a quick Wave 1 listing inventory without detail-page requests:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source newyork_presbyterian \
  --listing-only

docker compose run --rm worker python -m app.cli sync \
  --source statejobsny \
  --listing-only
```

Run only two records while developing or testing:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source mta \
  --limit 2
```

Replace `mta` above with `amtrak`, `cuny`, `northwell`, `port_authority`,
`nyc_jobs`, `nysdol_apprenticeships`, `newyork_presbyterian`,
`resorts_world_nyc`, or `statejobsny` to test another implemented adapter.

Perform a faster listing-only refresh. Previously stored detail fields are
preserved in PostgreSQL:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source mta \
  --listing-only
```

Use fewer workers and a longer delay for a gentler collection rate:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source mta \
  --workers 2 \
  --delay 1
```

Show all ingestion command options:

```bash
docker compose run --rm worker python -m app.cli --help
docker compose run --rm worker python -m app.cli sync --help
```

## Import an existing NYSDOL JSON export

```bash
docker compose run --rm worker python -m app.cli import-json \
  --source nysdol_apprenticeships \
  --path nysdol-export.json
```

## Classify jobs into occupational tracks

Preview all active-job assignments without changing the database:

```bash
docker compose run --rm worker python -m app.cli classify --dry-run
```

Save primary and secondary track assignments:

```bash
docker compose run --rm worker python -m app.cli classify
```

Classify one source only:

```bash
docker compose run --rm worker python -m app.cli classify \
  --source port_authority
```

Include inactive historical jobs:

```bash
docker compose run --rm worker python -m app.cli classify \
  --include-inactive
```

Inspect the primary-track distribution:

```bash
docker compose exec postgres psql -U jobtracks -d jobtracks \
  -c "SELECT t.name AS primary_track, count(*) FROM job_tracks jt JOIN tracks t ON t.id = jt.track_id WHERE jt.is_primary GROUP BY t.name ORDER BY count(*) DESC, t.name;"
```

Show assignments requiring review:

```bash
docker compose exec postgres psql -U jobtracks -d jobtracks \
  -c "SELECT s.key, j.external_id, j.title, t.name, jt.confidence, jt.reason FROM job_tracks jt JOIN jobs j ON j.id = jt.job_id JOIN sources s ON s.id = j.source_id JOIN tracks t ON t.id = jt.track_id WHERE jt.review_status = 'needs_review' ORDER BY s.key, j.title, jt.is_primary DESC, jt.confidence DESC;"
```

## Inspect stored jobs and sync runs

Count jobs by source:

```bash
docker compose exec postgres psql -U jobtracks -d jobtracks \
  -c "SELECT s.key, count(j.id) AS jobs FROM sources s LEFT JOIN jobs j ON j.source_id = s.id GROUP BY s.key ORDER BY s.key;"
```

Show the latest synchronization runs:

```bash
docker compose exec postgres psql -U jobtracks -d jobtracks \
  -c "SELECT s.key, r.status, r.started_at, r.finished_at, r.discovered_count, r.inserted_count, r.updated_count, r.unchanged_count, r.failed_count FROM sync_runs r JOIN sources s ON s.id = r.source_id ORDER BY r.started_at DESC LIMIT 20;"
```

Show the locally stored MTA sample fields:

```bash
docker compose exec postgres psql -U jobtracks -d jobtracks \
  -c "SELECT j.external_id AS jobvite_id, j.source_metadata->>'mta_job_id' AS mta_job_id, j.title, j.source_agency, j.source_department, j.location_text, j.salary_raw FROM jobs j JOIN sources s ON s.id = j.source_id WHERE s.key = 'mta' ORDER BY j.title;"
```

## Run tests

Run the dependency-free unit tests directly on the host:

```bash
python3 -m unittest discover -v
```

Run the same tests in the worker container:

```bash
docker compose run --rm worker python -m unittest discover -v
```

Run all tests in the API image (database integration tests remain skipped):

```bash
docker compose run --rm --no-deps api python -m unittest discover -v
```

Run the API contract and live PostgreSQL integration tests, including explicit
verification that the query session rejects writes:

```bash
docker compose run --rm -e RUN_DB_INTEGRATION=1 api \
  python -m unittest discover -s tests/api -t . -v
```

Check that all Python files compile:

```bash
python3 -m compileall -q app tests
```

## Newsletter subscriptions and Mailpit

Start Mailpit:

```bash
docker compose up -d mailpit
```

Open the website signup page:

```bash
open http://localhost:4000/newsletter
```

Open the captured messages at:

- <http://localhost:8026>

Render the newest database jobs without sending email:

```bash
docker compose run --rm worker python -m app.newsletter preview \
  --max-jobs 20 \
  --output newsletter-preview.html
```

Render a preview for one or more occupational tracks:

```bash
docker compose run --rm worker python -m app.newsletter preview \
  --track it-data-cybersecurity \
  --track customer-service
```

Send one local-only test message into Mailpit:

```bash
docker compose run --rm worker python -m app.newsletter send \
  --to preview@example.com \
  --max-jobs 20
```

Send individualized editions to every active subscriber saved by the website:

```bash
docker compose run --rm worker python -m app.newsletter send
```

List subscriber counts and recent recorded newsletter issues:

```bash
docker compose exec postgres psql -U jobtracks -d jobtracks \
  -c "SELECT status, frequency, count(*) FROM newsletter_subscribers GROUP BY status, frequency ORDER BY status, frequency;"
docker compose exec postgres psql -U jobtracks -d jobtracks \
  -c "SELECT id, subject, status, recipient_count, rendered_at, sent_at FROM newsletter_issues ORDER BY created_at DESC LIMIT 10;"
```

Show every newsletter option:

```bash
docker compose run --rm worker python -m app.newsletter preview --help
docker compose run --rm worker python -m app.newsletter send --help
```

Stop only Mailpit while preserving its local inbox:

```bash
docker compose stop mailpit
```

## Real SMTP configuration

For a real SMTP provider, configure these environment variables in your shell
or secret manager. Do not commit real credentials to `.env` or the repository.

```text
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-username
SMTP_PASSWORD=your-password
NEWSLETTER_FROM=Job Tracks <dispatch@example.com>
```

You can also supply the non-secret connection settings as command options:

```bash
docker compose run --rm worker python -m app.newsletter send \
  --smtp-host smtp.example.com \
  --smtp-port 587 \
  --smtp-security starttls \
  --to recipient@example.com
```

## Destructive reset — use only intentionally

The following command deletes the PostgreSQL and Mailpit named volumes along
with all locally stored jobs and captured email. It is not needed for normal
stopping or restarting:

```bash
docker compose down -v
```

Use `docker compose stop` or `docker compose down` without `-v` when you want to
preserve local data.
