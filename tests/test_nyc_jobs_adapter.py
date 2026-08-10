from datetime import datetime, timezone
from decimal import Decimal
from unittest import TestCase

from app.adapters.nyc_jobs import NYCCityJobsAdapter, html_to_text


def sample_listing(index: int = 1) -> dict:
    return {
        "id": f"posting-{index}",
        "uuid": f"uuid-{index}",
        "name": "Fleet Coordinator",
        "refNumber": f"79085{index}",
        "company": {"identifier": "CityOfNewYork", "name": "City of New York"},
        "releasedDate": "2026-08-08T11:39:57.459Z",
        "location": {
            "city": "New York",
            "region": "NY",
            "country": "us",
            "postalCode": "10007",
            "remote": False,
            "hybrid": False,
            "fullLocation": "New York, NY, United States",
        },
        "function": {"id": "supply_chain", "label": "Supply Chain"},
        "typeOfEmployment": {"id": "permanent", "label": "Full-time"},
        "experienceLevel": {"id": "associate", "label": "Associate"},
        "customField": [
            {"fieldLabel": "Agency", "valueLabel": "OFF OF PAYROLL ADMINISTRATION"},
            {"fieldLabel": "Business Title", "valueLabel": "Fleet Coordinator"},
            {"fieldLabel": "Experience", "valueLabel": "Experienced (non-manager)"},
            {"fieldLabel": "Borough", "valueLabel": "MANHATTAN"},
            {"fieldLabel": "Job Type", "valueLabel": "Full-Time"},
            {"fieldLabel": "Job Category", "valueLabel": "Administration & Human Resources"},
            {"fieldLabel": "Salary Type", "valueLabel": "Annual"},
            {"fieldLabel": "Salary Min", "valueLabel": "$68,213.00"},
            {"fieldLabel": "Salary Max", "valueLabel": "$73,561.00"},
            {"fieldLabel": "Posted On Date", "valueLabel": "2026-08-07"},
            {"fieldLabel": "Expire Date", "valueLabel": "2026-08-31"},
            {"fieldLabel": "Work Location", "valueLabel": "5 Manhattan West"},
            {"fieldLabel": "Division / Work Unit", "valueLabel": "Fleet Operations"},
            {"fieldLabel": "Preferred Skills", "valueLabel": "Valid driver license."},
            {"fieldLabel": "Title Code", "valueLabel": "10251"},
        ],
    }


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_json(self, url: str) -> dict:
        self.urls.append(url)
        if "?" in url:
            return {
                "offset": 0,
                "limit": 2,
                "totalFound": 3,
                "content": [sample_listing(1), sample_listing(2)],
            }
        record = sample_listing(1 if url.endswith("posting-1") else 2)
        return {
            **record,
            "postingUrl": f"https://jobs.smartrecruiters.com/CityOfNewYork/{record['id']}",
            "applyUrl": f"https://jobs.smartrecruiters.com/CityOfNewYork/{record['id']}?oga=true",
            "active": True,
            "jobAd": {
                "sections": {
                    "jobDescription": {
                        "text": "<p>Coordinate the municipal fleet.<br>Maintain records.</p>"
                    },
                    "qualifications": {
                        "text": "<p>Two years of fleet operations experience.</p>"
                    },
                },
                "compensation": {"min": 68213, "max": 73561, "currency": "USD"},
            },
        }


class NYCCityJobsAdapterTest(TestCase):
    def test_html_to_text_preserves_readable_breaks(self):
        self.assertEqual(
            html_to_text("<p>First line<br>Second line</p><ul><li>Third line</li></ul>"),
            "First line\nSecond line\n\n- Third line",
        )

    def test_collects_limited_records_and_loads_details(self):
        client = FakeClient()
        adapter = NYCCityJobsAdapter(client=client, workers=2)

        result = adapter.collect(limit=2)

        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.metadata["site_reported_count"], 3)
        self.assertTrue(all(record["_details_included"] for record in result.records))
        self.assertEqual(len(client.urls), 3)

    def test_normalizes_full_posting(self):
        record = FakeClient().get_json(
            "https://api.smartrecruiters.com/v1/companies/CityOfNewYork/postings/posting-1"
        )
        record["_details_included"] = True
        job = NYCCityJobsAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 9, tzinfo=timezone.utc)
        )

        self.assertEqual(job.external_id, "790851")
        self.assertEqual(job.employer_name, "OFF OF PAYROLL ADMINISTRATION")
        self.assertEqual(job.source_agency, "OFF OF PAYROLL ADMINISTRATION")
        self.assertEqual(job.source_department, "Fleet Operations")
        self.assertEqual(job.borough, "MANHATTAN")
        self.assertEqual(job.location_text, "5 Manhattan West")
        self.assertEqual(job.salary_min, Decimal("68213"))
        self.assertEqual(job.salary_max, Decimal("73561"))
        self.assertEqual(job.salary_period, "year")
        self.assertEqual(job.work_mode, "on_site")
        self.assertEqual(job.posted_at.isoformat(), "2026-08-07T00:00:00-04:00")
        self.assertEqual(job.closes_on.isoformat(), "2026-08-31")
        self.assertIn("Two years of fleet operations experience.", job.requirements_text)
        self.assertEqual(len(job.requirements), 2)
        self.assertEqual(job.status, "active")
        self.assertTrue(job.source_metadata["details_included"])
        self.assertEqual(len(job.content_hash), 64)

    def test_listing_only_builds_a_public_url(self):
        record = {**sample_listing(), "_details_included": False}
        job = NYCCityJobsAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 9, tzinfo=timezone.utc)
        )

        self.assertEqual(
            job.canonical_url,
            "https://jobs.smartrecruiters.com/CityOfNewYork/posting-1-fleet-coordinator",
        )
        self.assertIsNone(job.description_text)
        self.assertFalse(job.source_metadata["details_included"])
