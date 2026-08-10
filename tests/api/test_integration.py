from __future__ import annotations

import os
import unittest

import psycopg
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.repository import ReadOnlyJobRepository
from app.newsletter.repository import NewsletterRepository


@unittest.skipUnless(
    os.getenv("RUN_DB_INTEGRATION") == "1" and os.getenv("DATABASE_URL"),
    "Set RUN_DB_INTEGRATION=1 and DATABASE_URL to run PostgreSQL integration tests.",
)
class PostgreSQLAPIIntegrationTests(unittest.TestCase):
    test_email = "api-integration@example.com"

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def tearDown(self) -> None:
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
            connection.execute(
                "DELETE FROM newsletter_subscribers WHERE email = %s",
                (self.test_email,),
            )

    def test_health_confirms_read_only_database_session(self) -> None:
        response = self.client.get("/api/v1/health")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["database"], "read_only")

    def test_repository_session_rejects_write_statements(self) -> None:
        with ReadOnlyJobRepository(os.environ["DATABASE_URL"]) as repository:
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                repository.connection.execute("UPDATE jobs SET title = title WHERE false")

    def test_active_jobs_round_trip_through_response_models(self) -> None:
        response = self.client.get("/api/v1/jobs?page_size=5")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertGreater(payload["pagination"]["total_items"], 0)
        self.assertLessEqual(len(payload["items"]), 5)
        self.assertNotIn("raw_payload", payload["items"][0])

    def test_track_filter_and_detail(self) -> None:
        tracks = self.client.get("/api/v1/tracks")
        self.assertEqual(tracks.status_code, 200, tracks.text)
        self.assertGreater(len(tracks.json()), 0)

        slug = tracks.json()[0]["slug"]
        jobs = self.client.get("/api/v1/jobs", params={"track": slug, "page_size": 1})
        self.assertEqual(jobs.status_code, 200, jobs.text)
        self.assertGreater(jobs.json()["pagination"]["total_items"], 0)

        job_id = jobs.json()["items"][0]["id"]
        detail = self.client.get(f"/api/v1/jobs/{job_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["id"], job_id)

    def test_sources_and_stats_reflect_local_data(self) -> None:
        sources = self.client.get("/api/v1/sources")
        stats = self.client.get("/api/v1/stats")

        self.assertEqual(sources.status_code, 200, sources.text)
        self.assertEqual(stats.status_code, 200, stats.text)
        self.assertGreaterEqual(len(sources.json()), 4)
        self.assertGreater(stats.json()["active_jobs"], 0)
        self.assertGreater(stats.json()["active_tracks"], 0)

    def test_newsletter_signup_persists_and_updates_preferences(self) -> None:
        tracks = self.client.get("/api/v1/tracks").json()
        track_slug = tracks[0]["slug"]
        created = self.client.post(
            "/api/v1/newsletter/subscriptions",
            json={
                "email": self.test_email,
                "name": "Integration Test",
                "all_tracks": False,
                "track_slugs": [track_slug],
                "consent": True,
            },
        )
        updated = self.client.post(
            "/api/v1/newsletter/subscriptions",
            json={
                "email": self.test_email,
                "name": "Integration Test",
                "all_tracks": True,
                "consent": True,
            },
        )

        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["tracks"][0]["slug"], track_slug)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertTrue(updated.json()["all_tracks"])
        self.assertEqual(updated.json()["tracks"], [])
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            record = connection.execute(
                """
                SELECT s.status, s.all_tracks, count(st.track_id) AS track_count
                FROM newsletter_subscribers s
                LEFT JOIN newsletter_subscriber_tracks st ON st.subscriber_id = s.id
                WHERE s.email = %s
                GROUP BY s.id
                """,
                (self.test_email,),
            ).fetchone()
        self.assertEqual(record, ("subscribed", True, 0))

    def test_newsletter_issue_history_commits_after_reading_jobs(self) -> None:
        issue_id = None
        try:
            with NewsletterRepository(os.environ["DATABASE_URL"]) as repository:
                jobs = repository.list_jobs(track_slugs=(), max_jobs=1)
                self.assertEqual(len(jobs), 1)
                issue_id = repository.create_issue(
                    subject="Integration issue history",
                    job_ids=[jobs[0].id],
                    recipient_count=1,
                    rendered_content="integration content",
                    max_jobs=1,
                )
                repository.mark_sending(issue_id)
                repository.mark_sent(issue_id, recipient_count=1)

            with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
                record = connection.execute(
                    "SELECT status, recipient_count, sent_at IS NOT NULL FROM newsletter_issues WHERE id = %s",
                    (issue_id,),
                ).fetchone()
            self.assertEqual(record, ("sent", 1, True))
        finally:
            if issue_id is not None:
                with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
                    connection.execute("DELETE FROM newsletter_issues WHERE id = %s", (issue_id,))


if __name__ == "__main__":
    unittest.main()
