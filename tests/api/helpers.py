"""Deterministic API fixtures and a dependency-injected fake repository."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID


JOB_ID = UUID("11111111-1111-4111-8111-111111111111")
MISSING_JOB_ID = UUID("99999999-9999-4999-8999-999999999999")
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
SUBSCRIBER_ID = UUID("22222222-2222-4222-8222-222222222222")


def job(*, detailed: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": JOB_ID,
        "external_id": "TEST-101",
        "title": "Help Desk Technician",
        "summary": "Support staff and workplace technology.",
        "canonical_url": "https://example.test/jobs/TEST-101",
        "apply_url": "https://example.test/jobs/TEST-101/apply",
        "source": {
            "key": "test_source",
            "name": "Test Source",
            "last_success_at": NOW,
        },
        "employer": {"name": "Example Employer"},
        "location": {
            "text": "New York, NY",
            "city": "New York",
            "borough": "Manhattan",
            "region": "New York City",
            "state": "NY",
            "postal_code": "10001",
        },
        "salary": {
            "minimum": 60000,
            "maximum": 75000,
            "currency": "USD",
            "period": "year",
            "display_text": "$60,000-$75,000",
        },
        "source_category": "Technology",
        "source_department": "IT",
        "source_agency": None,
        "employment_type": "Full-time",
        "schedule": "Monday-Friday",
        "work_mode": "hybrid",
        "experience_level": "Entry level",
        "posted_at": NOW,
        "opens_on": date(2026, 8, 10),
        "closes_on": date(2026, 9, 10),
        "status": "active",
        "tracks": [
            {
                "slug": "it-data-cybersecurity",
                "name": "IT, data, and cybersecurity",
                "is_primary": True,
                "confidence": 0.91,
                "review_status": "unreviewed",
                "reason": "This internal field must be removed by the response model.",
            }
        ],
        "first_seen_at": NOW,
        "last_seen_at": NOW,
        "last_changed_at": NOW,
        "raw_payload": {"private": "must never appear"},
    }
    if detailed:
        item.update(
            description_text="Resolve tickets and support users.",
            requirements_text="One year of technical support experience.",
            requirements=[
                "One year of experience",
                {"type": "Preferred", "text": "CompTIA A+"},
            ],
            licenses=["Driver license"],
            experience_years_min=1,
            education_level="High school",
        )
    return item


class FakeRepository:
    def __init__(self) -> None:
        self.last_filters = None

    def health(self) -> bool:
        return True

    def list_jobs(self, filters):
        self.last_filters = filters
        return [job()], 1

    def get_job(self, job_id):
        return job(detailed=True) if job_id == JOB_ID else None

    def list_tracks(self, *, include_empty: bool):
        return [
            {
                "slug": "it-data-cybersecurity",
                "name": "IT, data, and cybersecurity",
                "description": "Technical roles",
                "taxonomy_version": "1.1",
                "sort_order": 20,
                "job_count": 1,
                "primary_job_count": 1,
                "needs_review_count": 0,
            }
        ]

    def list_sources(self, *, enabled_only: bool):
        return [
            {
                "key": "test_source",
                "name": "Test Source",
                "base_url": "https://example.test/jobs",
                "enabled": True,
                "adapter_version": "1.0",
                "last_attempt_at": NOW,
                "last_success_at": NOW,
                "consecutive_failures": 0,
                "active_job_count": 1,
                "total_job_count": 1,
                "latest_sync_status": "succeeded",
            }
        ]

    def stats(self):
        return {
            "generated_at": NOW,
            "total_jobs": 1,
            "active_jobs": 1,
            "expired_jobs": 0,
            "removed_jobs": 0,
            "unknown_jobs": 0,
            "unclassified_active_jobs": 0,
            "jobs_needing_review": 0,
            "enabled_sources": 1,
            "active_tracks": 1,
            "latest_source_success_at": NOW,
            "primary_track_counts": [
                {
                    "slug": "it-data-cybersecurity",
                    "name": "IT, data, and cybersecurity",
                    "job_count": 1,
                }
            ],
        }


class FakeNewsletterRepository:
    def __init__(self, *, created: bool = True) -> None:
        self.created = created
        self.last_request = None

    def subscribe(self, request):
        self.last_request = request
        return {
            "id": SUBSCRIBER_ID,
            "email": request.email,
            "name": request.name,
            "status": "subscribed",
            "frequency": request.frequency,
            "all_tracks": request.all_tracks,
            "tracks": [
                {"slug": slug, "name": "IT, data, and cybersecurity"}
                for slug in request.track_slugs
            ],
            "subscribed_at": NOW,
            "created": self.created,
        }
