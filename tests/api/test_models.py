from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.api.models import (
    JobQueryParams,
    NewsletterSubscriptionRequest,
    PaginationResponse,
    RequirementResponse,
)


class JobQueryModelTests(unittest.TestCase):
    def test_normalizes_and_deduplicates_list_filters(self) -> None:
        query = JobQueryParams(
            track=[" Customer-Service ", "customer-service"],
            source=[" MTA "],
            state=["ny", "NY"],
        )

        self.assertEqual(query.track, ["customer-service"])
        self.assertEqual(query.source, ["mta"])
        self.assertEqual(query.state, ["NY"])

    def test_rejects_unknown_fields_and_bad_state_codes(self) -> None:
        with self.assertRaises(ValidationError):
            JobQueryParams(unexpected="value")
        with self.assertRaises(ValidationError):
            JobQueryParams(state=["New York"])

    def test_page_size_has_a_hard_limit(self) -> None:
        with self.assertRaises(ValidationError):
            JobQueryParams(page_size=101)


class ResponseModelTests(unittest.TestCase):
    def test_requirement_normalizes_source_strings(self) -> None:
        model = RequirementResponse.model_validate("Must be at least 18 years old.")
        self.assertEqual(model.text, "Must be at least 18 years old.")
        self.assertIsNone(model.type)

    def test_pagination_handles_empty_and_later_pages(self) -> None:
        empty = PaginationResponse.from_query(page=1, page_size=20, total_items=0)
        later = PaginationResponse.from_query(page=2, page_size=20, total_items=45)

        self.assertEqual(empty.total_pages, 0)
        self.assertFalse(empty.has_next)
        self.assertEqual(later.total_pages, 3)
        self.assertTrue(later.has_next)
        self.assertTrue(later.has_previous)


class NewsletterSubscriptionModelTests(unittest.TestCase):
    def test_normalizes_identity_and_track_preferences(self) -> None:
        request = NewsletterSubscriptionRequest(
            email="Devin@Example.com",
            name="  Devin   Smith ",
            all_tracks=False,
            track_slugs=[" IT-Data-Cybersecurity ", "it-data-cybersecurity"],
            consent=True,
        )

        self.assertEqual(request.email, "devin@example.com")
        self.assertEqual(request.name, "Devin Smith")
        self.assertEqual(request.track_slugs, ["it-data-cybersecurity"])

    def test_requires_affirmative_consent_and_unambiguous_preferences(self) -> None:
        with self.assertRaises(ValidationError):
            NewsletterSubscriptionRequest(
                email="devin@example.com", all_tracks=True, consent=False
            )
        with self.assertRaises(ValidationError):
            NewsletterSubscriptionRequest(
                email="devin@example.com", all_tracks=False, consent=True
            )
        with self.assertRaises(ValidationError):
            NewsletterSubscriptionRequest(
                email="devin@example.com",
                all_tracks=True,
                track_slugs=["customer-service"],
                consent=True,
            )


if __name__ == "__main__":
    unittest.main()
