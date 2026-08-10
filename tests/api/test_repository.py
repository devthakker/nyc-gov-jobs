from __future__ import annotations

import unittest

from app.api.models import JobQueryParams, JobSort, JobStatus, WorkMode
from app.api.repository import ReadOnlyJobRepository


class ReadOnlyQueryConstructionTests(unittest.TestCase):
    def test_filter_values_are_parameters_not_sql_fragments(self) -> None:
        malicious = "customer-service') OR TRUE --"
        filters = JobQueryParams(
            q="help desk",
            track=[malicious],
            source=["mta"],
            state=["ny"],
            status=[JobStatus.ACTIVE],
            work_mode=[WorkMode.HYBRID],
            salary_available=True,
            primary_track_only=True,
        )

        sql, parameters = ReadOnlyJobRepository._where(filters)

        self.assertNotIn(malicious, sql)
        self.assertIn([malicious.lower()], parameters)
        self.assertIn("jt.is_primary", sql)
        self.assertIn("salary_min IS NOT NULL", sql)

    def test_sorting_uses_a_fixed_allowlist(self) -> None:
        sql, parameters = ReadOnlyJobRepository._order_by(
            JobQueryParams(q="support", sort=JobSort.RELEVANCE)
        )

        self.assertIn("ts_rank", sql)
        self.assertEqual(parameters, ["support"])

    def test_relevance_without_search_falls_back_to_newest(self) -> None:
        sql, parameters = ReadOnlyJobRepository._order_by(
            JobQueryParams(sort=JobSort.RELEVANCE)
        )

        self.assertNotIn("ts_rank", sql)
        self.assertIn("DESC", sql)
        self.assertEqual(parameters, [])


if __name__ == "__main__":
    unittest.main()
