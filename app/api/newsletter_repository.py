"""Narrowly scoped PostgreSQL writes for public newsletter signup."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.api.models import NewsletterSubscriptionRequest


class UnknownTrackSlugs(ValueError):
    def __init__(self, slugs: list[str]) -> None:
        self.slugs = slugs
        super().__init__(f"Unknown or inactive tracks: {', '.join(slugs)}")


class NewsletterSubscriptionRepository:
    """Write repository limited to subscriber preferences."""

    def __init__(self, database_url: str, *, statement_timeout_ms: int = 5000) -> None:
        if statement_timeout_ms < 100:
            raise ValueError("statement_timeout_ms must be at least 100")
        self.connection = psycopg.connect(
            database_url,
            row_factory=dict_row,
            application_name="jobtracks-newsletter-signup",
            options=f"-c statement_timeout={statement_timeout_ms}",
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "NewsletterSubscriptionRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def subscribe(self, request: NewsletterSubscriptionRequest) -> dict[str, Any]:
        with self.connection.transaction():
            tracks: list[dict[str, Any]] = []
            if request.track_slugs:
                tracks = list(
                    self.connection.execute(
                        """
                        SELECT id, slug, name
                        FROM tracks
                        WHERE active AND slug = ANY(%s::text[])
                        ORDER BY sort_order, name
                        """,
                        (request.track_slugs,),
                    ).fetchall()
                )
                found = {track["slug"] for track in tracks}
                unknown = [slug for slug in request.track_slugs if slug not in found]
                if unknown:
                    raise UnknownTrackSlugs(unknown)

            subscriber = self.connection.execute(
                """
                INSERT INTO newsletter_subscribers (
                    email, name, status, frequency, all_tracks, consented_at
                )
                VALUES (%s, %s, 'subscribed', %s, %s, now())
                ON CONFLICT (email) DO UPDATE SET
                    name = EXCLUDED.name,
                    status = 'subscribed',
                    frequency = EXCLUDED.frequency,
                    all_tracks = EXCLUDED.all_tracks,
                    consented_at = now(),
                    subscribed_at = CASE
                        WHEN newsletter_subscribers.status = 'unsubscribed' THEN now()
                        ELSE newsletter_subscribers.subscribed_at
                    END,
                    unsubscribed_at = NULL
                RETURNING id, email, name, status, frequency, all_tracks,
                          subscribed_at, (xmax = 0) AS created
                """,
                (request.email, request.name, request.frequency, request.all_tracks),
            ).fetchone()
            assert subscriber is not None

            self.connection.execute(
                "DELETE FROM newsletter_subscriber_tracks WHERE subscriber_id = %s",
                (subscriber["id"],),
            )
            if tracks:
                with self.connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO newsletter_subscriber_tracks (subscriber_id, track_id)
                        VALUES (%s, %s)
                        """,
                        [(subscriber["id"], track["id"]) for track in tracks],
                    )

        return {**dict(subscriber), "tracks": tracks}
