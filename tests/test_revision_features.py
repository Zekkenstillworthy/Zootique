import unittest

from app import create_app
from models import Animal, Booking, BookingPayment, BookingTicket, User, Zoo, ZooZone, db
from services.booking_service import process_booking_checkout
from services.payment import MockPaymentProvider


class RevisionFeatureTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_trivia_api_requires_json_errors_for_anonymous_requests(self):
        response = self.client.post("/visitor/api/trivia/submit", json={})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.content_type, "application/json")
        self.assertEqual(response.get_json()["success"], False)

    def test_empty_zone_does_not_fall_back_to_unrelated_animals(self):
        with self.app.app_context():
            zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            self.created_zoo = False
            if zoo is None:
                zoo = Zoo(name="Test Zoo", type="Zoo Park", location="Test Location")
                db.session.add(zoo)
                db.session.flush()
                self.created_zoo = True
            zone = ZooZone(zoo_id=zoo.id, name="Test Empty Zone")
            db.session.add(zone)
            db.session.flush()
            zoo_id = zoo.id
            Animal.query.filter_by(zoo_id=zoo.id, zone_id=zone.id).delete()
            zone_id = zone.id
            db.session.commit()

        response = self.client.get(f"/visitor/api/zones/{zone_id}/animals")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["animals"], [])

        with self.app.app_context():
            zone = db.session.get(ZooZone, zone_id)
            if zone:
                db.session.delete(zone)
            if self.created_zoo:
                zoo = db.session.get(Zoo, zoo_id)
                if zoo:
                    db.session.delete(zoo)
                db.session.commit()

    def test_local_payment_provider_is_explicitly_simulated(self):
        self.assertEqual(MockPaymentProvider.name, "simulated")

    def test_zone_gallery_images_round_trip_and_ignore_invalid_values(self):
        with self.app.app_context():
            zone = ZooZone(zoo_id=1, name="Gallery Test Zone")
            zone.image_urls = ["/uploads/zone_images/one.jpg", "", 42]
            self.assertEqual(zone.image_urls, ["/uploads/zone_images/one.jpg"])
            zone.image_urls_json = '{"not": "a list"}'
            self.assertEqual(zone.image_urls, [])

    def test_checkout_is_idempotent_for_the_same_booking_and_method(self):
        with self.app.app_context():
            user = User(
                email="revision-payment@example.com",
                full_name="Revision Payment",
                role="visitor",
                status="active",
            )
            user.set_password("Password123!")
            booking = Booking(
                id="REV-PAYMENT-1",
                visitor_name=user.full_name,
                date="2099-01-01",
                time="09:00",
                guests=1,
                status="Pending",
                amount=100,
                payment_status="unpaid",
            )
            db.session.add_all([user, booking])
            db.session.commit()

            first = process_booking_checkout(
                booking=booking,
                payer=user,
                payment_method="card",
            )
            second = process_booking_checkout(
                booking=booking,
                payer=user,
                payment_method="card",
            )

            self.assertEqual(first.id, second.id)
            self.assertEqual(
                BookingPayment.query.filter_by(booking_id=booking.id).count(),
                1,
            )

            db.session.delete(first)
            db.session.delete(booking)
            db.session.delete(user)
            db.session.commit()

    def test_checkout_redirects_to_confirmed_and_renders_receipt(self):
        with self.app.app_context():
            zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            user = User(
                email="checkout-confirm-test@example.com",
                full_name="Checkout Tester",
                role="visitor",
                status="active",
            )
            user.set_password("Password123!")
            booking = Booking(
                id="BK-CONFIRM-999",
                zoo_id=zoo.id if zoo else None,
                user=user,
                visitor_name=user.full_name,
                date="2099-05-10",
                time="10:00",
                guests=2,
                status="Pending",
                amount=350,
                payment_status="unpaid",
            )
            db.session.add_all([user, booking])
            db.session.commit()
            user_id = user.id
            booking_id = booking.id
            zoo_id = zoo.id if zoo else None

        try:
            with self.client.session_transaction() as sess:
                sess["user_id"] = user_id
                sess["role"] = "visitor"
                if zoo_id:
                    sess["selected_zoo_id"] = zoo_id
                sess["_csrf_token"] = "test-csrf-token"

            # Post checkout payment
            res = self.client.post(
                "/visitor/checkout",
                data={
                    "csrf_token": "test-csrf-token",
                    "booking_id": booking_id,
                    "payment_method": "gcash",
                },
                follow_redirects=False,
            )
            self.assertEqual(res.status_code, 302)
            self.assertIn(f"/visitor/checkout/confirmed?booking_id={booking_id}", res.headers["Location"])

            # Follow to confirmation page
            conf_res = self.client.get(f"/visitor/checkout/confirmed?booking_id={booking_id}")
            self.assertEqual(conf_res.status_code, 200)
            self.assertIn("Payment &amp; Booking Confirmed!", conf_res.get_data(as_text=True))
            self.assertIn(booking_id, conf_res.get_data(as_text=True))
        finally:
            with self.app.app_context():
                BookingTicket.query.filter_by(booking_id=booking_id).delete()
                BookingPayment.query.filter_by(booking_id=booking_id).delete()
                b = db.session.get(Booking, booking_id)
                if b:
                    db.session.delete(b)
                u = db.session.get(User, user_id)
                if u:
                    db.session.delete(u)
                db.session.commit()


if __name__ == "__main__":
    unittest.main()