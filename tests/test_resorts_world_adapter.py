from datetime import datetime, timezone
from unittest import TestCase

from app.adapters.resorts_world import ResortsWorldNYCAdapter, search_payload, validate_search


def listing(number: int) -> dict:
    return {
        "title": f"Guest Services Representative {number}",
        "externalPath": f"/job/Resorts-World-New-York/Guest-Services-{number}_JR-{number:05d}",
        "timeType": "Full time",
        "locationsText": "Resorts World New York",
        "postedOn": "Posted 2 Days Ago",
        "bulletFields": [f"JR-{number:05d}"],
    }


def detail(number: int) -> dict:
    return {
        "id": f"posting-{number}",
        "title": f"Guest Services Representative {number}",
        "jobDescription": """
          <h1>Job Responsibilities</h1><p>Assist casino guests.</p>
          <p><b>Essential Requirements:</b></p><ul><li>Customer service experience.</li></ul>
          <p><b>Knowledge/Work Experience:</b></p><ul><li>High school diploma preferred.</li></ul>
        """,
        "location": "Resorts World New York",
        "startDate": "2026-08-08",
        "timeType": "Full time",
        "jobReqId": f"JR-{number:05d}",
        "externalUrl": f"https://rwlasvegas.wd501.myworkdayjobs.com/Resorts_World_External_Careers/job/{number}",
    }


class FakeClient:
    def __init__(self) -> None:
        self.rows = [listing(number) for number in range(1, 22)]
        self.posts: list[dict] = []
        self.gets: list[str] = []

    def post_json(self, url: str, payload: dict) -> dict:
        self.posts.append(payload)
        offset = payload["offset"]
        result = {
            "total": len(self.rows),
            "jobPostings": self.rows[offset:offset + payload["limit"]],
            "facets": [],
        }
        if not payload["appliedFacets"]:
            result["facets"] = [{
                "facetParameter": "jobFamilyGroup",
                "descriptor": "Job Category",
                "values": [{"descriptor": "Casino Operations", "id": "casino", "count": 21}],
            }]
        return result

    def get_json(self, url: str) -> dict:
        self.gets.append(url)
        number = int(url.rsplit("_JR-", 1)[1])
        return {"jobPostingInfo": detail(number)}


class ResortsWorldAdapterTest(TestCase):
    def test_search_contract_and_validation(self):
        payload = search_payload(offset=20, facets={"jobFamilyGroup": ["casino"]})
        rows, total = validate_search({"total": 1, "jobPostings": [listing(1)]})

        self.assertEqual(payload["offset"], 20)
        self.assertEqual(payload["appliedFacets"], {"jobFamilyGroup": ["casino"]})
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["bulletFields"], ["JR-00001"])

    def test_collect_paginates_maps_categories_and_loads_details(self):
        client = FakeClient()
        result = ResortsWorldNYCAdapter(client=client, workers=2).collect()

        self.assertEqual(len(result.records), 21)
        self.assertEqual(result.metadata["site_reported_count"], 21)
        self.assertEqual(result.metadata["category_mapping_coverage"], 21)
        self.assertTrue(all(record["category"] == "Casino Operations" for record in result.records))
        self.assertEqual(len(client.posts), 4)
        self.assertEqual(len(client.gets), 21)

    def test_collect_limit_does_not_reconcile_full_count(self):
        client = FakeClient()
        result = ResortsWorldNYCAdapter(client=client, include_details=False).collect(limit=2)

        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.metadata["site_reported_count"], 21)
        self.assertFalse(result.records[0]["_details_included"])

    def test_normalizes_workday_posting(self):
        record = {
            **listing(1),
            "category": "Casino Operations",
            "detail": detail(1),
            "_details_included": True,
        }
        job = ResortsWorldNYCAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(job.external_id, "JR-00001")
        self.assertEqual(job.source_category, "Casino Operations")
        self.assertEqual(job.city, "Jamaica")
        self.assertEqual(job.state, "NY")
        self.assertEqual(job.postal_code, "11420")
        self.assertIn("Customer service experience", job.requirements_text)
        self.assertEqual(job.posted_at.isoformat(), "2026-08-08T00:00:00-04:00")

