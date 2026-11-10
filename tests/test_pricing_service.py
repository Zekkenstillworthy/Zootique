from datetime import date
from types import SimpleNamespace
import unittest

from services.loyalty import points_discount
from services.pricing import PricingError, calculate_booking_price, guest_limits


class PricingServiceTestCase(unittest.TestCase):
    def test_bundle_and_add_on_are_calculated_once(self):
        service = SimpleNamespace(id=1, zoo_id=7, name="Park Entry", price=100)
        bundle = SimpleNamespace(
            id=2, zoo_id=7, service_id=1, name="Family", price=80,
            discount_type="none", discount_value=0, min_guests=2, max_guests=6,
            valid_from=None, valid_until=None, is_active=True,
        )
        add_on = SimpleNamespace(id=3, zoo_id=7, name="Animal Encounter", price=25)

        result = calculate_booking_price(service=service, bundle=bundle, guests=4, add_ons=[add_on], visit_date=date.today())

        self.assertEqual(result.subtotal, 105.0)
        self.assertEqual(result.total, 105.0)
        self.assertEqual(len(result.lines), 2)

    def test_bundle_guest_limits_are_enforced(self):
        service = SimpleNamespace(id=1, zoo_id=7, name="Park Entry", price=100)
        bundle = SimpleNamespace(
            zoo_id=7, service_id=1, name="Family", price=80, discount_type="none", discount_value=0,
            min_guests=2, max_guests=6, valid_from=None, valid_until=None, is_active=True,
        )

        with self.assertRaises(PricingError):
            calculate_booking_price(service=service, bundle=bundle, guests=1)

    def test_guest_limits_use_the_stricter_service_and_bundle_range(self):
        service = SimpleNamespace(max_guest_capacity=5)
        bundle = SimpleNamespace(min_guests=4, max_guests=10)

        self.assertEqual(guest_limits(service=service), (1, 5))
        self.assertEqual(guest_limits(service=service, bundle=bundle), (4, 5))

    def test_booking_points_discount_is_fixed_in_steps_of_100(self):
        self.assertEqual(points_discount(0), 0.0)
        self.assertEqual(points_discount(300), 30.0)
        self.assertEqual(points_discount(1300), 130.0)
        with self.assertRaises(ValueError):
            points_discount(250)
        with self.assertRaises(ValueError):
            points_discount(-100)

    def test_bundle_must_belong_to_selected_service(self):
        service = SimpleNamespace(id=1, zoo_id=7, name="Park Entry", price=100)
        bundle = SimpleNamespace(
            id=2, zoo_id=7, service_id=99, name="Family", price=80,
            discount_type="none", discount_value=0, min_guests=1, max_guests=6,
            valid_from=None, valid_until=None, is_active=True,
        )

        with self.assertRaises(PricingError):
            calculate_booking_price(service=service, bundle=bundle, guests=2)

    def test_promotion_add_on_and_loyalty_are_included(self):
        service = SimpleNamespace(id=1, zoo_id=7, name="Park Entry", price=100)
        add_on = SimpleNamespace(id=2, zoo_id=7, name="Animal Encounter", price=25)
        promotion = SimpleNamespace(
            zoo_id=7, discount_type="percent", discount_value=10,
            valid_until=None, is_active=True,
        )
        user = SimpleNamespace(id=10)
        account = SimpleNamespace(balance=500)
        setting = SimpleNamespace(
            minimum_redemption_points=10,
            currency_per_point=0.01,
            maximum_redemption_percent=50,
        )

        from unittest.mock import patch
        import services.pricing as pricing
        with patch.object(
            pricing,
            "LoyaltyAccount",
            SimpleNamespace(query=SimpleNamespace(filter_by=lambda **_: SimpleNamespace(first=lambda: account))),
        ), patch.object(pricing, "get_settings", lambda: setting):
            result = calculate_booking_price(
                service=service,
                guests=2,
                add_ons=[add_on],
                promotion=promotion,
                loyalty_points=100,
                user=user,
            )

        self.assertEqual(result.subtotal, 125.0)
        self.assertEqual(result.discount, 12.5)
        self.assertEqual(result.loyalty_discount, 10.0)
        self.assertEqual(result.total, 102.5)


if __name__ == "__main__":
    unittest.main()
