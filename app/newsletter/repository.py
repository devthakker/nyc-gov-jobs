"""PostgreSQL queries and issue bookkeeping for newsletter delivery."""

from __future__ import annotations

from hashlib import sha256
from typing import Iterable
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.newsletter.models import DigestJob, Subscriber


class NewsletterRepository:
    def __init__(self, database_url: str) -> None:
        self.connection = psycopg.connect(
            database_url,
            autocommit=True,
            row_factory=dict_row,
            application_name="jobtracks-newsletter-worker",
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "NewsletterRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def list_subscribers(self) -> list[Subscriber]:
        rows = self.connection.execute(
            """
            SELECT s.id, s.email, s.name, s.all_tracks,
                   COALESCE(
                       array_agg(t.slug ORDER BY t.sort_order, t.name)
                           FILTER (WHERE t.id IS NOT NULL),
                       ARRAY[]::text[]
                   ) AS track_slugs
            FROM newsletter_subscribers s
            LEFT JOIN newsletter_subscriber_tracks st ON st.subscriber_id = s.id
            LEFT JOIN tracks t ON t.id = st.track_id AND t.active
            WHERE s.status = 'subscribed' AND s.frequency = 'weekly'
            GROUP BY s.id
            ORDER BY s.subscribed_at, s.id
            """
        ).fetchall()
        return [
            Subscriber(
                id=row["id"],
                email=row["email"],
                name=row["name"],
                all_tracks=row["all_tracks"],
                track_slugs=tuple(row["track_slugs"]),
            )
            for row in rows
        ]

    def list_jobs(self, *, track_slugs: Iterable[str], max_jobs: int) -> list[DigestJob]:
        selected_tracks = list(track_slugs)
        track_filter = ""
        parameters: list[object] = []
        if selected_tracks:
            track_filter = """
                AND EXISTS (
                    SELECT 1
                    FROM job_tracks selected_jt
                    JOIN tracks selected_t ON selected_t.id = selected_jt.track_id
                    WHERE selected_jt.job_id = j.id
                      AND selected_t.active
                      AND selected_t.slug = ANY(%s::text[])
                )
            """
            parameters.append(selected_tracks)
        rows = self.connection.execute(
            f"""
            SELECT j.id, j.title, j.canonical_url, j.apply_url,
                   COALESCE(e.name, s.name) AS employer_name,
                   s.name AS source_name,
                   j.location_text, j.city, j.state,
                   j.salary_min, j.salary_max, j.salary_currency,
                   j.salary_period, j.salary_raw, j.summary,
                   j.posted_at, j.closes_on,
                   primary_track.slug AS track_slug,
                   primary_track.name AS track_name
            FROM jobs j
            JOIN sources s ON s.id = j.source_id
            LEFT JOIN employers e ON e.id = j.employer_id
            LEFT JOIN LATERAL (
                SELECT t.slug, t.name
                FROM job_tracks jt
                JOIN tracks t ON t.id = jt.track_id
                WHERE jt.job_id = j.id
                ORDER BY jt.is_primary DESC, t.sort_order, t.name
                LIMIT 1
            ) primary_track ON true
            WHERE j.status = 'active'
              AND (j.closes_on IS NULL OR j.closes_on >= CURRENT_DATE)
              {track_filter}
            ORDER BY COALESCE(j.posted_at, j.opens_on::timestamptz, j.first_seen_at) DESC,
                     j.title, j.id
            LIMIT %s
            """,
            [*parameters, max_jobs],
        ).fetchall()
        return [DigestJob(**dict(row)) for row in rows]

    def create_issue(
        self,
        *,
        subject: str,
        job_ids: Iterable[UUID],
        recipient_count: int,
        rendered_content: str,
        max_jobs: int,
    ) -> UUID:
        unique_job_ids = list(dict.fromkeys(job_ids))
        content_hash = sha256(rendered_content.encode("utf-8")).hexdigest()
        with self.connection.transaction():
            row = self.connection.execute(
                """
                INSERT INTO newsletter_issues (
                    subject, filters, status, rendered_at, recipient_count, content_hash
                )
                VALUES (%s, jsonb_build_object('frequency', 'weekly', 'max_jobs', %s),
                        'rendered', now(), %s, %s)
                RETURNING id
                """,
                (subject, max_jobs, recipient_count, content_hash),
            ).fetchone()
            assert row is not None
            issue_id = row["id"]
            if unique_job_ids:
                with self.connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO newsletter_issue_jobs (
                            newsletter_issue_id, job_id, position
                        ) VALUES (%s, %s, %s)
                        """,
                        [
                            (issue_id, job_id, index)
                            for index, job_id in enumerate(unique_job_ids, start=1)
                        ],
                    )
        return issue_id

    def mark_sending(self, issue_id: UUID) -> None:
        self._update_issue(issue_id, status="sending")

    def mark_sent(self, issue_id: UUID, *, recipient_count: int) -> None:
        self._update_issue(
            issue_id,
            status="sent",
            recipient_count=recipient_count,
            sent=True,
        )

    def mark_failed(self, issue_id: UUID, *, recipient_count: int, error: str) -> None:
        self._update_issue(
            issue_id,
            status="failed",
            recipient_count=recipient_count,
            error=error[:2000],
        )

    def _update_issue(
        self,
        issue_id: UUID,
        *,
        status: str,
        recipient_count: int | None = None,
        sent: bool = False,
        error: str | None = None,
    ) -> None:
        with self.connection.transaction():
            self.connection.execute(
                """
                UPDATE newsletter_issues
                SET status = %s,
                    recipient_count = COALESCE(%s, recipient_count),
                    sent_at = CASE WHEN %s THEN now() ELSE sent_at END,
                    error_summary = %s
                WHERE id = %s
                """,
                (status, recipient_count, sent, error, issue_id),
            )
