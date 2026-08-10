from datetime import datetime, timezone
from decimal import Decimal
from unittest import TestCase

from app.adapters.newyork_presbyterian import (
    SEARCH_URL,
    NewYorkPresbyterianAdapter,
    parse_detail_html,
    parse_listing_html,
)


def listing_html(page: int, records: list[tuple[str, str]]) -> str:
    items = "".join(
        f'<li><a href="/job/new-york/{job_id}" data-job-id="{job_id}">'
        f'<h2>{title}</h2><span class="job-location">New York, NY</span></a></li>'
        for job_id, title in records
    )
    return (
        f'<section id="search-results" data-total-job-results="3" data-total-pages="2" '
        f'data-current-page="{page}" data-records-per-page="2">'
        f'<section id="search-results-list"><ul>{items}</ul></section></section>'
    )


DETAIL_HTML = """
<html><head><script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Patient Care Technician",
  "identifier": "00883133",
  "datePosted": "2026-08-07",
  "description": "<p>Support direct patient care.</p><p><b>Required Criteria</b></p><ul><li>High school diploma</li><li>Current BLS certification</li></ul><p>Join a healthcare system.</p><p><b>Salary Range:</b></p>$33.67-$36.01/Hourly",
  "employmentType": "Full time",
  "industry": "Weill Cornell Medical Center",
  "url": "https://careers.nyp.org/job/new-york/one",
  "hiringOrganization": {"@type": "Organization", "name": "NewYork-Presbyterian"},
  "jobLocation": [{"@type": "Place", "address": {"postalCode": "10065"}}]
}
</script></head><body>
<section class="job-description">
  <span class="job-facility job-info"><b>Location</b> Weill Cornell Medical Center</span>
  <a class="button job-apply" data-apply-url="https://nyp.wd1.myworkdayjobs.com/apply">Apply</a>
  <span class="job-id job-info"><b>Job ID</b> 00883133</span>
  <span class="job-location job-info"><b>Location</b> New York, New York</span>
  <span class="job-date job-info"><b>Date posted</b> Aug. 07, 2026</span>
  <span class="job-category job-info"><b>Category</b> Clinical Support Services</span>
</section>
</body></html>
"""


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        if url == SEARCH_URL:
            return listing_html(1, [("one", "Patient Care Technician"), ("two", "Analyst")])
        if "&p=2" in url:
            return listing_html(2, [("three", "Coordinator")])
        return DETAIL_HTML


class NewYorkPresbyterianAdapterTest(TestCase):
    def test_listing_parser_reads_counts_and_cards(self):
        records, metadata = parse_listing_html(
            listing_html(1, [("one", "Patient Care Technician"), ("two", "Analyst")])
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["id"], "one")
        self.assertEqual(records[0]["location"], "New York, NY")
        self.assertEqual(metadata["total_results"], 3)
        self.assertEqual(metadata["total_pages"], 2)

    def test_detail_parser_reads_structured_posting_and_apply_link(self):
        detail = parse_detail_html(DETAIL_HTML)

        self.assertEqual(detail["job_posting"]["identifier"], "00883133")
        self.assertEqual(detail["fields"]["category"], "Clinical Support Services")
        self.assertEqual(detail["fields"]["facility"], "Weill Cornell Medical Center")
        self.assertTrue(detail["apply_url"].endswith("/apply"))

    def test_collect_paginates_and_limits_before_detail_requests(self):
        client = FakeClient()
        result = NewYorkPresbyterianAdapter(client=client, workers=2).collect(limit=3)

        self.assertEqual(len(result.records), 3)
        self.assertEqual(result.metadata["site_reported_count"], 3)
        self.assertTrue(all(record["_details_included"] for record in result.records))
        self.assertEqual(len(client.urls), 5)

    def test_normalizes_full_posting(self):
        record = {
            "id": "one",
            "url": "https://careers.nyp.org/job/new-york/one",
            "title": "Patient Care Technician",
            "location": "New York, NY",
            "detail": parse_detail_html(DETAIL_HTML),
            "_details_included": True,
        }
        job = NewYorkPresbyterianAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(job.external_id, "one")
        self.assertEqual(job.source_category, "Clinical Support Services")
        self.assertEqual(job.source_department, "Weill Cornell Medical Center")
        self.assertEqual(job.city, "New York")
        self.assertEqual(job.state, "NY")
        self.assertEqual(job.postal_code, "10065")
        self.assertEqual(job.salary_min, Decimal("33.67"))
        self.assertEqual(job.salary_max, Decimal("36.01"))
        self.assertEqual(job.salary_period, "hour")
        self.assertEqual(job.posted_at.isoformat(), "2026-08-07T00:00:00-04:00")
        self.assertIn("High school diploma", job.requirements_text)
        self.assertTrue(job.source_metadata["details_included"])

    def test_listing_only_keeps_public_identity(self):
        record = {
            "id": "one",
            "url": "https://careers.nyp.org/job/new-york/one",
            "title": "Patient Care Technician",
            "location": "New York, NY",
            "_details_included": False,
        }
        job = NewYorkPresbyterianAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertIsNone(job.description_text)
        self.assertFalse(job.source_metadata["details_included"])

