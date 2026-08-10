from datetime import datetime, timezone
from decimal import Decimal
from unittest import TestCase

from app.adapters.mta import (
    BOARD_URL,
    MTAJobsAdapter,
    html_to_text,
    parse_detail_html,
    parse_listing_html,
    parse_money,
)


LISTING_HTML = """
<h3 class="h2">Administrative &amp; Clerical</h3>
<table><tbody>
  <tr>
    <td class="jv-job-list-name">
      <a href="/metropolitantransportationauthority/job/token-one">Fleet Coordinator</a>
    </td>
    <td class="jv-job-list-location">New York, NY</td>
  </tr>
</tbody></table>
<h3 class="h2">Engineering</h3>
<table><tbody>
  <tr>
    <td class="jv-job-list-name">
      <a href="/metropolitantransportationauthority/job/token-two">Signal Engineer</a>
    </td>
    <td class="jv-job-list-location">Queens, NY</td>
  </tr>
</tbody></table>
"""


DETAIL_HTML = """
<html><body>
  <h2 class="jv-header">Fleet Coordinator</h2>
  <a class="jv-button jv-button-primary jv-button-apply"
     href="/metropolitantransportationauthority/job/token-one/apply">Apply</a>
  <div class="jv-job-detail-description" ng-non-bindable>
    <h3>Description</h3>
    <div class="jv-meta"><em>Position at MTA Headquarters</em></div>
    <p>
      Job Title: Fleet Coordinator<br>
      Department: Fleet Operations<br>
      MTA Agency: MTAHQ<br>
      Primary Location(s): New York, NY<br>
      Salary Range: $68,213 - $73,561 per year<br>
      Closing Date (if applicable): 08/31/2026<br>
      Shift (if applicable): Day
    </p>
    <h3>JOB SUMMARY:</h3>
    <p>Coordinate fleet maintenance and records.</p>
    <h3>REQUIRED EDUCATION AND EXPERIENCE:</h3>
    <p>Two years of fleet operations experience.</p>
  </div>
  <script>
    window.preloadedData = {jobId: 'token-one', jobReqId: '790851'};
  </script>
</body></html>
"""


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return LISTING_HTML if url == BOARD_URL else DETAIL_HTML


class MTAJobsAdapterTest(TestCase):
    def test_salary_parser_tolerates_source_spacing_after_comma(self):
        minimum, maximum, period = parse_money("$94,161 - $148, 834 (Grade D)")

        self.assertEqual(minimum, Decimal("94161"))
        self.assertEqual(maximum, Decimal("148834"))
        self.assertEqual(period, "year")

    def test_listing_parser_preserves_categories_and_locations(self):
        records = parse_listing_html(LISTING_HTML)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "Fleet Coordinator")
        self.assertEqual(records[0]["category"], "Administrative & Clerical")
        self.assertEqual(records[1]["location"], "Queens, NY")
        self.assertTrue(records[1]["url"].endswith("/job/token-two"))

    def test_detail_parser_extracts_jobvite_and_mta_identifiers(self):
        detail = parse_detail_html(DETAIL_HTML)

        self.assertEqual(detail["title"], "Fleet Coordinator")
        self.assertEqual(detail["position_at"], "MTA Headquarters")
        self.assertEqual(detail["jobvite_token"], "token-one")
        self.assertEqual(detail["mta_job_id"], "790851")
        self.assertTrue(detail["apply_url"].endswith("/job/token-one/apply"))
        self.assertIn("Two years of fleet operations experience", html_to_text(detail["description_html"]))

    def test_collects_limited_records_and_loads_details(self):
        client = FakeClient()
        result = MTAJobsAdapter(client=client, workers=2).collect(limit=1)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.metadata["site_reported_count"], 2)
        self.assertEqual(result.records[0]["id"], "token-one")
        self.assertTrue(result.records[0]["_details_included"])
        self.assertEqual(len(client.urls), 2)

    def test_normalizes_full_posting(self):
        record = {
            **parse_listing_html(LISTING_HTML)[0],
            "id": "token-one",
            "detail": parse_detail_html(DETAIL_HTML),
            "_details_included": True,
        }
        job = MTAJobsAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 9, tzinfo=timezone.utc)
        )

        self.assertEqual(job.external_id, "token-one")
        self.assertEqual(job.employer_name, "MTA Headquarters")
        self.assertEqual(job.source_department, "Fleet Operations")
        self.assertEqual(job.source_category, "Administrative & Clerical")
        self.assertEqual(job.location_text, "New York, NY")
        self.assertEqual(job.city, "New York")
        self.assertEqual(job.state, "NY")
        self.assertEqual(job.salary_min, Decimal("68213"))
        self.assertEqual(job.salary_max, Decimal("73561"))
        self.assertEqual(job.salary_period, "year")
        self.assertEqual(job.closes_on.isoformat(), "2026-08-31")
        self.assertEqual(job.schedule, "Day")
        self.assertIn("Two years of fleet operations experience", job.requirements_text)
        self.assertEqual(job.source_metadata["mta_job_id"], "790851")
        self.assertTrue(job.source_metadata["details_included"])
        self.assertEqual(len(job.content_hash), 64)

    def test_listing_only_keeps_stable_jobvite_identity(self):
        record = {
            **parse_listing_html(LISTING_HTML)[0],
            "id": "token-one",
            "_details_included": False,
        }
        job = MTAJobsAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 9, tzinfo=timezone.utc)
        )

        self.assertEqual(job.external_id, "token-one")
        self.assertIsNone(job.description_text)
        self.assertFalse(job.source_metadata["details_included"])
