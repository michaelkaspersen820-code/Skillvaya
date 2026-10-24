"""Regression tests for additive Skillvaya subscription entitlements."""
import unittest

from subscription_entitlements import features_for, has_feature, normalize_plan


class SubscriptionEntitlementsTests(unittest.TestCase):
    def test_existing_plan_ids_remain_valid(self):
        self.assertEqual(normalize_plan("local"), "local")
        self.assertEqual(normalize_plan("priority"), "priority")
        self.assertEqual(normalize_plan("plus"), "plus")
        self.assertEqual(normalize_plan("spotlight"), "spotlight")

    def test_business_plus_includes_business_tools(self):
        for feature in (
            "lead_pipeline", "customer_booking_calendar", "crm",
            "quotation_followups", "invoice_payment_tracking",
            "customer_service_packages", "advanced_analytics",
        ):
            with self.subTest(feature=feature):
                self.assertTrue(has_feature("plus", feature))

    def test_spotlight_inherits_plus_and_adds_promotion_tools(self):
        for feature in features_for("plus"):
            self.assertTrue(has_feature("spotlight", feature))
        for feature in (
            "featured_placement", "campaign_management", "promotional_offers",
            "vouchers", "branded_provider_page", "team_management",
            "lead_source_analytics", "priority_automation",
            "customer_announcements",
        ):
            with self.subTest(feature=feature):
                self.assertTrue(has_feature("spotlight", feature))
                self.assertFalse(has_feature("plus", feature))

    def test_unknown_plans_fail_closed(self):
        self.assertEqual(features_for("unknown"), frozenset())
        self.assertEqual(features_for(None), frozenset())
        self.assertFalse(has_feature("unknown", "featured_placement"))

    def test_display_name_aliases(self):
        self.assertEqual(normalize_plan("Business Plus"), "plus")
        self.assertEqual(normalize_plan("Business Spotlight"), "spotlight")


if __name__ == "__main__":
    unittest.main()
