from datetime import datetime, timezone
from decimal import Decimal
from unittest import TestCase

from app.adapters.port_authority import (
    BOARD_URL,
    PortAuthorityJobsAdapter,
    extract_job_posting,
    parse_compensation,
    salary_excerpt,
)


LISTING_HTML = """
<h3 class="h2">Finance</h3>
<table class="jv-job-list"><tbody>
  <tr>
    <td class="jv-job-list-name">
      <a href="/panynj/job/token-one">Staff Financial Analyst</a>
    </td>
    <td class="jv-job-list-location">Jersey City, New Jersey</td>
  </tr>
  <tr>
    <td class="jv-job-list-name">
      <a href="/panynj/job/token-two">Deputy Treasurer</a>
    </td>
    <td class="jv-job-list-location">New York, New York</td>
  </tr>
</tbody></table>
"""


DETAIL_HTML = """
<html><body>
  <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "JobPosting",
      "datePosted": "2026-07-23",
      "description": "Fallback description",
      "employmentType": "Full-Time Regular",
      "industry": "Finance",
      "identifier": "token-one",
      "title": "Staff Financial Analyst"
    }
  </script>
  <h2 class="jv-header">Staff Financial Analyst</h2>
  <a class="jv-button jv-button-primary jv-button-apply"
     href="/panynj/job/token-one/apply">Apply</a>
  <div class="jv-job-detail-description" ng-non-bindable>
    <h3>Description</h3>
    <div class="jv-meta"><em>Position at The Port Authority of NY &amp; NJ</em></div>
    <p><b>About the Role</b></p>
    <p>Support financial planning for transportation infrastructure.</p>
    <p><b>Responsibilities</b></p>
    <ul><li>Prepare financial forecasts.</li></ul>
    <p><b>Minimum Qualifications</b></p>
    <ul><li>Bachelor's degree and three years of experience.</li></ul>
    <p><b>Desired Qualifications</b></p>
    <ul><li>Experience with public infrastructure budgets.</li></ul>
    <p><b>Compensation, Benefits &amp; On-Site Collaboration Requirements:</b></p>
    <p>Employees may work remotely a maximum of one day per week.</p>
    <p>The expected compensation range for this role is:
       Minimum: $ 73,658 Midpoint: $ 95,742 Maximum: $ 117, 832</p>
  </div>
  <script>
    window.preloadedData = {jobId: 'token-one', jobReqId: '64635'};
  </script>
</body></html>
"""


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return LISTING_HTML if url == BOARD_URL else DETAIL_HTML


class PortAuthorityJobsAdapterTest(TestCase):
    def test_extracts_job_posting_json_ld(self):
        posting = extract_job_posting(DETAIL_HTML)

        self.assertEqual(posting["title"], "Staff Financial Analyst")
        self.assertEqual(posting["datePosted"], "2026-07-23")
        self.assertEqual(posting["employmentType"], "Full-Time Regular")

    def test_parses_salary_with_source_spacing(self):
        minimum, maximum, period = parse_compensation(
            "Minimum: $ 73,658 Midpoint: $ 95,742 Maximum: $ 117, 832"
        )

        self.assertEqual(minimum, Decimal("73658"))
        self.assertEqual(maximum, Decimal("117832"))
        self.assertEqual(period, "year")

    def test_salary_excerpt_does_not_include_following_benefits_link(self):
        text = (
            "The expected compensation range is: Minimum: $70,000 Maximum: $90,000\n"
            "Click here for benefits."
        )

        self.assertNotIn("Click here", salary_excerpt(text))

    def test_collects_limited_records_and_loads_details(self):
        client = FakeClient()
        result = PortAuthorityJobsAdapter(client=client, workers=2).collect(limit=1)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.metadata["site_reported_count"], 2)
        self.assertEqual(result.records[0]["id"], "token-one")
        self.assertTrue(result.records[0]["_details_included"])
        self.assertEqual(len(client.urls), 2)

    def test_normalizes_full_posting(self):
        adapter = PortAuthorityJobsAdapter(client=FakeClient())
        record = adapter.collect(limit=1).records[0]
        job = adapter.normalize(record, datetime(2026, 8, 9, tzinfo=timezone.utc))

        self.assertEqual(job.external_id, "token-one")
        self.assertEqual(job.employer_name, "The Port Authority of New York & New Jersey")
        self.assertEqual(job.source_category, "Finance")
        self.assertIsNone(job.source_department)
        self.assertEqual(job.city, "Jersey City")
        self.assertEqual(job.state, "NJ")
        self.assertEqual(job.salary_min, Decimal("73658"))
        self.assertEqual(job.salary_max, Decimal("117832"))
        self.assertEqual(job.salary_period, "year")
        self.assertEqual(job.employment_type, "Full-Time Regular")
        self.assertEqual(job.work_mode, "hybrid")
        self.assertEqual(job.posted_at.isoformat(), "2026-07-23T00:00:00-04:00")
        self.assertEqual(len(job.requirements), 2)
        self.assertIn("Bachelor's degree", job.requirements_text)
        self.assertEqual(job.source_metadata["port_authority_job_id"], "64635")
        self.assertEqual(len(job.content_hash), 64)

    def test_listing_only_keeps_stable_jobvite_identity(self):
        adapter = PortAuthorityJobsAdapter(client=FakeClient(), include_details=False)
        record = adapter.collect(limit=1).records[0]
        job = adapter.normalize(record, datetime(2026, 8, 9, tzinfo=timezone.utc))

        self.assertEqual(job.external_id, "token-one")
        self.assertIsNone(job.description_text)
        self.assertFalse(job.source_metadata["details_included"])
