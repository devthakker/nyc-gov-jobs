from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.newsletter.mailer import build_message
from app.newsletter.models import DigestJob, Subscriber
from app.newsletter.renderer import render_html, render_text, salary


def digest_job() -> DigestJob:
    return DigestJob(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        title="Help Desk <Technician>",
        canonical_url="https://example.test/jobs/101",
        apply_url="https://example.test/jobs/101/apply",
        employer_name="Example & Company",
        source_name="Metropolitan Transportation Authority",
        location_text="Brooklyn, NY",
        city="Brooklyn",
        state="NY",
        salary_min=Decimal("60000"),
        salary_max=Decimal("75000"),
        salary_currency="USD",
        salary_period="year",
        salary_raw=None,
        summary="Support staff and workplace technology.",
        posted_at=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
        closes_on=date(2026, 9, 10),
        track_slug="it-data-cybersecurity",
        track_name="IT, data, and cybersecurity",
    )


class NewsletterRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.subscriber = Subscriber(
            id=None,
            email="devin@example.com",
            name="Devin & team",
            all_tracks=False,
            track_slugs=("it-data-cybersecurity",),
        )

    def test_html_matches_site_palette_and_escapes_source_content(self) -> None:
        output = render_html(
            self.subscriber,
            [digest_job()],
            site_url="http://localhost:4000",
            generated_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        )

        self.assertIn("#11231f", output)
        self.assertIn("#ec5128", output)
        self.assertIn("#efc650", output)
        self.assertIn("Less searching.", output)
        self.assertIn("Help Desk &lt;Technician&gt;", output)
        self.assertIn("Example &amp; Company", output)
        self.assertIn("http://localhost:4000/jobs/11111111", output)
        self.assertNotIn("#0b63ce", output)

    def test_text_fallback_has_the_same_job_facts(self) -> None:
        output = render_text(
            self.subscriber,
            [digest_job()],
            site_url="http://localhost:4000",
        )

        self.assertIn("Help Desk <Technician>", output)
        self.assertIn("$60,000–$75,000 / year", output)
        self.assertIn("Sep 10, 2026", output)
        self.assertIn("https://example.test/jobs/101/apply", output)

    def test_salary_prefers_source_display_text(self) -> None:
        job = digest_job()
        replacement = DigestJob(**{**job.__dict__, "salary_raw": "$31.50 per hour"})
        self.assertEqual(salary(replacement), "$31.50 per hour")

    def test_message_contains_plain_and_html_alternatives(self) -> None:
        message = build_message(
            subject="Weekly jobs",
            sender="Job Tracks <dispatch@jobtracks.local>",
            recipient="devin@example.com",
            text_body="Plain text",
            html_body="<strong>HTML</strong>",
        )

        self.assertEqual(message["To"], "devin@example.com")
        self.assertTrue(message["Message-ID"].endswith("@jobtracks.local>"))
        self.assertTrue(message.is_multipart())
        self.assertEqual(message.get_body(preferencelist=("plain",)).get_content().strip(), "Plain text")


if __name__ == "__main__":
    unittest.main()
