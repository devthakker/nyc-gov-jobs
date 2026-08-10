from unittest import TestCase

from app.classification import (
    CLASSIFIER_VERSION,
    TAXONOMY_VERSION,
    classification_counts,
    classify_job,
)


class ClassificationTest(TestCase):
    def test_apprenticeship_gets_training_primary_and_trade_secondary(self):
        assignments = classify_job(
            {
                "source_key": "nysdol_apprenticeships",
                "title": "Electricians JAC Buffalo LU #41",
                "source_category": "Apprenticeship",
            }
        )

        self.assertEqual(assignments[0].track_slug, "apprenticeships-entry-level-training")
        self.assertTrue(assignments[0].is_primary)
        self.assertEqual(assignments[0].method, "source_map")
        self.assertIn(
            "construction-skilled-trades-facilities",
            [assignment.track_slug for assignment in assignments[1:]],
        )

    def test_native_category_can_be_overridden_by_stronger_title(self):
        assignments = classify_job(
            {
                "source_key": "mta",
                "title": "Database Administrator MS Access, Emerging Talent Intern (Fall)",
                "source_category": "Administrative & Clerical",
                "source_department": "Department of Subways",
            }
        )

        self.assertEqual(assignments[0].track_slug, "it-data-cybersecurity")
        self.assertEqual(assignments[0].method, "rule")
        self.assertIn("apprenticeships-entry-level-training", [a.track_slug for a in assignments])
        self.assertIn("administrative-office-support", [a.track_slug for a in assignments])

    def test_new_legal_track_avoids_forcing_attorney_into_admin(self):
        assignments = classify_job(
            {
                "source_key": "port_authority",
                "title": "Attorney",
                "source_category": "Corporate",
            }
        )

        self.assertEqual([assignment.track_slug for assignment in assignments], ["legal-compliance-policy"])

    def test_cloud_architect_is_it_primary_with_engineering_secondary(self):
        assignments = classify_job(
            {
                "source_key": "port_authority",
                "title": "Senior Cloud Architect & Program Manager",
                "source_category": "Engineering",
            }
        )

        self.assertEqual(assignments[0].track_slug, "it-data-cybersecurity")
        self.assertEqual(assignments[1].track_slug, "engineering-architecture-planning")
        self.assertTrue(all(item.review_status == "needs_review" for item in assignments))

    def test_description_build_word_does_not_imply_construction(self):
        assignments = classify_job(
            {
                "source_key": "test",
                "title": "IT Project Manager",
                "description_text": "Build systems and manage software delivery teams.",
            }
        )

        slugs = [assignment.track_slug for assignment in assignments]
        self.assertNotIn("construction-skilled-trades-facilities", slugs)
        self.assertIn("management-supervision", slugs)

    def test_nyp_native_it_category_maps_to_it_track(self):
        assignments = classify_job(
            {
                "source_key": "newyork_presbyterian",
                "title": "Service Management Analyst",
                "source_category": "Information Technology",
            }
        )

        self.assertEqual(assignments[0].track_slug, "it-data-cybersecurity")
        self.assertEqual(assignments[0].method, "source_map")

    def test_statejobs_native_clerical_category_maps_to_admin_track(self):
        assignments = classify_job(
            {
                "source_key": "statejobsny",
                "title": "Keyboard Specialist 1",
                "source_category": "Clerical, Secretarial, Office Aide",
            }
        )

        self.assertEqual(assignments[0].track_slug, "administrative-office-support")
        self.assertEqual(assignments[0].method, "source_map")

    def test_amtrak_railroad_operations_maps_to_transportation(self):
        assignments = classify_job(
            {
                "source_key": "amtrak",
                "title": "Trainmaster",
                "source_category": "Railroad Operations",
            }
        )

        self.assertEqual(assignments[0].track_slug, "transportation-logistics-fleet")
        self.assertEqual(assignments[0].method, "source_map")

    def test_wave_2_customer_categories_use_seeded_customer_track(self):
        for source_key, category in (
            ("amtrak", "Customer Service"),
            ("northwell", "Patient and Customer Experience"),
        ):
            with self.subTest(source_key=source_key):
                assignments = classify_job(
                    {
                        "source_key": source_key,
                        "title": "Customer Experience Representative",
                        "source_category": category,
                    }
                )

                self.assertEqual(assignments[0].track_slug, "customer-service")

    def test_northwell_clinical_support_maps_to_clinical_track(self):
        assignments = classify_job(
            {
                "source_key": "northwell",
                "title": "Patient Care Associate",
                "source_category": "Clinical Support",
            }
        )

        self.assertEqual(assignments[0].track_slug, "clinical-patient-support")
        self.assertEqual(assignments[0].method, "source_map")

    def test_cuny_it_category_maps_to_it_track(self):
        assignments = classify_job(
            {
                "source_key": "cuny",
                "title": "IT Assistant",
                "source_category": "Information Technology/Technical",
            }
        )

        self.assertEqual(assignments[0].track_slug, "it-data-cybersecurity")
        self.assertEqual(assignments[0].method, "source_map")

    def test_resorts_world_facilities_maps_to_trades(self):
        assignments = classify_job(
            {
                "source_key": "resorts_world_nyc",
                "title": "Facilities Technician",
                "source_category": "Facilities",
            }
        )

        self.assertEqual(assignments[0].track_slug, "construction-skilled-trades-facilities")
        self.assertEqual(assignments[0].method, "source_map")

    def test_ed_technician_is_high_confidence_clinical_support(self):
        assignments = classify_job(
            {
                "source_key": "newyork_presbyterian",
                "title": "ED Technician - Emergency Department - Full Time Night",
                "source_category": "Emergency Services",
            }
        )

        self.assertEqual(assignments[0].track_slug, "clinical-patient-support")
        self.assertEqual(assignments[0].confidence, 0.960)

    def test_marketing_trainee_keeps_occupation_as_primary_track(self):
        assignments = classify_job(
            {
                "source_key": "statejobsny",
                "title": "Marketing & Events Specialist, Trainee 1/2",
                "source_category": "Other Professional Careers",
            }
        )

        self.assertEqual(assignments[0].track_slug, "communications-marketing")
        self.assertEqual(assignments[1].track_slug, "apprenticeships-entry-level-training")

    def test_assignment_metadata_is_versioned_and_countable(self):
        finance = classify_job(
            {
                "source_key": "port_authority",
                "title": "Staff Financial Analyst",
                "source_category": "Finance",
            }
        )
        legal = classify_job(
            {
                "source_key": "port_authority",
                "title": "Attorney",
                "source_category": "Corporate",
            }
        )
        primary, secondary = classification_counts([finance, legal])

        self.assertEqual(finance[0].taxonomy_version, TAXONOMY_VERSION)
        self.assertIn(CLASSIFIER_VERSION, finance[0].reason)
        self.assertEqual(primary["finance-purchasing-accounting"], 1)
        self.assertEqual(primary["legal-compliance-policy"], 1)
        self.assertEqual(secondary, {})
