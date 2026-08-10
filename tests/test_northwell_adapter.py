from datetime import datetime, timezone
from decimal import Decimal
from unittest import TestCase
from urllib.parse import parse_qs, urlparse

from app.adapters.northwell import NorthwellHealthAdapter, extract_qualification, search_url


def api_job(job_id: int, *, category: str = "Clinical Support") -> dict:
    return {
        "id": job_id,
        "ref": f"R-{job_id}",
        "title": "Patient Care Associate",
        "primary_category": category,
        "primary_city": "New York",
        "primary_state": "NY",
        "primary_zip": "10075",
        "primary_address": "100 East 77th Street",
        "description": (
            "<p>Job Description</p><p>Support patients and the clinical team.</p>"
            "<p>Job Qualification</p><ul><li>High school diploma required.</li></ul>"
            "<p><strong>*Additional Salary Detail</strong></p>"
        ),
        "salary": "$25.50-$31.25/hour",
        "open_date": "2026-08-10T00:00:00",
        "close_date": "2036-08-10T00:00:00",
        "employment_type": "Full Time",
        "shift": "Days",
        "schedule": "8:00 AM-4:00 PM",
        "business_unit": "Lenox Hill Hospital",
        "department": "Patient Services",
        "brand": "Northwell",
        "location_type": "On-site",
        "url": f"https://jobs.northwell.edu/job-3/{job_id}/patient-care-associate/",
        "seo_url": f"https://example.oraclecloud.com/job/{job_id}/apply/email",
    }


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_json(self, url: str) -> dict:
        self.urls.append(url)
        offset = int(parse_qs(urlparse(url).query)["offset"][0])
        jobs = [api_job(101), api_job(102), api_job(103)]
        page = jobs[offset:offset + 2]
        return {
            "totalHits": len(jobs),
            "searchResults": [
                {"job": job, "summary": {"job_summary": f"Summary for {job['id']}"}}
                for job in page
            ],
        }


class NorthwellAdapterTest(TestCase):
    def test_search_url_contains_official_query_contract(self):
        query = parse_qs(urlparse(search_url(offset=100, page_size=50)).query)

        self.assertEqual(query["offset"], ["100"])
        self.assertEqual(query["pageSize"], ["50"])
        self.assertIn("Northwell Health", query["customAttributeFilter"][0])

    def test_collect_paginates_complete_snapshot(self):
        client = FakeClient()
        result = NorthwellHealthAdapter(client=client).collect()

        self.assertEqual(len(result.records), 3)
        self.assertEqual(result.metadata["site_reported_count"], 3)
        self.assertEqual(len(client.urls), 2)
        self.assertEqual(result.records[0]["_search_summary"]["job_summary"], "Summary for 101")

    def test_collect_applies_limit_at_api_boundary(self):
        client = FakeClient()
        result = NorthwellHealthAdapter(client=client).collect(limit=1)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(len(client.urls), 1)

    def test_extracts_qualification_section(self):
        text = "Job Qualification\nHigh school diploma required.\nAdditional Salary Detail\nDisclosure"

        self.assertEqual(extract_qualification(text), "High school diploma required.")

    def test_normalizes_complete_api_job(self):
        record = {
            **api_job(101),
            "_search_summary": {"job_summary": "Support patients safely."},
            "_details_included": True,
        }
        job = NorthwellHealthAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(job.external_id, "101")
        self.assertEqual(job.source_category, "Clinical Support")
        self.assertEqual(job.source_department, "Lenox Hill Hospital")
        self.assertEqual(job.salary_min, Decimal("25.50"))
        self.assertEqual(job.salary_max, Decimal("31.25"))
        self.assertEqual(job.salary_period, "hour")
        self.assertEqual(job.schedule, "Days · 8:00 AM-4:00 PM")
        self.assertIsNone(job.closes_on)
        self.assertIn("High school diploma", job.requirements_text)

