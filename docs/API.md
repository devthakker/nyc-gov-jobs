# Job Tracks API

The local API exposes normalized jobs, occupational tracks, source health, and
aggregate counts without exposing scraper payloads. It also provides one
narrowly scoped newsletter signup operation. It is versioned under `/api/v1`
and publishes an OpenAPI 3 document.

## Start the API

From the project directory:

```bash
docker compose up -d postgres api
```

The service is available only on the local machine:

- API root: <http://localhost:8000/>
- Interactive documentation: <http://localhost:8000/docs>
- Alternative documentation: <http://localhost:8000/redoc>
- OpenAPI JSON: <http://localhost:8000/openapi.json>
- Health check: <http://localhost:8000/api/v1/health>

The API container runs as an unprivileged user with a read-only filesystem and
drops Linux capabilities. Catalog repositories open PostgreSQL sessions with
`default_transaction_read_only=on` and a five-second statement timeout. A
separate, narrowly scoped repository performs only subscriber preference
upserts. The database URL is supplied through Docker Compose; no package is
installed on the host system.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Verify API connectivity and read-only DB mode |
| `GET` | `/api/v1/jobs` | Search, filter, sort, and paginate jobs |
| `GET` | `/api/v1/jobs/{job_id}` | Retrieve one normalized job |
| `GET` | `/api/v1/tracks` | List tracks and active-job counts |
| `GET` | `/api/v1/sources` | List enabled sources and sync health |
| `GET` | `/api/v1/stats` | Retrieve aggregate catalog statistics |
| `POST` | `/api/v1/newsletter/subscriptions` | Create or update delivery preferences |

Job data has no create, update, or delete endpoint. Unknown methods return
`405`. Response models remove internal `raw_payload`, `source_metadata`,
classifier reasons, and reviewer identities. Subscriber records have no public
list or detail endpoint.

## Newsletter subscription request

`POST /api/v1/newsletter/subscriptions` accepts:

- `email`: required valid email; normalized to lowercase
- `name`: optional, up to 100 characters
- `frequency`: currently the literal `weekly`
- `all_tracks`: `true` for the complete index, otherwise `false`
- `track_slugs`: empty for all tracks; otherwise one or more active track slugs
- `consent`: must be the literal `true`

The endpoint returns `201` when an address is first created and `200` when its
preferences are updated. Reusing an email never creates a duplicate. Example:

```bash
curl -X POST "http://localhost:8000/api/v1/newsletter/subscriptions" \
  -H "Content-Type: application/json" \
  -d '{"email":"preview@example.com","name":"Preview","frequency":"weekly","all_tracks":false,"track_slugs":["it-data-cybersecurity"],"consent":true}'
```

## Job query parameters

`GET /api/v1/jobs` accepts:

- `q`: PostgreSQL full-text search, 2–200 characters
- `track`: track slug; repeat to match any of several tracks
- `source`: source key; repeat to match any of several sources
- `state`: two-letter state code; repeat to match several states
- `status`: `active`, `expired`, `removed`, or `unknown`; defaults to `active`
- `work_mode`: `on_site`, `hybrid`, `remote`, or `unknown`
- `salary_available`: `true` or `false`
- `posted_since`: ISO date such as `2026-08-01`
- `primary_track_only`: require a matching primary assignment
- `sort`: `newest`, `oldest`, `title`, `closing_soon`, `salary_desc`, or
  `relevance`
- `page`: one-based page number
- `page_size`: 1–100; defaults to 20

Unknown parameters and invalid values return a structured `422` response.

Examples:

```bash
curl "http://localhost:8000/api/v1/jobs?page_size=5"
```

```bash
curl "http://localhost:8000/api/v1/jobs?q=help%20desk&sort=relevance"
```

```bash
curl "http://localhost:8000/api/v1/jobs?track=it-data-cybersecurity&state=NY&salary_available=true"
```

```bash
curl "http://localhost:8000/api/v1/jobs?track=customer-service&track=administrative-office-support"
```

List disabled and future sources as well as enabled sources:

```bash
curl "http://localhost:8000/api/v1/sources?enabled_only=false"
```

Include tracks that currently have no active jobs:

```bash
curl "http://localhost:8000/api/v1/tracks?include_empty=true"
```

## Tests

The regular suite uses dependency-injected repositories and does not require a
database:

```bash
docker compose run --rm --no-deps api python -m unittest discover -v
```

Run the API tests, including PostgreSQL integration and read-only enforcement:

```bash
docker compose run --rm -e RUN_DB_INTEGRATION=1 api \
  python -m unittest discover -s tests/api -t . -v
```

Compile-check the source tree:

```bash
python3 -m compileall -q app tests
```

## Configuration

The optional `.env` settings are:

| Variable | Default | Meaning |
| --- | --- | --- |
| `API_PORT` | `8000` | Host port bound to `127.0.0.1` |
| `API_STATEMENT_TIMEOUT_MS` | `5000` | PostgreSQL statement timeout |
| `API_CORS_ORIGINS` | local port 4000 origins | Comma-separated browser origins |

After changing Python dependencies, rebuild with:

```bash
docker compose build api worker
```
