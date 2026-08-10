"""PostgreSQL persistence for canonical jobs and sync state."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain import CanonicalJob, MATERIAL_FIELDS, json_ready


JOB_COLUMNS = (
    "title",
    "normalized_title",
    "summary",
    "description_text",
    "requirements_text",
    "requirements",
    "canonical_url",
    "apply_url",
    "source_category",
    "source_department",
    "source_agency",
    "location_text",
    "city",
    "borough",
    "region",
    "state",
    "postal_code",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "salary_raw",
    "employment_type",
    "schedule",
    "work_mode",
    "experience_level",
    "experience_years_min",
    "education_level",
    "licenses",
    "posted_at",
    "opens_on",
    "closes_on",
    "status",
    "content_hash",
    "raw_payload",
    "source_metadata",
)

JSON_COLUMNS = {"requirements", "licenses", "raw_payload", "source_metadata"}


class JobRepository:
    def __init__(self, database_url: str) -> None:
        self.connection = psycopg.connect(
            database_url,
            autocommit=True,
            row_factory=dict_row,
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "JobRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def jobs_for_classification(
        self,
        *,
        source_key: str | None = None,
        active_only: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if source_key:
            conditions.append("s.key = %s")
            parameters.append(source_key)
        if active_only:
            conditions.append("j.status = 'active'")
            conditions.append("(j.closes_on IS NULL OR j.closes_on >= CURRENT_DATE)")
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT %s"
            parameters.append(limit)
        return list(
            self.connection.execute(
                f"""
                SELECT j.id, s.key AS source_key, j.external_id, j.title,
                       j.summary, j.description_text, j.source_category,
                       j.source_department, j.source_agency, j.status
                FROM jobs j
                JOIN sources s ON s.id = j.source_id
                {where_sql}
                ORDER BY s.key, j.title, j.external_id
                {limit_sql}
                """,
                parameters,
            ).fetchall()
        )

    def replace_automated_job_tracks(
        self,
        job_id: UUID,
        assignments: Sequence[dict[str, Any]],
    ) -> str:
        """Replace automated assignments while preserving every human decision."""

        with self.connection.transaction():
            human = self.connection.execute(
                "SELECT 1 FROM job_tracks WHERE job_id = %s AND method = 'human' LIMIT 1",
                (job_id,),
            ).fetchone()
            if human is not None:
                return "skipped_human"

            track_rows = self.connection.execute(
                "SELECT id, slug FROM tracks WHERE active"
            ).fetchall()
            track_ids = {row["slug"]: row["id"] for row in track_rows}
            unknown = sorted(
                {
                    str(assignment["track_slug"])
                    for assignment in assignments
                    if assignment["track_slug"] not in track_ids
                }
            )
            if unknown:
                raise RuntimeError(f"Classifier returned unknown track(s): {', '.join(unknown)}")

            existing_rows = self.connection.execute(
                """
                SELECT t.slug AS track_slug, jt.is_primary, jt.confidence,
                       jt.method, jt.reason, jt.taxonomy_version, jt.review_status
                FROM job_tracks jt
                JOIN tracks t ON t.id = jt.track_id
                WHERE jt.job_id = %s AND jt.method <> 'human'
                ORDER BY t.slug
                """,
                (job_id,),
            ).fetchall()

            def comparable(item: dict[str, Any]) -> tuple[Any, ...]:
                return (
                    str(item["track_slug"]),
                    bool(item["is_primary"]),
                    round(float(item["confidence"]), 3),
                    str(item["method"]),
                    item.get("reason"),
                    str(item["taxonomy_version"]),
                    str(item["review_status"]),
                )

            existing_values = sorted(comparable(dict(row)) for row in existing_rows)
            proposed_values = sorted(comparable(dict(item)) for item in assignments)
            if existing_values == proposed_values:
                return "unchanged"

            self.connection.execute(
                "DELETE FROM job_tracks WHERE job_id = %s AND method <> 'human'",
                (job_id,),
            )
            for assignment in assignments:
                self.connection.execute(
                    """
                    INSERT INTO job_tracks (
                        job_id, track_id, is_primary, confidence, method, reason,
                        taxonomy_version, review_status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        job_id,
                        track_ids[assignment["track_slug"]],
                        assignment["is_primary"],
                        assignment["confidence"],
                        assignment["method"],
                        assignment["reason"],
                        assignment["taxonomy_version"],
                        assignment["review_status"],
                    ),
                )
        return "classified" if assignments else "unclassified"

    def begin_sync(self, source_key: str, adapter_version: str) -> tuple[UUID, UUID, datetime]:
        with self.connection.transaction():
            source = self.connection.execute(
                """
                UPDATE sources
                SET last_attempt_at = now(), adapter_version = %s
                WHERE key = %s
                RETURNING id
                """,
                (adapter_version, source_key),
            ).fetchone()
            if source is None:
                raise RuntimeError(f"Source is not seeded in the database: {source_key}")
            run = self.connection.execute(
                """
                INSERT INTO sync_runs (source_id)
                VALUES (%s)
                RETURNING id, started_at
                """,
                (source["id"],),
            ).fetchone()
            assert run is not None
            return run["id"], source["id"], run["started_at"]

    def _upsert_employer(self, name: str) -> UUID:
        normalized = " ".join(name.casefold().split())
        row = self.connection.execute(
            """
            INSERT INTO employers (name, normalized_name)
            VALUES (%s, %s)
            ON CONFLICT (normalized_name) DO UPDATE
            SET name = EXCLUDED.name
            RETURNING id
            """,
            (name, normalized),
        ).fetchone()
        assert row is not None
        return row["id"]

    @staticmethod
    def _merge_listing_only(job: CanonicalJob, existing: dict[str, Any]) -> CanonicalJob:
        if job.source_metadata.get("details_included", True):
            return job
        preserved: dict[str, Any] = {}
        for field_name in MATERIAL_FIELDS:
            incoming = getattr(job, field_name)
            missing = incoming is None or (
                field_name in {"requirements", "licenses"} and not incoming
            )
            if missing and existing.get(field_name) is not None:
                preserved[field_name] = existing[field_name]

        # Some adapters must emit a generic fallback for required canonical
        # fields when no detail page is fetched. They can name those fields
        # explicitly so the fallback does not overwrite a more specific value.
        preserve_fields = job.source_metadata.get("listing_only_preserve_fields", [])
        for field_name in preserve_fields:
            if field_name in MATERIAL_FIELDS and existing.get(field_name) is not None:
                preserved[field_name] = existing[field_name]

        existing_payload = existing.get("raw_payload")
        merged_payload = (
            {**existing_payload, **job.raw_payload}
            if isinstance(existing_payload, dict)
            else job.raw_payload
        )
        existing_metadata = existing.get("source_metadata")
        merged_metadata = dict(existing_metadata) if isinstance(existing_metadata, dict) else {}
        for key, value in job.source_metadata.items():
            if value is not None and value != {} and value != [] and value != "":
                merged_metadata[key] = value

        return replace(
            job,
            **preserved,
            raw_payload=merged_payload,
            source_metadata=merged_metadata,
        )

    @staticmethod
    def _existing_material(existing: dict[str, Any]) -> dict[str, Any]:
        return {name: json_ready(existing.get(name)) for name in MATERIAL_FIELDS}

    @staticmethod
    def _job_parameters(job: CanonicalJob) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for column in JOB_COLUMNS:
            value = job.content_hash if column == "content_hash" else getattr(job, column)
            if column in JSON_COLUMNS:
                values[column] = Jsonb(json_ready(value))
            else:
                values[column] = value.replace("\x00", "") if isinstance(value, str) else value
        return values

    def upsert_job(self, source_id: UUID, job: CanonicalJob) -> str:
        with self.connection.transaction():
            existing = self.connection.execute(
                """
                SELECT j.*, e.name AS employer_name
                FROM jobs j
                LEFT JOIN employers e ON e.id = j.employer_id
                WHERE j.source_id = %s AND j.external_id = %s
                FOR UPDATE OF j
                """,
                (source_id, job.external_id),
            ).fetchone()

            if existing is not None:
                job = self._merge_listing_only(job, existing)
            employer_id = self._upsert_employer(job.employer_name)
            parameters = {
                **self._job_parameters(job),
                "source_id": source_id,
                "employer_id": employer_id,
                "external_id": job.external_id.replace("\x00", ""),
                "observed_at": job.observed_at,
            }

            if existing is None:
                columns = ("source_id", "employer_id", "external_id", *JOB_COLUMNS)
                column_sql = ", ".join(columns)
                value_sql = ", ".join(f"%({column})s" for column in columns)
                inserted = self.connection.execute(
                    f"""
                    INSERT INTO jobs (
                        {column_sql}, first_seen_at, last_seen_at, last_changed_at
                    )
                    VALUES (
                        {value_sql}, %(observed_at)s, %(observed_at)s, %(observed_at)s
                    )
                    RETURNING id
                    """,
                    parameters,
                ).fetchone()
                assert inserted is not None
                self._insert_version(inserted["id"], job, ["initial"])
                return "inserted"

            if existing["content_hash"] == job.content_hash:
                self.connection.execute(
                    """
                    UPDATE jobs
                    SET last_seen_at = %(observed_at)s,
                        consecutive_misses = 0,
                        missing_since_at = NULL,
                        raw_payload = %(raw_payload)s,
                        source_metadata = %(source_metadata)s
                    WHERE id = %(job_id)s
                    """,
                    {**parameters, "job_id": existing["id"]},
                )
                return "unchanged"

            previous = self._existing_material(existing)
            current = job.material_snapshot()
            changed_fields = [name for name in MATERIAL_FIELDS if previous.get(name) != current.get(name)]
            assignment_sql = ", ".join(
                f"{column} = %({column})s" for column in JOB_COLUMNS
            )
            self.connection.execute(
                f"""
                UPDATE jobs
                SET employer_id = %(employer_id)s,
                    {assignment_sql},
                    last_seen_at = %(observed_at)s,
                    last_changed_at = %(observed_at)s,
                    consecutive_misses = 0,
                    missing_since_at = NULL
                WHERE id = %(job_id)s
                """,
                {**parameters, "job_id": existing["id"]},
            )
            self._insert_version(existing["id"], job, changed_fields)
            return "updated"

    def _insert_version(
        self,
        job_id: UUID,
        job: CanonicalJob,
        changed_fields: list[str],
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO job_versions (
                job_id, observed_at, content_hash, changed_fields,
                normalized_snapshot, raw_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                job.observed_at,
                job.content_hash,
                changed_fields,
                Jsonb(job.version_snapshot()),
                Jsonb(json_ready(job.raw_payload)),
            ),
        )

    def reconcile_missing(self, source_id: UUID, run_id: UUID) -> dict[str, int]:
        run = self.connection.execute(
            """
            SELECT sr.started_at,
                   COALESCE((s.configuration->>'removal_grace_runs')::integer, 3)
                       AS grace_runs,
                   COALESCE((s.configuration->>'removal_grace_hours')::integer, 48)
                       AS grace_hours
            FROM sync_runs sr
            JOIN sources s ON s.id = sr.source_id
            WHERE sr.id = %s AND sr.source_id = %s
            """,
            (run_id, source_id),
        ).fetchone()
        if run is None:
            raise RuntimeError(f"Sync run not found: {run_id}")

        with self.connection.transaction():
            result = self.connection.execute(
                """
                WITH updated AS (
                    UPDATE jobs
                    SET consecutive_misses = consecutive_misses + 1,
                        missing_since_at = COALESCE(missing_since_at, now()),
                        status = CASE
                            WHEN consecutive_misses + 1 >= %(grace_runs)s
                             AND COALESCE(missing_since_at, now()) <=
                                 now() - (%(grace_hours)s * interval '1 hour')
                            THEN 'removed'
                            ELSE status
                        END
                    WHERE source_id = %(source_id)s
                      AND last_seen_at < %(started_at)s
                      AND status NOT IN ('expired', 'removed')
                    RETURNING status
                )
                SELECT count(*)::integer AS missed,
                       count(*) FILTER (WHERE status = 'removed')::integer AS removed
                FROM updated
                """,
                {
                    "source_id": source_id,
                    "started_at": run["started_at"],
                    "grace_runs": run["grace_runs"],
                    "grace_hours": run["grace_hours"],
                },
            ).fetchone()
        assert result is not None
        return {"missed": result["missed"], "removed": result["removed"]}

    def finish_sync(
        self,
        *,
        run_id: UUID,
        source_id: UUID,
        status: str,
        counts: dict[str, int],
        diagnostics: dict[str, Any],
        reconcile: bool,
    ) -> dict[str, int]:
        missing = {"missed": 0, "removed": 0}
        if reconcile and status == "succeeded":
            missing = self.reconcile_missing(source_id, run_id)
        diagnostics = {**diagnostics, "missing_reconciliation": missing}
        with self.connection.transaction():
            self.connection.execute(
                """
                UPDATE sync_runs
                SET finished_at = now(),
                    status = %(status)s,
                    discovered_count = %(discovered)s,
                    inserted_count = %(inserted)s,
                    updated_count = %(updated)s,
                    unchanged_count = %(unchanged)s,
                    skipped_count = %(skipped)s,
                    failed_count = %(failed)s,
                    error_summary = %(error_summary)s,
                    diagnostics = %(diagnostics)s
                WHERE id = %(run_id)s
                """,
                {
                    **counts,
                    "run_id": run_id,
                    "status": status,
                    "error_summary": diagnostics.get("error_summary"),
                    "diagnostics": Jsonb(json_ready(diagnostics)),
                },
            )
            if status == "succeeded":
                self.connection.execute(
                    """
                    UPDATE sources
                    SET last_success_at = now(), consecutive_failures = 0
                    WHERE id = %s
                    """,
                    (source_id,),
                )
            elif status == "failed":
                self.connection.execute(
                    """
                    UPDATE sources
                    SET consecutive_failures = consecutive_failures + 1
                    WHERE id = %s
                    """,
                    (source_id,),
                )
        return missing

    def fail_sync(self, run_id: UUID, source_id: UUID, error: str) -> None:
        with self.connection.transaction():
            self.connection.execute(
                """
                UPDATE sync_runs
                SET finished_at = now(), status = 'failed',
                    failed_count = 1, error_summary = %s,
                    diagnostics = %s
                WHERE id = %s
                """,
                (error, Jsonb({"fatal_error": error}), run_id),
            )
            self.connection.execute(
                """
                UPDATE sources
                SET consecutive_failures = consecutive_failures + 1
                WHERE id = %s
                """,
                (source_id,),
            )
