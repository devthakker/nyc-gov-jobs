from datetime import datetime, timezone
from decimal import Decimal
from unittest import TestCase

from app.adapters.cuny import CUNYJobsAdapter, parse_sitemap


SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://cuny.jobs/bronx-ny/administrative-coordinator/000AE940B17449DB9682FA3C2FA15054/job/</loc><lastmod>2026-08-09</lastmod></url>
  <url><loc>https://cuny.jobs/new-york-ny/it-assistant/10AFE5F837524BAAB3C0C743930A8A03/job/</loc><lastmod>2026-08-10</lastmod></url>
</urlset>"""


DETAIL = {
    "guid": "000AE940B17449DB9682FA3C2FA15054",
    "title_exact": "Administrative Coordinator",
    "html_description": """
      <p>Administrative Coordinator</p><p><strong>POSITION DETAILS</strong></p>
      <p>Coordinate campus programs and office operations.</p>
      <p><strong>QUALIFICATIONS</strong></p><p>Bachelor's Degree required.</p>
      <p><strong>CUNY TITLE OVERVIEW</strong></p><p>Supports a department.</p>
      <p><strong>COMPENSATION AND BENEFITS</strong></p><p>Salary $52,426 annually.</p>
      <p><strong>HOW TO APPLY</strong></p><p>Apply online.</p>
      <p><strong>CLOSING DATE</strong></p><p>Applications close August 15th, 2026.</p>
      <p><strong>JOB SEARCH CATEGORY</strong></p><p>CUNY Job Posting: Managerial/Professional</p>
    """,
    "date_new": "2026-07-28T22:36:06Z",
    "reqid": "32503",
    "link": "https://de.jobsyn.org/000AE940B17449DB9682FA3C2FA1505410",
    "location_exact": "Bronx, NY",
    "location_name": "LEHMAN COLLEGE",
    "city": "Bronx",
    "state_short": "NY",
    "zipcode": "10460",
    "job_type": "Full-Time",
}


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return SITEMAP

    def get_json(self, url: str) -> dict:
        self.urls.append(url)
        guid = url.rsplit("/", 1)[-1].removesuffix(".json")
        return {**DETAIL, "guid": guid, "title_exact": "IT Assistant" if guid.startswith("10") else DETAIL["title_exact"]}


class CUNYAdapterTest(TestCase):
    def test_sitemap_is_complete_and_uses_guid_identity(self):
        records = parse_sitemap(SITEMAP)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["id"], "000AE940B17449DB9682FA3C2FA15054")
        self.assertEqual(records[0]["last_modified"], "2026-08-09")

    def test_collect_limits_before_detail_requests(self):
        client = FakeClient()
        result = CUNYJobsAdapter(client=client, workers=2).collect(limit=1)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.metadata["site_reported_count"], 2)
        self.assertTrue(result.records[0]["_details_included"])
        self.assertEqual(len(client.urls), 2)

    def test_normalizes_campus_job(self):
        listing = parse_sitemap(SITEMAP)[0]
        job = CUNYJobsAdapter(client=FakeClient()).normalize(
            {**listing, "detail": DETAIL, "_details_included": True},
            datetime(2026, 8, 10, tzinfo=timezone.utc),
        )

        self.assertEqual(job.external_id, "000AE940B17449DB9682FA3C2FA15054")
        self.assertEqual(job.source_category, "Managerial/Professional")
        self.assertEqual(job.source_department, "LEHMAN COLLEGE")
        self.assertEqual(job.salary_min, Decimal("52426"))
        self.assertEqual(job.salary_period, "year")
        self.assertEqual(job.closes_on.isoformat(), "2026-08-15")
        self.assertIn("Bachelor's Degree", job.requirements_text)

    def test_listing_only_retains_public_identity(self):
        listing = parse_sitemap(SITEMAP)[0]
        job = CUNYJobsAdapter(client=FakeClient()).normalize(
            {**listing, "_details_included": False},
            datetime(2026, 8, 10, tzinfo=timezone.utc),
        )

        self.assertIsNone(job.description_text)
        self.assertFalse(job.source_metadata["details_included"])

    def test_reversed_source_salary_range_is_normalized(self):
        changed = {
            **DETAIL,
            "html_description": DETAIL["html_description"].replace(
                "$52,426 annually", "$133,982 - $126,333 annually"
            ),
        }
        listing = parse_sitemap(SITEMAP)[0]
        job = CUNYJobsAdapter(client=FakeClient()).normalize(
            {**listing, "detail": changed, "_details_included": True},
            datetime(2026, 8, 10, tzinfo=timezone.utc),
        )

        self.assertEqual(job.salary_min, Decimal("126333"))
        self.assertEqual(job.salary_max, Decimal("133982"))
