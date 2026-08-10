# Job Tracks opportunity pilot

Local occupational-track job index, subscriber signup, and weekly opportunity
dispatch. The pilot grew from a dependency-free scraper for the [New York State
Department of Labor apprenticeship announcements](https://dol.ny.gov/apprenticeship/apprenticeship-announcements)
and now normalizes several public employers into PostgreSQL.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the complete implemented
system, data flows, repository map, local services, operating procedures,
security boundaries, and production gaps.

See [COMMANDS.md](COMMANDS.md) for a copy-paste command reference covering
Docker, database migrations, every implemented adapter, tests, and Mailpit.

See [docs/CLASSIFICATION.md](docs/CLASSIFICATION.md) for the occupational-track
taxonomy, deterministic rules, review behavior, and human-override policy.

See [docs/API.md](docs/API.md) for the versioned HTTP API, its request and
response contracts, filters, newsletter signup boundary, security posture, and
test commands.

## Jobs API and newsletter signup

Start the local API and PostgreSQL:

```bash
docker compose up -d postgres api
```

Browse the generated API documentation at <http://localhost:8000/docs>, or
request the active job catalog directly:

```bash
curl "http://localhost:8000/api/v1/jobs?page_size=5"
```

The API runs in a hardened, read-only filesystem container. Every job-catalog
query uses a PostgreSQL session that enforces read-only mode. The only public
write is `POST /api/v1/newsletter/subscriptions`, a narrow subscriber-preference
operation with typed validation, explicit consent, normalized email addresses,
and idempotent preference updates. There is no public subscriber-list endpoint.

## Local job-search website

Start the complete local stack:

```bash
docker compose up -d postgres api web
```

Open <http://localhost:4000>. The site provides live keyword
search, occupational-track and employer filters, location and salary controls,
sorting, pagination, responsive job cards, detailed job files, and official
application links. Filter selections are stored in the URL so searches can be
bookmarked and shared. The `/newsletter` route lets readers subscribe to the
full weekly index or choose specific career tracks.

The React and TypeScript application is contained in [`web/`](web/); see
[`web/README.md`](web/README.md) for its architecture and test commands.

## Local pilot database

The canonical job contract is defined in
[`docs/CANONICAL_JOB_CONTRACT.md`](docs/CANONICAL_JOB_CONTRACT.md). Start the
Dockerized PostgreSQL database and apply its versioned migrations with:

```bash
docker compose up -d postgres
docker compose run --rm migrate
```

The database listens on `127.0.0.1:5433` and persists in a named Docker volume.
See [`db/README.md`](db/README.md) for schema and operator details.

## Synchronize job sources into PostgreSQL

The ingestion worker and its pinned Psycopg dependency run inside Docker; no
Python package is installed globally. Import the existing scraper export with:

```bash
docker compose run --rm worker python -m app.cli import-json \
  --source nysdol_apprenticeships \
  --path nysdol-export.json
```

Run a complete live sync with detail pages:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source nysdol_apprenticeships
```

The second adapter ingests NYC civil-service openings through the public
SmartRecruiters Posting API used by NYC City Jobs. A full sync follows the API's
pagination and enriches each result with its complete description and minimum
qualifications:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source nyc_jobs
```

Use `--listing-only` for a much faster NYC freshness pass. Listing responses
still include the Job ID, agency, category, experience level, borough, work
location, salary, closing date, and preferred skills; existing full descriptions
and qualifications remain intact in PostgreSQL.

The MTA adapter reads the public Jobvite-hosted MTA board, then visits each
posting for the MTA job ID, agency, department, description, requirements,
salary, shift, and closing date:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source mta
```

MTA's primary careers search currently blocks non-browser HTTP clients. The
public Jobvite board is a clean, directly readable source, but its visible count
must be monitored against the primary portal before the pilot claims complete
MTA coverage. On August 9, 2026, the two interfaces showed 218 and 334 openings,
respectively. The adapter records the Jobvite-board count in each sync run.

The Port Authority adapter also uses its official public Jobvite board. During
implementation on August 9, 2026, its 21 listings matched the 21 jobs visible on
the branded Port Authority portal. It captures the Port Authority job ID, native
job family, NY/NJ location, posting date, employment type, full description,
qualifications, work-mode language, and published compensation:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source port_authority
```

The branded portal publishes a department field that the public Jobvite board
does not expose. The adapter leaves department empty rather than inferring it.

Wave 1 adds NewYork-Presbyterian and StateJobsNY. The NYP adapter follows every
page of the official TalentBrew search, then reads each posting's structured
JobPosting data and official Workday apply link:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source newyork_presbyterian
```

The StateJobsNY adapter reads the complete public vacancy table and enriches
each row with its occupational category, salary, schedule, location, duties,
minimum qualifications, and application deadline:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source statejobsny
```

StateJobsNY publishes a large statewide catalog. Use `--listing-only` for a
quick complete inventory or `--limit 2` while testing detail extraction.

Wave 2 adds Amtrak and Northwell Health. The Amtrak adapter paginates the
official SuccessFactors board, enriches postings from their public detail
pages, and cross-references Amtrak's official job-family boards for native
occupational categories:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source amtrak
```

The Northwell adapter paginates the public careers search API used by the
official Northwell job-search page. Its search response already includes the
description, qualifications, facility, schedule, salary, location, and official
application link, so it does not need a separate detail request per job:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source northwell
```

Both adapters validate the source-reported count before a complete run can
reconcile missing jobs. Use `--limit 3` for a non-reconciling smoke test.

The final adapter wave adds CUNY and Resorts World New York City. CUNY reads
the official jobs sitemap and enriches every listing from the public job data
used by the CUNY careers site:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source cuny
```

The Resorts World adapter paginates the official Workday careers API, follows
each posting for its full description and requirements, and retains the native
Workday job category for occupational-track classification:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source resorts_world_nyc
```

Both final-wave adapters validate the provider's complete reported inventory
before missing-job reconciliation is allowed.

For a faster completeness/freshness pass that preserves details already in the
database, use any implemented source key with:

```bash
docker compose run --rm worker python -m app.cli sync \
  --source mta \
  --listing-only
```

Use `--limit 2` for development. Limited runs and JSON imports never mark unseen
jobs missing. Missing-job reconciliation runs only after a complete, successful
live snapshot whose discovered count matches the source-reported count.

The worker records each attempt in `sync_runs`, performs idempotent upserts by
source/external ID, creates `job_versions` only for material changes, and waits
for three complete misses plus a 48-hour grace period before marking a job
removed.

## Classify jobs into occupational tracks

Preview the versioned, deterministic classification rules without changing the
database:

```bash
docker compose run --rm worker python -m app.cli classify --dry-run
```

Persist primary and secondary track assignments for all active jobs:

```bash
docker compose run --rm worker python -m app.cli classify
```

Assignments retain their confidence, matching evidence, method, taxonomy
version, and review status. Automated runs never replace a human assignment.

## Test the opportunity dispatch locally with Mailpit

[Mailpit](https://mailpit.axllent.org/) is a local SMTP inbox: the newsletter is
sent normally over SMTP, but Mailpit captures it instead of delivering it to a
real address.

Start Mailpit and render a database-backed HTML preview:

```bash
docker compose up -d mailpit
docker compose run --rm worker python -m app.newsletter preview --max-jobs 20
```

Send a one-recipient test message to Mailpit:

```bash
docker compose run --rm worker python -m app.newsletter send \
  --to preview@example.com \
  --max-jobs 20
```

Then open [http://localhost:8026](http://localhost:8026). Mailpit accepts the
message without delivering it to the public internet. The preview command saves
`newsletter-preview.html` in the project root.

Useful newsletter options:

```bash
# Preview a focused career-track edition
docker compose run --rm worker python -m app.newsletter preview \
  --track it-data-cybersecurity \
  --output newsletter-preview.html

# Send to every active subscriber saved by the website
docker compose run --rm worker python -m app.newsletter send

# Show command options
docker compose run --rm worker python -m app.newsletter preview --help
docker compose run --rm worker python -m app.newsletter send --help
```

Stop Mailpit without deleting its local inbox:

```bash
docker compose stop mailpit
```

To use a real SMTP service later, set `SMTP_HOST`, `SMTP_PORT`,
`SMTP_SECURITY` (`none`, `starttls`, or `ssl`), `SMTP_USERNAME`, and
`SMTP_PASSWORD`. The sender can be set with `NEWSLETTER_FROM`. Mailpit is only a
development inbox and does not deliver mail to the public internet.

## Fields

The output includes the announcement title and URL, NY regions, posting/opening/
closing dates (both normalized ISO dates and the site's raw values), location,
subtitle, full readable description, source HTML, and a structured requirements
list. JSON also includes scrape metadata. Array-valued fields are JSON-encoded
inside CSV cells.

The source site occasionally contains malformed date text. In that case the raw
value is preserved and the corresponding normalized date is `null`/blank.
