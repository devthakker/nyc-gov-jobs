from datetime import datetime, timezone
from decimal import Decimal
from unittest import TestCase

from app.adapters.statejobsny import (
    VACANCY_TABLE_URL,
    StateJobsNYAdapter,
    parse_detail_html,
    parse_listing_html,
    parse_salary,
)


LISTING_HTML = """
<table id="vacancyTable"><thead><tr><th>Item #</th></tr></thead><tbody>
<tr><td>221490</td><td><a href="vacancyDetailsView.cfm?id=221490">Marketing &amp; Events Specialist</a></td><td>18</td><td>08/10/26</td><td>08/20/26</td><td>Motor Vehicles, Department of</td><td>Albany</td></tr>
<tr><td>221491</td><td><a href="vacancyDetailsView.cfm?id=221491">Administrative Assistant</a></td><td>11</td><td>08/09/26</td><td>08/21/26</td><td>Health, Department of</td><td>New York</td></tr>
</tbody></table>
"""


DETAIL_HTML = """
<div class="columnReport">
<p class="row"><span class="leftCol">Date Posted</span><span class="rightCol">08/10/26</span></p>
<p class="row"><span class="leftCol">Applications Due</span><span class="rightCol">08/20/26</span></p>
<p class="row"><span class="leftCol">Vacancy ID</span><span class="rightCol">221490</span></p>
</div>
<div id="vacancyDetails">
<div id="information">
<p class="row"><span class="leftCol">NY HELP</span><span class="rightCol">Yes</span></p>
<p class="row"><span class="leftCol">Agency</span><span class="rightCol">Motor Vehicles, Department of</span></p>
<p class="row"><span class="leftCol">Title</span><span class="rightCol">Marketing &amp; Events Specialist</span></p>
<p class="row"><span class="leftCol">Occupational Category</span><span class="rightCol">Other Professional Careers</span></p>
<p class="row"><span class="leftCol">Salary Grade</span><span class="rightCol">18</span></p>
<p class="row"><span class="leftCol">Salary Range</span><span class="rightCol">From $53764 to $85138 Annually</span></p>
<p class="row"><span class="leftCol">Employment Type</span><span class="rightCol">Full-Time</span></p>
<p class="row"><span class="leftCol">Appointment Type</span><span class="rightCol">Permanent</span></p>
</div>
<div id="schedule">
<p class="row"><span class="leftCol">Workweek</span><span class="rightCol">Mon-Fri</span></p>
<p class="row"><span class="leftCol">Hours Per Week</span><span class="rightCol">37.5</span></p>
<p class="row"><span class="leftCol">Telecommuting allowed?</span><span class="rightCol">Yes</span></p>
</div>
<div id="location">
<p class="row"><span class="leftCol">County</span><span class="rightCol">Albany</span></p>
<p class="row"><span class="leftCol">Street Address</span><span class="rightCol">6 Empire State Plaza</span></p>
<p class="row"><span class="leftCol">City</span><span class="rightCol">Albany</span></p>
<p class="row"><span class="leftCol">State</span><span class="rightCol">NY</span></p>
<p class="row"><span class="leftCol">Zip Code</span><span class="rightCol">12228</span></p>
</div>
<div id="jobspecifics">
<p class="row"><span class="leftCol">Duties Description</span><span class="rightCol">Coordinate public events.<br>Prepare materials.</span></p>
<p class="row"><span class="leftCol">Minimum Qualifications</span><span class="rightCol">Four years of communications experience.</span></p>
<p class="row"><span class="leftCol">Additional Comments</span><span class="rightCol">Travel may be required.</span></p>
</div>
</div>
"""


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return LISTING_HTML if url == VACANCY_TABLE_URL else DETAIL_HTML


class StateJobsNYAdapterTest(TestCase):
    def test_reversed_source_salary_range_is_normalized(self):
        minimum, maximum, period = parse_salary(
            "From $48,855 to $48,743 Annually"
        )

        self.assertEqual(minimum, Decimal("48743"))
        self.assertEqual(maximum, Decimal("48855"))
        self.assertEqual(period, "year")

    def test_listing_parser_reads_public_vacancy_table(self):
        records = parse_listing_html(LISTING_HTML)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["id"], "221490")
        self.assertEqual(records[0]["agency"], "Motor Vehicles, Department of")
        self.assertEqual(records[0]["county"], "Albany")
        self.assertTrue(records[0]["url"].endswith("id=221490"))

    def test_detail_parser_scopes_repeated_labels(self):
        fields = parse_detail_html(DETAIL_HTML)

        self.assertEqual(fields["overview.vacancy id"], "221490")
        self.assertEqual(fields["information.occupational category"], "Other Professional Careers")
        self.assertEqual(fields["location.city"], "Albany")
        self.assertIn("Prepare materials", fields["jobspecifics.duties description"])

    def test_collect_limits_before_detail_requests(self):
        client = FakeClient()
        result = StateJobsNYAdapter(client=client).collect(limit=1)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.metadata["site_reported_count"], 2)
        self.assertTrue(result.records[0]["_details_included"])
        self.assertEqual(len(client.urls), 2)

    def test_normalizes_full_vacancy(self):
        record = {
            **parse_listing_html(LISTING_HTML)[0],
            "detail": parse_detail_html(DETAIL_HTML),
            "_details_included": True,
        }
        job = StateJobsNYAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(job.external_id, "221490")
        self.assertEqual(job.employer_name, "Motor Vehicles, Department of")
        self.assertEqual(job.source_category, "Other Professional Careers")
        self.assertEqual(job.location_text, "6 Empire State Plaza, Albany, NY, 12228")
        self.assertEqual(job.region, "Albany")
        self.assertEqual(job.salary_min, Decimal("53764"))
        self.assertEqual(job.salary_max, Decimal("85138"))
        self.assertEqual(job.salary_period, "year")
        self.assertEqual(job.work_mode, "hybrid")
        self.assertEqual(job.closes_on.isoformat(), "2026-08-20")
        self.assertIn("Four years of communications", job.requirements_text)
        self.assertTrue(job.source_metadata["details_included"])

    def test_listing_only_keeps_vacancy_identity(self):
        record = {**parse_listing_html(LISTING_HTML)[0], "_details_included": False}
        job = StateJobsNYAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(job.external_id, "221490")
        self.assertEqual(job.employer_name, "Motor Vehicles, Department of")
        self.assertIsNone(job.description_text)
        self.assertFalse(job.source_metadata["details_included"])

    def test_normalize_does_not_duplicate_state_embedded_in_city(self):
        detail = parse_detail_html(DETAIL_HTML)
        detail["location.city"] = "New York, NY"
        record = {
            **parse_listing_html(LISTING_HTML)[0],
            "detail": detail,
            "_details_included": True,
        }

        job = StateJobsNYAdapter(client=FakeClient()).normalize(
            record, datetime(2026, 8, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(job.city, "New York")
        self.assertNotIn("New York, NY, NY", job.location_text)
