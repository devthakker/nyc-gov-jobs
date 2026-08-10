from datetime import datetime, timezone
from unittest import TestCase

from app.adapters.nysdol import NYSDOLApprenticeshipAdapter


class NYSDOLAdapterTest(TestCase):
    def test_normalizes_listing_record(self):
        record = {
            "id": "66851",
            "title": "International Union of Operating Engineers Local Union #138",
            "regions": ["Long Island"],
            "posted_date": "2026-07-31",
            "opening_date": "2026-09-14",
            "closing_date": "2026-09-25",
            "listing_summary": "Opening Date 09/14/2026 Closing Date 09/25/2026",
            "url": "https://dol.ny.gov/news/example",
            "_details_included": False,
        }
        job = NYSDOLApprenticeshipAdapter().normalize(
            record, datetime(2026, 8, 9, tzinfo=timezone.utc)
        )
        self.assertEqual(job.external_id, "66851")
        self.assertEqual(job.region, "Long Island")
        self.assertEqual(job.state, "NY")
        self.assertEqual(job.status, "active")
        self.assertEqual(job.opens_on.isoformat(), "2026-09-14")
        self.assertEqual(len(job.content_hash), 64)

    def test_closed_title_is_expired_and_cleaned_for_employer(self):
        record = {
            "id": "1",
            "title": "CLOSED: Example Sponsor",
            "regions": [],
            "url": "https://dol.ny.gov/news/closed-example",
        }
        job = NYSDOLApprenticeshipAdapter().normalize(
            record, datetime(2026, 8, 9, tzinfo=timezone.utc)
        )
        self.assertEqual(job.employer_name, "Example Sponsor")
        self.assertEqual(job.status, "expired")
