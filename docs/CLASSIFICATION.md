# Occupational Track Classification

**Taxonomy version:** 1.1  
**Classifier version:** `rules-1.3.0`

The classification layer converts source-specific categories, job families,
departments, and titles into a shared set of occupational tracks. It is a
navigation aid, not an eligibility decision or a claim that a worker qualifies
for a posting.

## How classification works

Classification is deterministic and runs in this order:

1. Apply high-confidence mappings from strong native source categories.
2. Apply explicit regular-expression rules to title, source category, and
   source department.
3. Apply a small set of conservative description fallbacks for specialized
   terms not found in structured fields.
4. Rank the resulting tracks by confidence.
5. Store at most three tracks, with exactly one primary track.
6. Flag close primary/secondary scores or low-confidence results for review.

Every assignment records:

- Primary or secondary status
- Confidence from zero to one
- Method: `source_map` or `rule`
- Matching evidence and rule identifier
- Taxonomy and classifier version
- Review status

The employer's original category and department remain on the canonical job.
Classification does not replace or rewrite source facts.

## Current tracks

1. Administrative and office support
2. IT, data, and cybersecurity
3. Transportation, logistics, and fleet
4. Engineering, architecture, and planning
5. Construction, skilled trades, and facilities
6. Customer service
7. Communications and marketing
8. Clinical and patient support
9. Education and student services
10. Finance, purchasing, and accounting
11. Legal, compliance, and policy
12. Food service, hospitality, and tourism
13. Social services and community support
14. Public safety and security
15. Management and supervision
16. Apprenticeships and entry-level training

Engineering and legal were added in taxonomy 1.1 after reviewing the first four
sources. Without them, professional engineers and attorneys would have been
forced into misleading administrative or skilled-trades categories.

## Examples

| Job | Primary | Secondary |
|---|---|---|
| MTA Database Administrator Intern | IT, data, and cybersecurity | Entry-level training; Administrative support |
| MTA Director, Legal Operations | Legal, compliance, and policy | Administrative support; Management |
| Port Authority Staff Financial Analyst | Finance, purchasing, and accounting | None |
| Port Authority Cloud Architect & Program Manager | IT, data, and cybersecurity | Engineering; Management |
| NYSDOL electrician apprenticeship | Apprenticeships and entry-level training | Construction and skilled trades |
| Amtrak railroad operations job | Transportation, logistics, and fleet | Title-dependent |
| Northwell clinical support job | Clinical and patient support | Title-dependent |
| CUNY IT posting | IT, data, and cybersecurity | Title-dependent |
| Resorts World facilities posting | Construction, skilled trades, and facilities | Title-dependent |

## Commands

Preview proposed assignments without changing PostgreSQL:

```bash
docker compose run --rm worker python -m app.cli classify --dry-run
```

Classify all active jobs:

```bash
docker compose run --rm worker python -m app.cli classify
```

Classify one source:

```bash
docker compose run --rm worker python -m app.cli classify \
  --source port_authority
```

Include inactive historical jobs:

```bash
docker compose run --rm worker python -m app.cli classify \
  --include-inactive
```

Repeated runs are idempotent. If the proposed assignments are unchanged, the
database rows are not rewritten.

## Human overrides

Any job with a `job_tracks` row whose method is `human` is skipped by automated
classification. This deliberately favors a human correction over every source
mapping, keyword rule, or future model result.

A future review screen should let an authorized reviewer:

- Approve or reject proposed assignments
- Change the primary track
- Add or remove secondary tracks
- Record their identity and review time
- Reopen a job for automated classification when appropriate

The command-line classifier does not manufacture human approvals.

## Review queue

The CLI reports `needs_review_samples` for jobs where:

- The primary confidence is below `0.750`, or
- The top two track scores differ by less than `0.025`

Unclassified jobs are also reported with source, external ID, and title. These
counts are intentionally reported at run time rather than documented as a
fixed property of the changing live catalog.

## Updating rules

Rules live in [`app/classification.py`](../app/classification.py). When changing
them:

1. Increment `CLASSIFIER_VERSION`.
2. Add a regression test for the motivating job title or category.
3. Run the complete unit test suite.
4. Run `classify --dry-run` and review count changes and samples.
5. Apply classification only after the audit is reasonable.

Add or rename tracks through a database migration and increment
`TAXONOMY_VERSION`. Do not silently recycle an existing track slug for a new
meaning.
