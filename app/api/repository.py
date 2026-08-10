"""Read-only PostgreSQL queries used exclusively by the HTTP API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.api.models import JobQueryParams, JobSort


LIST_JOB_COLUMNS = """
    j.id, j.external_id, j.title, j.summary, j.canonical_url, j.apply_url,
    j.source_category, j.source_department, j.source_agency,
    j.location_text, j.city, j.borough, j.region, j.state, j.postal_code,
    j.salary_min, j.salary_max, j.salary_currency, j.salary_period, j.salary_raw,
    j.employment_type, j.schedule, j.work_mode, j.experience_level,
    j.posted_at, j.opens_on, j.closes_on, j.status,
    j.first_seen_at, j.last_seen_at, j.last_changed_at,
    s.key AS source_key, s.name AS source_name,
    s.last_success_at AS source_last_success_at,
    COALESCE(e.name, s.name) AS employer_name
"""


class ReadOnlyJobRepository:
    """Short-lived repository whose PostgreSQL session cannot write data."""

    def __init__(self, database_url: str, *, statement_timeout_ms: int = 5000) -> None:
        if statement_timeout_ms < 100:
            raise ValueError("statement_timeout_ms must be at least 100")
        self.connection = psycopg.connect(
            database_url,
            autocommit=True,
            row_factory=dict_row,
            application_name="jobtracks-read-api",
            options=(
                "-c default_transaction_read_only=on "
                f"-c statement_timeout={statement_timeout_ms}"
            ),
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ReadOnlyJobRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def health(self) -> bool:
        row = self.connection.execute(
            "SELECT current_setting('transaction_read_only') AS read_only"
        ).fetchone()
        return row is not None and row["read_only"] == "on"

    @staticmethod
    def _where(filters: JobQueryParams) -> tuple[str, list[Any]]:
        conditions: list[str] = []
        parameters: list[Any] = []

        statuses = [status.value for status in filters.status]
        conditions.append("j.status = ANY(%s::text[])")
        parameters.append(statuses)
        if "active" in statuses:
            conditions.append(
                "(j.status <> 'active' OR j.closes_on IS NULL OR j.closes_on >= CURRENT_DATE)"
            )
        if filters.q:
            conditions.append(
                "j.search_document @@ websearch_to_tsquery('english', %s)"
            )
            parameters.append(filters.q)
        if filters.track:
            primary_sql = "AND jt.is_primary" if filters.primary_track_only else ""
            conditions.append(
                f"""EXISTS (
                    SELECT 1
                    FROM job_tracks jt
                    JOIN tracks t ON t.id = jt.track_id
                    WHERE jt.job_id = j.id
                      AND t.slug = ANY(%s::text[])
                      {primary_sql}
                )"""
            )
            parameters.append(filters.track)
        if filters.source:
            conditions.append("s.key = ANY(%s::text[])")
            parameters.append(filters.source)
        if filters.state:
            conditions.append("j.state = ANY(%s::text[])")
            parameters.append(filters.state)
        if filters.work_mode:
            conditions.append("j.work_mode = ANY(%s::text[])")
            parameters.append([mode.value for mode in filters.work_mode])
        if filters.salary_available is True:
            conditions.append("(j.salary_min IS NOT NULL OR j.salary_max IS NOT NULL)")
        elif filters.salary_available is False:
            conditions.append("j.salary_min IS NULL AND j.salary_max IS NULL")
        if filters.posted_since:
            conditions.append("j.posted_at >= %s::date")
            parameters.append(filters.posted_since)

        return "WHERE " + " AND ".join(conditions), parameters

    @staticmethod
    def _order_by(filters: JobQueryParams) -> tuple[str, list[Any]]:
        newest = "COALESCE(j.posted_at, j.opens_on::timestamptz, j.first_seen_at)"
        if filters.sort == JobSort.OLDEST:
            return f"{newest} ASC, j.title ASC, j.id ASC", []
        if filters.sort == JobSort.TITLE:
            return "j.title ASC, j.id ASC", []
        if filters.sort == JobSort.CLOSING_SOON:
            return "j.closes_on ASC NULLS LAST, j.title ASC, j.id ASC", []
        if filters.sort == JobSort.SALARY_DESC:
            return (
                "COALESCE(j.salary_max, j.salary_min) DESC NULLS LAST, "
                "j.title ASC, j.id ASC",
                [],
            )
        if filters.sort == JobSort.RELEVANCE and filters.q:
            return (
                "ts_rank(j.search_document, websearch_to_tsquery('english', %s)) "
                f"DESC, {newest} DESC, j.id ASC",
                [filters.q],
            )
        return f"{newest} DESC, j.title ASC, j.id ASC", []

    def list_jobs(self, filters: JobQueryParams) -> tuple[list[dict[str, Any]], int]:
        where_sql, parameters = self._where(filters)
        order_sql, order_parameters = self._order_by(filters)
        count = self.connection.execute(
            f"""
            SELECT count(*) AS total
            FROM jobs j
            JOIN sources s ON s.id = j.source_id
            {where_sql}
            """,
            parameters,
        ).fetchone()
        total = int(count["total"]) if count is not None else 0

        rows = self.connection.execute(
            f"""
            SELECT {LIST_JOB_COLUMNS}
            FROM jobs j
            JOIN sources s ON s.id = j.source_id
            LEFT JOIN employers e ON e.id = j.employer_id
            {where_sql}
            ORDER BY {order_sql}
            LIMIT %s OFFSET %s
            """,
            [
                *parameters,
                *order_parameters,
                filters.page_size,
                (filters.page - 1) * filters.page_size,
            ],
        ).fetchall()
        jobs = [self._job_response(dict(row)) for row in rows]
        self._attach_tracks(jobs)
        return jobs, total

    def get_job(self, job_id: UUID) -> dict[str, Any] | None:
        row = self.connection.execute(
            f"""
            SELECT {LIST_JOB_COLUMNS},
                   j.description_text, j.requirements_text, j.requirements,
                   j.licenses, j.experience_years_min, j.education_level
            FROM jobs j
            JOIN sources s ON s.id = j.source_id
            LEFT JOIN employers e ON e.id = j.employer_id
            WHERE j.id = %s
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        job = self._job_response(dict(row), detailed=True)
        self._attach_tracks([job])
        return job

    def list_tracks(self, *, include_empty: bool) -> list[dict[str, Any]]:
        having_sql = (
            ""
            if include_empty
            else """HAVING count(DISTINCT j.id) FILTER (
                WHERE j.status = 'active'
                  AND (j.closes_on IS NULL OR j.closes_on >= CURRENT_DATE)
            ) > 0"""
        )
        return list(
            self.connection.execute(
                f"""
                SELECT t.slug, t.name, t.description, t.taxonomy_version, t.sort_order,
                       count(DISTINCT j.id) FILTER (
                           WHERE j.status = 'active'
                             AND (j.closes_on IS NULL OR j.closes_on >= CURRENT_DATE)
                       )::integer AS job_count,
                       count(DISTINCT j.id) FILTER (
                           WHERE jt.is_primary AND j.status = 'active'
                             AND (j.closes_on IS NULL OR j.closes_on >= CURRENT_DATE)
                       )::integer AS primary_job_count,
                       count(DISTINCT j.id) FILTER (
                           WHERE jt.review_status = 'needs_review'
                             AND j.status = 'active'
                             AND (j.closes_on IS NULL OR j.closes_on >= CURRENT_DATE)
                       )::integer AS needs_review_count
                FROM tracks t
                LEFT JOIN job_tracks jt ON jt.track_id = t.id
                LEFT JOIN jobs j ON j.id = jt.job_id
                WHERE t.active
                GROUP BY t.id
                {having_sql}
                ORDER BY t.sort_order, t.name
                """
            ).fetchall()
        )

    def list_sources(self, *, enabled_only: bool) -> list[dict[str, Any]]:
        enabled_sql = "WHERE s.enabled" if enabled_only else ""
        return list(
            self.connection.execute(
                f"""
                SELECT s.key, s.name, s.base_url, s.enabled, s.adapter_version,
                       s.last_attempt_at, s.last_success_at, s.consecutive_failures,
                       count(j.id) FILTER (
                           WHERE j.status = 'active'
                             AND (j.closes_on IS NULL OR j.closes_on >= CURRENT_DATE)
                       )::integer AS active_job_count,
                       count(j.id)::integer AS total_job_count,
                       latest.status AS latest_sync_status
                FROM sources s
                LEFT JOIN jobs j ON j.source_id = s.id
                LEFT JOIN LATERAL (
                    SELECT sr.status
                    FROM sync_runs sr
                    WHERE sr.source_id = s.id
                    ORDER BY sr.started_at DESC
                    LIMIT 1
                ) latest ON true
                {enabled_sql}
                GROUP BY s.id, latest.status
                ORDER BY s.name
                """
            ).fetchall()
        )

    def stats(self) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT count(*)::integer AS total_jobs,
                   count(*) FILTER (
                       WHERE status = 'active'
                         AND (closes_on IS NULL OR closes_on >= CURRENT_DATE)
                   )::integer AS active_jobs,
                   count(*) FILTER (WHERE status = 'expired')::integer AS expired_jobs,
                   count(*) FILTER (WHERE status = 'removed')::integer AS removed_jobs,
                   count(*) FILTER (WHERE status = 'unknown')::integer AS unknown_jobs,
                   count(*) FILTER (
                       WHERE status = 'active'
                         AND (closes_on IS NULL OR closes_on >= CURRENT_DATE)
                         AND NOT EXISTS (
                             SELECT 1 FROM job_tracks jt WHERE jt.job_id = jobs.id
                         )
                   )::integer AS unclassified_active_jobs
            FROM jobs
            """
        ).fetchone()
        assert row is not None
        auxiliary = self.connection.execute(
            """
            SELECT (SELECT count(DISTINCT jt.job_id)::integer
                    FROM job_tracks jt
                    JOIN jobs j ON j.id = jt.job_id
                    WHERE jt.review_status = 'needs_review'
                      AND j.status = 'active'
                      AND (j.closes_on IS NULL OR j.closes_on >= CURRENT_DATE)
                   ) AS jobs_needing_review,
                   (SELECT count(*)::integer FROM sources WHERE enabled) AS enabled_sources,
                   (SELECT count(*)::integer FROM tracks WHERE active) AS active_tracks,
                   (SELECT max(last_success_at) FROM sources) AS latest_source_success_at
            """
        ).fetchone()
        assert auxiliary is not None
        primary_counts = self.connection.execute(
            """
            SELECT t.slug, t.name, count(*)::integer AS job_count
            FROM job_tracks jt
            JOIN tracks t ON t.id = jt.track_id
            JOIN jobs j ON j.id = jt.job_id
            WHERE jt.is_primary
              AND j.status = 'active'
              AND (j.closes_on IS NULL OR j.closes_on >= CURRENT_DATE)
            GROUP BY t.id
            ORDER BY count(*) DESC, t.name
            """
        ).fetchall()
        return {
            "generated_at": datetime.now(timezone.utc),
            **dict(row),
            **dict(auxiliary),
            "primary_track_counts": list(primary_counts),
        }

    def _attach_tracks(self, jobs: list[dict[str, Any]]) -> None:
        if not jobs:
            return
        ids = [job["id"] for job in jobs]
        rows = self.connection.execute(
            """
            SELECT jt.job_id, t.slug, t.name, jt.is_primary,
                   jt.confidence::float8 AS confidence, jt.review_status
            FROM job_tracks jt
            JOIN tracks t ON t.id = jt.track_id
            WHERE jt.job_id = ANY(%s::uuid[])
            ORDER BY jt.job_id, jt.is_primary DESC, jt.confidence DESC, t.name
            """,
            (ids,),
        ).fetchall()
        assignments: dict[UUID, list[dict[str, Any]]] = {job_id: [] for job_id in ids}
        for row in rows:
            item = dict(row)
            job_id = item.pop("job_id")
            assignments[job_id].append(item)
        for job in jobs:
            job["tracks"] = assignments[job["id"]]

    @staticmethod
    def _job_response(row: dict[str, Any], *, detailed: bool = False) -> dict[str, Any]:
        salary = None
        if any(
            row.get(name) is not None
            for name in ("salary_min", "salary_max", "salary_currency", "salary_period", "salary_raw")
        ):
            salary = {
                "minimum": row.get("salary_min"),
                "maximum": row.get("salary_max"),
                "currency": row.get("salary_currency"),
                "period": row.get("salary_period"),
                "display_text": row.get("salary_raw"),
            }
        response: dict[str, Any] = {
            "id": row["id"],
            "external_id": row["external_id"],
            "title": row["title"],
            "summary": row.get("summary"),
            "canonical_url": row["canonical_url"],
            "apply_url": row.get("apply_url"),
            "source": {
                "key": row["source_key"],
                "name": row["source_name"],
                "last_success_at": row.get("source_last_success_at"),
            },
            "employer": {"name": row["employer_name"]},
            "location": {
                "text": row.get("location_text"),
                "city": row.get("city"),
                "borough": row.get("borough"),
                "region": row.get("region"),
                "state": row.get("state"),
                "postal_code": row.get("postal_code"),
            },
            "salary": salary,
            "source_category": row.get("source_category"),
            "source_department": row.get("source_department"),
            "source_agency": row.get("source_agency"),
            "employment_type": row.get("employment_type"),
            "schedule": row.get("schedule"),
            "work_mode": row.get("work_mode"),
            "experience_level": row.get("experience_level"),
            "posted_at": row.get("posted_at"),
            "opens_on": row.get("opens_on"),
            "closes_on": row.get("closes_on"),
            "status": row["status"],
            "tracks": [],
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
            "last_changed_at": row["last_changed_at"],
        }
        if detailed:
            response.update(
                description_text=row.get("description_text"),
                requirements_text=row.get("requirements_text"),
                requirements=row.get("requirements") or [],
                licenses=row.get("licenses") or [],
                experience_years_min=row.get("experience_years_min"),
                education_level=row.get("education_level"),
            )
        return response
