# Canonical Job Contract

**Version:** 1.0  
**Status:** Locked for the foundation pilot  
**Last updated:** August 9, 2026

This document defines the shared record produced by every job-source adapter.
Source adapters may collect additional fields, but they must normalize into this
contract before writing to PostgreSQL.

Schema changes after version 1.0 must be made through a database migration and a
contract update. Scrapers must not create source-specific columns directly.

## Design principles

1. The employer's posting is authoritative.
2. Preserve source facts separately from system inferences.
3. Unknown means unknown; missing data never means “not required.”
4. A job may belong to multiple occupational tracks.
5. Repeated syncs must be idempotent.
6. Source failures must not cause valid jobs to disappear.
7. Store raw values when normalization could lose meaning.
8. Historical changes remain auditable.

## Identity

Every job is uniquely identified by `(source_id, external_id)`.

- `source_id` identifies the adapter/source configuration.
- `external_id` is the stable ID published by the source.
- If a source publishes no ID, the adapter creates a deterministic ID from the
  most stable source attributes available, normally the canonical URL. The
  fallback algorithm and its version must be documented by that adapter.
- A URL is not the database primary key because employers can change URLs while
  keeping the same requisition.
- Cross-source duplicates are flagged for review but are not automatically
  merged during the pilot.

The database uses an internal UUID `jobs.id` for relationships.

## Canonical job fields

### Source and identity

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `source_id` | UUID | Yes | Source adapter/configuration that observed the job |
| `employer_id` | UUID | No | Normalized employer; may be unknown on first observation |
| `external_id` | Text | Yes | Stable source-provided or deterministic fallback ID |
| `canonical_url` | URL text | Yes | Authoritative public job-detail page |
| `apply_url` | URL text | No | Direct public application URL, when different |

### Source-provided content

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `title` | Text | Yes | Title exactly as published, whitespace-normalized |
| `normalized_title` | Text | No | Search/deduplication form; never displayed as source text |
| `summary` | Text | No | Short source summary or conservative extracted summary |
| `description_text` | Text | No | Readable job description |
| `requirements_text` | Text | No | Readable qualifications/requirements section |
| `requirements` | JSON array | No | Structured requirements explicitly supported by source text |
| `source_category` | Text | No | Employer's category or job family |
| `source_department` | Text | No | Employer's department or business unit |
| `source_agency` | Text | No | Agency/campus/subsidiary when distinct from employer |

### Location

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `location_text` | Text | No | Location exactly as published |
| `city` | Text | No | Parsed city |
| `borough` | Text | No | NYC borough, when explicitly known |
| `region` | Text | No | Workforce/NYS region or multi-location label |
| `state` | Text | No | Two-character state code where confidently known |
| `postal_code` | Text | No | Postal code as text to preserve leading zeroes |

Multiple locations that cannot be represented safely in the scalar fields stay
in `location_text` and `source_metadata`. A later migration can introduce a
normalized job-locations table if the pilot demonstrates the need.

### Compensation and work arrangement

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `salary_min` | Decimal | No | Normalized lower bound |
| `salary_max` | Decimal | No | Normalized upper bound |
| `salary_currency` | ISO code | No | Normally `USD` |
| `salary_period` | Enum-like text | No | `hour`, `day`, `week`, `month`, `year`, or `other` |
| `salary_raw` | Text | No | Original salary statement |
| `employment_type` | Text | No | Full-time, part-time, per diem, temporary, seasonal, etc. |
| `schedule` | Text | No | Shift/schedule language as published |
| `work_mode` | Enum-like text | No | `on_site`, `hybrid`, `remote`, or `unknown` |

Do not calculate annualized compensation during ingestion. Raw and normalized
salary fields must remain traceable to source text.

### Experience and eligibility

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `experience_level` | Text | No | Source-provided or conservatively normalized level |
| `experience_years_min` | Decimal | No | Explicit minimum years only |
| `education_level` | Text | No | Explicit minimum education level |
| `licenses` | JSON array | No | Explicit licenses/certifications with optional required flag |

### Dates and lifecycle

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `posted_at` | Timestamp | No | Source posting time/date |
| `opens_on` | Date | No | Application opening date |
| `closes_on` | Date | No | Application deadline |
| `status` | Enum-like text | Yes | `active`, `expired`, `removed`, or `unknown` |
| `first_seen_at` | Timestamp | Yes | First successful observation |
| `last_seen_at` | Timestamp | Yes | Most recent successful observation |
| `last_changed_at` | Timestamp | Yes | Most recent material normalized change |
| `consecutive_misses` | Integer | Yes | Complete successful snapshots that did not contain the job |
| `missing_since_at` | Timestamp | No | First complete-snapshot miss in the current missing sequence |

### Provenance and change detection

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `content_hash` | SHA-256 text | Yes | Hash of material normalized fields |
| `raw_payload` | JSON object | Yes | Source facts/raw values needed for audit and reparsing |
| `source_metadata` | JSON object | Yes | Noncanonical source fields, request metadata, and parser notes |

The content hash excludes observation timestamps, request timing, and other
volatile transport metadata. A changed content hash creates a `job_versions`
record.

## Null and empty-value rules

- Use SQL `NULL` when a scalar value is absent or cannot be determined safely.
- Use an empty JSON array only when parsing completed and produced no elements.
- Do not store empty strings; normalize them to `NULL`.
- Preserve malformed source values in `raw_payload` even when their normalized
  field is `NULL`.
- Boolean-like facts should be added only when a source explicitly supports
  them. Absence of a driver's-license statement is not `false`.

## Job lifecycle

1. **First observation:** insert the job as `active` unless source facts already
   prove it expired; create its first version.
2. **Unchanged observation:** update `last_seen_at`; do not create a version.
3. **Changed observation:** update canonical fields and `last_changed_at`; insert
   a version containing the normalized snapshot and changed fields.
4. **Explicit deadline:** set `expired` after `closes_on` passes unless the source
   clearly says the opportunity remains open.
5. **Missing observation:** do not remove immediately. Mark `removed` only after
   the source has completed at least three successful syncs during a configured
   grace period without seeing the job.
6. **Failed/partial sync:** never use that run as evidence that a job was removed.
7. **Reappearance:** return a removed/expired job to `active` only when a current
   source observation supports it; retain its history.

## Occupational-track assignments

`job_tracks` is a many-to-many relationship. Each assignment stores:

- Track
- Whether it is the primary display track
- Confidence from 0 to 1
- Method: `source_map`, `rule`, `model`, or `human`
- Short evidence/reason
- Taxonomy version
- Review status

At most one track is primary for a job. Human-reviewed assignments override
automated assignments until explicitly reopened for review.

## Initial occupational tracks

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

The occupational taxonomy is version 1.1. Engineering and legal were added
after reviewing live jobs from the four representative pilot sources.

## Version 1.0 decisions intentionally deferred

- Normalized multi-location child records
- O*NET/SOC occupation codes
- Skills extraction and training-program matching
- Benefits normalization
- Subscriber profiles and production email consent records
- Automatic cross-source merging
- Model-assisted classification implementation

These should be added only after real data from the first four adapters shows
which representations are necessary.
