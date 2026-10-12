from types import SimpleNamespace
import unittest
from unittest.mock import patch

from services.subscription_catalog import (
    infer_tier_level,
    plan_context,
    sort_plans,
    tier_label,
)
from services.subscription_guard import can_edit_feature, feature_required_tier, limit_allows


class SubscriptionCatalogTestCase(unittest.TestCase):
    def test_stored_plan_names_have_distinct_canonical_tiers(self):
        self.assertEqual(infer_tier_level("Standard"), 1)
        self.assertEqual(infer_tier_level("Pro"), 2)
        self.assertEqual(tier_label(1), "Standard Tier")
        self.assertEqual(tier_label(2), "Pro Tier")

    def test_plan_sorting_uses_tier_then_price(self):
        plans = [
            SimpleNamespace(name="Pro", tier_level=2, price=9999),
            SimpleNamespace(name="Standard", tier_level=1, price=4999),
            SimpleNamespace(name="Free", tier_level=0, price=0),
        ]
        self.assertEqual([plan.name for plan in sort_plans(plans)], ["Free", "Standard", "Pro"])

    def test_plan_context_uses_real_plan_tier(self):
        context = plan_context(SimpleNamespace(
            id=3,
            name="Pro",
            tier_level=2,
            price=9999,
            duration="monthly",
            duration_months=1,
            features="Everything in Standard\nAnalytics",
            is_active=True,
        ))
        self.assertEqual(context["tier_label"], "Pro Tier")
        self.assertEqual(context["features"], ("Everything in Standard", "Analytics"))

    def test_guard_uses_canonical_tier_requirements(self):
        zoo = SimpleNamespace(id=1)
        with patch("services.subscription_guard.get_zoo_subscription_tier", return_value=1):
            self.assertFalse(can_edit_feature(zoo, "analytics"))

    def test_staff_management_and_limits_match_standard_plan(self):
        self.assertEqual(feature_required_tier("staff_management"), 1)
        zoo = SimpleNamespace(id=1)
        with patch("services.subscription_guard.feature_limit", return_value=3):
            self.assertTrue(limit_allows(zoo, "staff_accounts", 2))
            self.assertFalse(limit_allows(zoo, "staff_accounts", 3))


if __name__ == "__main__":
    unittest.main()
