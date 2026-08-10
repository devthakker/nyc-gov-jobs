# Job Tracks website

The website is a React and TypeScript client for the versioned Job Tracks API.
It lives entirely in this directory; packages are installed locally or in the
Docker image, never globally.

## Run with Docker

From the repository root:

```bash
docker compose up -d postgres api web
```

Open <http://localhost:4000>. Vite proxies `/api` requests to the internal API
container, so the browser never connects to PostgreSQL and does not need a
cross-origin URL.

The main route is the searchable opportunity index, `/jobs/:jobId` is a job
file, and `/newsletter` creates or updates weekly delivery preferences. Signup
supports the full index or a selected set of occupational tracks.

Stop or restart only the site:

```bash
docker compose stop web
docker compose restart web
```

## Tests and builds

Run the frontend test suite in Docker:

```bash
docker compose run --rm --no-deps web npm test
```

Type-check and create a production bundle:

```bash
docker compose run --rm --no-deps web npm run build
```

Regenerate the checked-in TypeScript API contract after changing FastAPI
request or response models:

```bash
cd web
npm ci
npm run generate:api
```

That command expects the API at <http://localhost:8000/openapi.json>.

## Source organization

```text
src/
├── api/          # Generated schema and typed fetch client
├── components/   # Reusable filters, cards, navigation, and states
├── lib/          # URL-state and display helpers
├── pages/        # Search index, job detail, newsletter, and not-found routes
└── test/         # Shared typed fixtures and test setup
```

Search filters are stored in the URL so filtered result sets remain shareable
and browser navigation works naturally. External applications always open on
the official employer site.
