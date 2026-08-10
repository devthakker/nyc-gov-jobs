from datetime import datetime, timezone
from decimal import Decimal
from unittest import TestCase

from app.adapters.amtrak import AmtrakJobsAdapter, parse_detail_html, parse_listing_html


LISTING_HTML = """
<div>Results <b>1 – 2</b> of <b>2</b></div>
<table id="searchresults"><tbody>
<tr class="data-row">
  <td><a class="jobTitle-link" href="/job/New-York/1001/">Signal Maintainer</a></td>
  <td class="colLocation">New York, NY, US, 10001</td><td class="colDate">Aug 10, 2026</td>
</tr>
<tr class="data-row">
  <td><a class="jobTitle-link" href="/job/Albany/1002/">Systems Analyst</a></td>
  <td class="colLocation">Albany, NY, US, 12207</td><td class="colDate">Aug 09, 2026</td>
</tr>
</tbody></table>
"""


DETAIL_HTML = """
<meta itemprop="addressLocality" content="New York">
<meta itemprop="addressRegion" content="NY">
<meta itemprop="postalCode" content="10001">
<meta itemprop="addressCountry" content="US">
<meta itemprop="datePosted" content="Mon Aug 10 07:00:00 UTC 2026">
<span itemprop="title">Signal Maintainer - 90380001 - New York</span>
<span class="jobdescription">
  <h2>Job Summary</h2><p>Maintain safe railroad signal systems.</p>
  <h2>Essential Functions</h2><p>Inspect and repair equipment.</p>
  <h2>Minimum Qualifications</h2><p>High school diploma and two years of experience.</p>
  <h2>Preferred Qualifications</h2><p>Railroad signal certification.</p>
  <h2>Knowledge, Skills, and Abilities</h2><p>Electrical troubleshooting.</p>
  <p>The salary/hourly range is $38.50 – $44.25.</p>
  <p><strong>Requisition ID:</strong>166650</p>
  <p><strong>Work Arrangement:</strong>06-Onsite 4/5 Days <a>Click here</a></p>
</span>
<a class="apply" href="/talentcommunity/apply/1001/?locale=en_US">Apply</a>
"""


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return DETAIL_HTML if "/job/" in url else LISTING_HTML


class AmtrakAdapterTest(TestCase):
    def test_listing_parser_reads_counts_and_rows(self):
        records, metadata = parse_listing_html(LISTING_HTML)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["id"], "1001")
        self.assertEqual(records[0]["location"], "New York, NY, US, 10001")
        self.assertEqual(metadata, {"start": 1, "end": 2, "total": 2})

    def test_detail_parser_reads_structured_fields(self):
        detail = parse_detail_html(DETAIL_HTML)

        self.assertEqual(detail["title"], "Signal Maintainer - 90380001 - New York")
        self.assertEqual(detail["addressLocality"], "New York")
        self.assertTrue(detail["apply_url"].endswith("/1001/?locale=en_US"))
        self.assertIn("Minimum Qualifications", detail["description_html"])

    def test_filled_detail_page_is_preserved_as_removed(self):
        detail = parse_detail_html(
            '<div class="job"><p><strong>Sorry, this position has been filled.</strong></p></div>'
        )
        record = {
            **parse_listing_html(LISTING_HTML)[0][0],
            "detail": detail,
            "_details_included": True,
            "native_categories": [],
        }
        job = AmtrakJobsAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(job.status, "removed")
        self.assertTrue(job.source_metadata["filled_notice"])

    def test_collect_includes_categories_and_details(self):
        client = FakeClient()
        result = AmtrakJobsAdapter(client=client, workers=2).collect(limit=2)

        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.metadata["site_reported_count"], 2)
        self.assertEqual(result.metadata["category_mapping_coverage"], 2)
        self.assertEqual(result.records[0]["category"], "Information Technology")
        self.assertTrue(all(record["_details_included"] for record in result.records))

    def test_normalizes_full_posting(self):
        record = {
            **parse_listing_html(LISTING_HTML)[0][0],
            "category": "Railroad Operations",
            "native_categories": ["Railroad Operations"],
            "detail": parse_detail_html(DETAIL_HTML),
            "_details_included": True,
        }
        job = AmtrakJobsAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(job.external_id, "1001")
        self.assertEqual(job.source_category, "Railroad Operations")
        self.assertEqual(job.city, "New York")
        self.assertEqual(job.salary_min, Decimal("38.50"))
        self.assertEqual(job.salary_max, Decimal("44.25"))
        self.assertEqual(job.salary_period, "hour")
        self.assertEqual(job.work_mode, "on_site")
        self.assertIn("High school diploma", job.requirements_text)
        self.assertEqual(job.source_metadata["requisition_id"], "166650")

    def test_listing_only_keeps_public_identity(self):
        record = {
            **parse_listing_html(LISTING_HTML)[0][0],
            "native_categories": [],
            "_details_included": False,
        }
        job = AmtrakJobsAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertIsNone(job.description_text)
        self.assertFalse(job.source_metadata["details_included"])

    def test_multi_region_detail_uses_first_valid_state_code(self):
        detail = parse_detail_html(DETAIL_HTML)
        detail["addressRegion"] = "DC, VA"
        record = {
            **parse_listing_html(LISTING_HTML)[0][0],
            "detail": detail,
            "_details_included": True,
            "native_categories": [],
        }
        job = AmtrakJobsAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(job.state, "DC")
