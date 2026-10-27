import unittest

from app import create_app
from models import Booking, Service, SystemSetting, User, Zoo, db
from services.booking_service import BookingValidationError, process_booking_checkout
from services.zoo_settings import get_availability_settings, get_payment_methods, save_zoo_setting


class RemainingFeatureTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_landing_slider_links_to_each_zoo(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            if zoo:
                self.assertIn(f"/visitor/zoos/{zoo.id}", response.get_data(as_text=True))

    def test_public_zoo_text_hides_seed_markers(self):
        with self.app.app_context():
            zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            if not zoo:
                self.skipTest("Seed data does not contain a zoo.")
            response = self.client.get(f"/visitor/zoos/{zoo.id}")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("[zootique-", response.get_data(as_text=True).lower())

    def test_payment_methods_are_scoped_and_enforced(self):
        with self.app.app_context():
            zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            service = Service.query.filter_by(zoo_id=zoo.id).first() if zoo else None
            if not zoo or not service:
                self.skipTest("Seed data does not contain a zoo service.")
            user = User(
                email="remaining-payment@example.com",
                full_name="Remaining Payment",
                role="visitor",
                status="active",
            )
            user.set_password("Password123!")
            booking = Booking(
                id="REM-PAYMENT-1",
                zoo_id=zoo.id,
                service_id=service.id,
                user_id=user.id,
                visitor_name=user.full_name,
                date="2099-01-01",
                time=service.opening_time or "08:00",
                guests=1,
                status="Pending",
                amount=10,
                payment_status="unpaid",
            )
            db.session.add_all([user, booking])
            db.session.flush()
            save_zoo_setting(zoo.id, "payment_methods", ["gcash"])
            db.session.commit()
            self.assertEqual(get_payment_methods(zoo.id), ["gcash"])
            with self.assertRaises(BookingValidationError):
                process_booking_checkout(booking=booking, payer=user, payment_method="card")
            db.session.delete(booking)
            db.session.delete(user)
            SystemSetting.query.filter_by(key=f"zoo:{zoo.id}:payment_methods").delete()
            db.session.commit()

    def test_availability_settings_round_trip(self):
        with self.app.app_context():
            zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            if not zoo:
                self.skipTest("Seed data does not contain a zoo.")
            save_zoo_setting(zoo.id, "availability", {"closure_days": [2, 6], "max_advance_days": 30})
            db.session.commit()
            settings = get_availability_settings(zoo.id)
            self.assertEqual(settings["closure_days"], [2, 6])
            self.assertEqual(settings["max_advance_days"], 30)
            SystemSetting.query.filter_by(key=f"zoo:{zoo.id}:availability").delete()
            db.session.commit()

    def test_booking_quote_endpoint_returns_backend_breakdown(self):
        with self.app.app_context():
            zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            service = Service.query.filter_by(zoo_id=zoo.id).first() if zoo else None
            visitor = User.query.filter_by(role="visitor").first()
            if not zoo or not service or not visitor:
                self.skipTest("Seed data does not contain a visitor service.")
            with self.client.session_transaction() as session:
                session["user_id"] = visitor.id
                session["role"] = "visitor"
                session["selected_zoo_id"] = zoo.id
            response = self.client.get(
                "/visitor/api/booking-quote",
                query_string={"service_id": service.id, "guests": 2},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["success"])
            self.assertIn("lines", payload["quote"])
            self.assertIn("total", payload["quote"])

    def test_booking_page_uses_configured_operating_note_and_passes_anchor(self):
        with self.app.app_context():
            zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            visitor = User.query.filter_by(role="visitor").first()
            if not zoo or not visitor:
                self.skipTest("Seed data does not contain a zoo and visitor.")
            with self.client.session_transaction() as session:
                session["user_id"] = visitor.id
                session["role"] = "visitor"
                session["selected_zoo_id"] = zoo.id

            save_zoo_setting(zoo.id, "availability", {"closure_days": [2]})
            db.session.commit()
            response = self.client.get("/visitor/bookings")
            body = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn('href="#all-reservations"', body)
            self.assertIn("Wednesday", body)
            self.assertNotIn("Mondays are reserved", body)
            self.assertNotIn('id="custom-guests-input"', body)
            self.assertNotIn("api.qrserver.com", body)
            SystemSetting.query.filter_by(key=f"zoo:{zoo.id}:availability").delete()
            db.session.commit()

    def test_delete_booking_cascades_safely(self):
        with self.app.app_context():
            from models import BookingPayment, BookingTicket, Notification
            from uuid import uuid4

            admin_user = User.query.filter(User.role == "animal_farm_admin", User.zoo_id.isnot(None)).first()
            if not admin_user:
                admin_user = User.query.filter(User.zoo_id.isnot(None)).first()
            if not admin_user:
                self.skipTest("No admin user with zoo found.")

            zoo_id = admin_user.zoo_id
            booking_id = f"BK-TEST-{uuid4().hex[:6].upper()}"
            booking = Booking(
                id=booking_id,
                zoo_id=zoo_id,
                visitor_name="Test Deletion",
                date="2099-01-01",
                time="09:00 AM",
                guests=2,
                status="Confirmed",
                amount=200,
                payment_status="paid",
            )
            db.session.add(booking)
            db.session.flush()

            payment = BookingPayment(
                booking_id=booking.id,
                amount=200,
                method="card",
                status="paid",
                reference=f"REF-{uuid4().hex[:8].upper()}",
            )
            ticket = BookingTicket(
                booking_id=booking.id,
                token_hash=uuid4().hex,
                token_payload=uuid4().hex,
                status="issued",
            )
            notification = Notification(
                user_id=admin_user.id,
                booking_id=booking.id,
                notification_type="booking_confirmed",
                message="Test deletion notification",
                dedupe_key=f"test-del:{booking.id}",
            )
            db.session.add_all([payment, ticket, notification])
            db.session.commit()

            with self.client.session_transaction() as sess:
                sess["user_id"] = admin_user.id
                sess["role"] = admin_user.role or "animal_farm_admin"
                sess["zoo_id"] = zoo_id

            # GET should redirect safely
            get_res = self.client.get(f"/animal-farm-admin/bookings/{booking.id}/delete")
            self.assertEqual(get_res.status_code, 302)

            # POST should delete without 500 error
            post_res = self.client.post(f"/animal-farm-admin/bookings/{booking.id}/delete")
            self.assertEqual(post_res.status_code, 302)

            # Ensure booking and child records are gone
            self.assertIsNone(Booking.query.filter_by(id=booking_id).first())
            self.assertEqual(BookingPayment.query.filter_by(booking_id=booking_id).count(), 0)
            self.assertEqual(BookingTicket.query.filter_by(booking_id=booking_id).count(), 0)


if __name__ == "__main__":
    unittest.main()
