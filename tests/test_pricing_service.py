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

        # service price 100 * 2 guests = 200, add_on 25 -> subtotal before promo: 225.0
        # 10% promo on 225 = 22.5 discount -> subtotal after promo: 202.5
        # loyalty 100 points = 10.0 discount -> total: 192.5
        self.assertEqual(result.subtotal, 225.0)
        self.assertEqual(result.discount, 22.5)
        self.assertEqual(result.loyalty_discount, 10.0)
        self.assertEqual(result.total, 192.5)

    def test_experience_price_is_multiplied_per_guest(self):
        service = SimpleNamespace(id=1, zoo_id=7, name="Farm Learning Tour", price=350)
        result = calculate_booking_price(service=service, guests=3)
        self.assertEqual(result.total, 1050.0)
        self.assertEqual(result.subtotal, 1050.0)
        self.assertEqual(len(result.lines), 1)
        self.assertEqual(result.lines[0].quantity, 3)
        self.assertEqual(result.lines[0].unit_price, 350.0)
        self.assertEqual(result.lines[0].total, 1050.0)

    def test_bundle_price_is_flat_package_not_per_guest(self):
        service = SimpleNamespace(id=1, zoo_id=7, name="Farm Learning Tour", price=350)
        bundle = SimpleNamespace(
            id=2, zoo_id=7, service_id=1, name="Family Bundle", price=1200,
            discount_type="none", discount_value=0, min_guests=2, max_guests=5,
            valid_from=None, valid_until=None, is_active=True,
        )
        result = calculate_booking_price(service=service, bundle=bundle, guests=4)
        self.assertEqual(result.total, 1200.0)
        self.assertEqual(result.subtotal, 1200.0)
        self.assertEqual(len(result.lines), 1)
        self.assertEqual(result.lines[0].quantity, 1)
        self.assertEqual(result.lines[0].unit_price, 1200.0)
        self.assertEqual(result.lines[0].total, 1200.0)


if __name__ == "__main__":
    unittest.main()
