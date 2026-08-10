from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.api.dependencies import get_newsletter_repository, get_repository
from app.api.main import create_app
from tests.api.helpers import FakeNewsletterRepository, FakeRepository, JOB_ID, MISSING_JOB_ID


class APIRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeRepository()
        self.newsletter_repository = FakeNewsletterRepository()
        self.app = create_app()
        self.app.dependency_overrides[get_repository] = lambda: self.repository
        self.app.dependency_overrides[get_newsletter_repository] = (
            lambda: self.newsletter_repository
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()

    def test_root_and_health(self) -> None:
        root = self.client.get("/")
        health = self.client.get("/api/v1/health", headers={"X-Request-ID": "test-123"})

        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.json()["documentation_url"], "/docs")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["database"], "read_only")
        self.assertEqual(health.headers["X-Request-ID"], "test-123")

    def test_jobs_parses_repeated_filters_and_strips_private_fields(self) -> None:
        response = self.client.get(
            "/api/v1/jobs",
            params=[
                ("q", "help desk"),
                ("track", "IT-Data-Cybersecurity"),
                ("track", "customer-service"),
                ("state", "ny"),
                ("page_size", "10"),
            ],
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["pagination"]["total_items"], 1)
        self.assertEqual(self.repository.last_filters.track[0], "it-data-cybersecurity")
        self.assertEqual(self.repository.last_filters.state, ["NY"])
        self.assertNotIn("raw_payload", payload["items"][0])
        self.assertNotIn("reason", payload["items"][0]["tracks"][0])

    def test_job_detail_normalizes_requirements_and_licenses(self) -> None:
        response = self.client.get(f"/api/v1/jobs/{JOB_ID}")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["requirements"][0]["text"], "One year of experience")
        self.assertEqual(payload["licenses"][0]["name"], "Driver license")

    def test_missing_job_uses_structured_error_model(self) -> None:
        response = self.client.get(f"/api/v1/jobs/{MISSING_JOB_ID}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_validation_errors_are_structured(self) -> None:
        response = self.client.get("/api/v1/jobs?page_size=101&unexpected=true")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertGreaterEqual(len(response.json()["error"]["details"]), 1)

    def test_write_methods_are_rejected_with_structured_errors(self) -> None:
        response = self.client.post("/api/v1/jobs", json={"title": "No writes"})

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"]["code"], "method_not_allowed")

    def test_newsletter_subscription_creates_a_normalized_record(self) -> None:
        response = self.client.post(
            "/api/v1/newsletter/subscriptions",
            json={
                "email": " Devin@Example.COM ",
                "name": "  Devin   Smith  ",
                "frequency": "weekly",
                "all_tracks": False,
                "track_slugs": ["IT-Data-Cybersecurity"],
                "consent": True,
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["email"], "devin@example.com")
        self.assertEqual(response.json()["name"], "Devin Smith")
        self.assertTrue(response.json()["created"])
        self.assertEqual(
            self.newsletter_repository.last_request.track_slugs,
            ["it-data-cybersecurity"],
        )

    def test_newsletter_subscription_update_returns_200(self) -> None:
        self.newsletter_repository.created = False
        response = self.client.post(
            "/api/v1/newsletter/subscriptions",
            json={"email": "devin@example.com", "all_tracks": True, "consent": True},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["created"])

    def test_newsletter_requires_consent_and_a_valid_track_choice(self) -> None:
        no_consent = self.client.post(
            "/api/v1/newsletter/subscriptions",
            json={"email": "devin@example.com", "all_tracks": True, "consent": False},
        )
        no_tracks = self.client.post(
            "/api/v1/newsletter/subscriptions",
            json={"email": "devin@example.com", "all_tracks": False, "consent": True},
        )

        self.assertEqual(no_consent.status_code, 422)
        self.assertEqual(no_tracks.status_code, 422)
        self.assertEqual(no_consent.json()["error"]["code"], "validation_error")

    def test_catalog_endpoints(self) -> None:
        tracks = self.client.get("/api/v1/tracks")
        sources = self.client.get("/api/v1/sources")
        stats = self.client.get("/api/v1/stats")

        self.assertEqual(tracks.status_code, 200)
        self.assertEqual(sources.status_code, 200)
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(tracks.json()[0]["job_count"], 1)
        self.assertEqual(sources.json()[0]["latest_sync_status"], "succeeded")
        self.assertEqual(stats.json()["active_jobs"], 1)

    def test_openapi_documents_models_and_limits_writes_to_signup(self) -> None:
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        document = response.json()
        self.assertIn("JobListResponse", document["components"]["schemas"])
        self.assertIn("JobDetailResponse", document["components"]["schemas"])
        self.assertIn("NewsletterSubscriptionRequest", document["components"]["schemas"])
        self.assertIn("NewsletterSubscriptionResponse", document["components"]["schemas"])
        self.assertIn("ErrorResponse", document["components"]["schemas"])
        write_operations = {
            path: set(operations).intersection({"post", "put", "patch", "delete"})
            for path, operations in document["paths"].items()
            if set(operations).intersection({"post", "put", "patch", "delete"})
        }
        self.assertEqual(
            write_operations,
            {"/api/v1/newsletter/subscriptions": {"post"}},
        )


if __name__ == "__main__":
    unittest.main()
