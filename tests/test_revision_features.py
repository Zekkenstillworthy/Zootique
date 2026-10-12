import unittest

from app import create_app
from models import Animal, Booking, BookingPayment, User, Zoo, ZooZone, db
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


if __name__ == "__main__":
    unittest.main()