from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase

from app.domain import CanonicalJob, json_ready


class CanonicalJobTest(TestCase):
    def test_json_ready_removes_postgresql_invalid_nul_bytes(self):
        value = {"description": "before\x00after", "nested": ["a\x00b"]}

        self.assertEqual(
            json_ready(value),
            {"description": "beforeafter", "nested": ["ab"]},
        )

    def make_job(self, **changes):
        values = {
            "source_key": "test",
            "employer_name": "Example Employer",
            "external_id": "123",
            "title": "Help Desk Technician",
            "canonical_url": "https://example.test/jobs/123",
            "observed_at": datetime(2026, 8, 9, tzinfo=timezone.utc),
        }
        values.update(changes)
        return CanonicalJob(**values)

    def test_hash_ignores_observation_time(self):
        first = self.make_job()
        second = self.make_job(observed_at=datetime(2026, 8, 10, tzinfo=timezone.utc))
        self.assertEqual(first.content_hash, second.content_hash)

    def test_hash_ignores_decimal_display_scale(self):
        first = CanonicalJob(
            source_key="test",
            employer_name="Example",
            external_id="1",
            title="Example job",
            canonical_url="https://example.test/jobs/1",
            observed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
            salary_min=Decimal("131330"),
        )
        second = replace(first, salary_min=Decimal("131330.00"))

        self.assertEqual(first.content_hash, second.content_hash)

    def test_hash_ignores_equivalent_timezone_display(self):
        eastern = timezone(timedelta(hours=-4))
        first = self.make_job(posted_at=datetime(2026, 8, 9, 8, tzinfo=eastern))
        second = replace(
            first,
            posted_at=datetime(2026, 8, 9, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(first.content_hash, second.content_hash)

    def test_hash_changes_with_material_content(self):
        first = self.make_job()
        second = self.make_job(title="Senior Help Desk Technician")
        self.assertNotEqual(first.content_hash, second.content_hash)
