import unittest

from app import create_app
from models import Booking, EstablishmentRegistration, Event, Service, SystemSetting, User, Zoo, db
from services.booking_reporting import report_bookings, report_period
from services.booking_service import BookingValidationError, process_booking_checkout
from services.service_catalog import PROMOTION_CATEGORY_VALUES, SERVICE_CATEGORY_VALUES
from services.zoo_settings import get_availability_settings, get_payment_methods, save_zoo_setting
from uuid import uuid4


class RemainingFeatureTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_animal_farm_admin_can_edit_event(self):
        with self.app.app_context():
            admin = User.query.filter(
                User.role == "zoo_admin",
                User.zoo_id.isnot(None),
                User.status == "active",
            ).first()
            if not admin:
                self.skipTest("No active Zoo Admin account found.")

            event = Event.query.filter_by(zoo_id=admin.zoo_id).first()
            if not event:
                event = Event(
                    zoo_id=admin.zoo_id,
                    name=f"Edit Event {uuid4().hex[:8]}",
                    type="Tour",
                    time="2026-11-11 10:00 AM",
                    location="Original Location",
                )
                db.session.add(event)
                db.session.commit()
            event_id = event.id

            with self.client.session_transaction() as session:
                session["user_id"] = admin.id
                session["role"] = "zoo_admin"
                session["zoo_id"] = admin.zoo_id

            response = self.client.get(
                "/animal-farm-admin/events",
                query_string={"tab": "add", "edit": event_id},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("Edit Event", response.get_data(as_text=True))

            list_response = self.client.get(
                "/animal-farm-admin/events",
                query_string={"tab": "list"},
            )
            self.assertEqual(list_response.status_code, 200)
            self.assertIn(
                f"/animal-farm-admin/events?tab=add&amp;edit={event_id}",
                list_response.get_data(as_text=True),
            )

            response = self.client.post(
                "/animal-farm-admin/events/save",
                data={
                    "event_id": event_id,
                    "name": "Updated Event Name",
                    "type": "Feeding",
                    "time": "2026-11-12 02:00 PM - 03:00 PM",
                    "location": "Updated Location",
                },
            )
            self.assertEqual(response.status_code, 302)
            db.session.expire_all()
            updated = db.session.get(Event, event_id)
            self.assertEqual(updated.name, "Updated Event Name")
            self.assertEqual(updated.type, "Feeding")
            self.assertEqual(updated.location, "Updated Location")

    def test_service_and_promotion_categories_are_limited_to_requested_values(self):
        with self.app.app_context():
            admin = User.query.filter(
                User.role == "zoo_admin",
                User.zoo_id.isnot(None),
                User.status == "active",
            ).first()
            if not admin:
                self.skipTest("No active Zoo Admin account found.")

            with self.client.session_transaction() as session:
                session["user_id"] = admin.id
                session["role"] = "zoo_admin"
                session["zoo_id"] = admin.zoo_id

            expected_services = (
                "Family Tour",
                "Group Tour",
                "Tour",
                "Senior Citizen",
                "Vip Experience",
            )
            expected_promotions = (
                "Family Tour",
                "Group Tour",
                "Tour",
                "Senior Citizen",
                "Vip Experience",
                "Valid For All",
            )
            self.assertEqual(SERVICE_CATEGORY_VALUES, expected_services)
            self.assertEqual(PROMOTION_CATEGORY_VALUES, expected_promotions)

            service_response = self.client.get(
                "/animal-farm-admin/services",
                query_string={"tab": "add"},
            )
            promotion_response = self.client.get(
                "/animal-farm-admin/promotions",
                query_string={"tab": "add"},
            )
            self.assertEqual(service_response.status_code, 200)
            self.assertEqual(promotion_response.status_code, 200)
            service_body = service_response.get_data(as_text=True)
            promotion_body = promotion_response.get_data(as_text=True)
            for category in expected_services:
                self.assertIn(f'value="{category}"', service_body)
            for category in expected_promotions:
                self.assertIn(f'value="{category}"', promotion_body)
            for legacy in ("Feeding", "Photography", "Education", "Workshop", "Other"):
                self.assertNotIn(f'value="{legacy}"', service_body)
                self.assertNotIn(f'value="{legacy}"', promotion_body)

    def test_analytics_range_statuses_and_csv_are_scoped_to_zoo(self):
        with self.app.app_context():
            admin = User.query.filter(
                User.role == "zoo_admin",
                User.zoo_id.isnot(None),
                User.status == "active",
            ).first()
            other_zoo = Zoo.query.filter(Zoo.id != admin.zoo_id).first() if admin else None
            if not admin or not other_zoo:
                self.skipTest("Need two zoo facilities with an active Zoo Admin.")

            suffix = uuid4().hex[:8]
            bookings = [
                Booking(
                    id=f"AN-{suffix}-{index}",
                    zoo_id=admin.zoo_id,
                    visitor_name=f"Analytics Visitor {index}",
                    service_name="Analytics Service",
                    date="2099-06-15",
                    guests=2,
                    amount=100,
                    status=status,
                    payment_status="paid" if status == "Paid" else "unpaid",
                )
                for index, status in enumerate(
                    ("Pending", "Paid", "Finished", "Cancelled")
                )
            ]
            other_booking = Booking(
                id=f"AO-{suffix}",
                zoo_id=other_zoo.id,
                visitor_name="Other Zoo Visitor",
                service_name="Other Service",
                date="2099-06-15",
                guests=9,
                amount=999,
                status="Paid",
                payment_status="paid",
            )
            db.session.add_all(bookings + [other_booking])
            db.session.commit()

            try:
                with self.client.session_transaction() as session:
                    session["user_id"] = admin.id
                    session["role"] = "zoo_admin"
                    session["zoo_id"] = admin.zoo_id

                response = self.client.get(
                    "/animal-farm-admin/analytics",
                    query_string={"range": "all_time"},
                )
                self.assertEqual(response.status_code, 200)
                body = response.get_data(as_text=True)
                self.assertIn("Cancelled Bookings", body)
                self.assertNotIn("No bookings in this range", body)
                self.assertNotIn("Other Zoo Visitor", body)

                csv_response = self.client.get(
                    "/animal-farm-admin/analytics/export",
                    query_string={"range": "all_time"},
                )
                self.assertEqual(csv_response.status_code, 200)
                csv_body = csv_response.get_data(as_text=True)
                self.assertIn("booking date,visitor,service,guests,amount,status", csv_body)
                self.assertIn("Analytics Visitor", csv_body)
                self.assertNotIn("Other Zoo Visitor", csv_body)
            finally:
                db.session.delete(other_booking)
                for booking in bookings:
                    db.session.delete(booking)
                db.session.commit()

    def test_analytics_date_ranges_use_inclusive_schedule_dates(self):
        from datetime import date

        self.assertEqual(
            report_period("today", date(2026, 11, 9)),
            (date(2026, 11, 9), date(2026, 11, 9)),
        )
        self.assertEqual(
            report_period("last_7_days", date(2026, 11, 9)),
            (date(2026, 11, 3), date(2026, 11, 9)),
        )
        self.assertEqual(
            report_period("this_month", date(2026, 11, 9)),
            (date(2026, 11, 1), date(2026, 11, 9)),
        )
        self.assertEqual(
            report_period("last_month", date(2026, 11, 9)),
            (date(2026, 10, 1), date(2026, 10, 31)),
        )
        self.assertEqual(report_period("all_time", date(2026, 11, 9)), (None, None))

    def test_landing_slider_links_to_each_zoo(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            assigned_zoo_id = (
                User.query.filter(
                    User.role == "zoo_admin",
                    User.zoo_id.isnot(None),
                )
                .with_entities(User.zoo_id)
                .order_by(User.zoo_id.asc())
                .first()
            )
            zoo = db.session.get(Zoo, assigned_zoo_id[0]) if assigned_zoo_id else None
            if zoo:
                self.assertIn(f"/visitor/zoos/{zoo.id}", response.get_data(as_text=True))

    def test_landing_carousel_excludes_unassigned_facilities(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            assigned_facility_ids = {
                zoo_id
                for (zoo_id,) in User.query.filter(
                    User.role == "zoo_admin",
                    User.zoo_id.isnot(None),
                )
                .with_entities(User.zoo_id)
                .distinct()
                .all()
            }
            unassigned_zoos = Zoo.query.filter(
                ~Zoo.id.in_(assigned_facility_ids)
                if assigned_facility_ids
                else db.text("TRUE")
            ).all()
            body = response.get_data(as_text=True)
            for zoo in unassigned_zoos:
                self.assertNotIn(f"/visitor/zoos/{zoo.id}", body)

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

    def test_super_admin_delete_removes_assigned_facility_and_approved_registration(self):
        with self.app.app_context():
            super_admin = User.query.filter_by(role="zootique_admin", status="active").first()
            if not super_admin:
                self.skipTest("No active Super Admin account found.")

            suffix = uuid4().hex[:8]
            zoo = Zoo(name=f"Delete Cascade Zoo {suffix}", type="Zoo Park", location="Test")
            db.session.add(zoo)
            db.session.flush()
            administrator = User(
                email=f"delete-cascade-{suffix}@example.com",
                full_name="Delete Cascade Admin",
                role="zoo_admin",
                zoo_id=zoo.id,
                status="active",
            )
            administrator.set_password("Password123!")
            registration = EstablishmentRegistration(
                establishment_name=zoo.name,
                establishment_type=zoo.type,
                location=zoo.location,
                admin_email=administrator.email,
                status="approved",
                zoo_id=zoo.id,
            )
            historical_registration = EstablishmentRegistration(
                establishment_name=f"{zoo.name} Historical",
                establishment_type=zoo.type,
                location=zoo.location,
                admin_email=administrator.email,
                status="approved",
            )
            carousel_setting = SystemSetting(
                key=f"landing_carousel:{zoo.id}",
                value="1",
            )
            db.session.add_all([
                administrator,
                registration,
                historical_registration,
                carousel_setting,
            ])
            db.session.commit()
            administrator_id = administrator.id
            zoo_id = zoo.id
            registration_id = registration.id
            historical_registration_id = historical_registration.id

            with self.client.session_transaction() as session:
                session["user_id"] = super_admin.id
                session["role"] = "zootique_admin"
                session["_csrf_token"] = "test-csrf"

            response = self.client.post(
                f"/zootique-admin/user-management/users/{administrator_id}/delete",
                data={"csrf_token": "test-csrf"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertIsNone(db.session.get(User, administrator_id))
            self.assertIsNone(db.session.get(Zoo, zoo_id))
            self.assertIsNone(db.session.get(EstablishmentRegistration, registration_id))
            self.assertIsNone(db.session.get(EstablishmentRegistration, historical_registration_id))
            self.assertIsNone(
                SystemSetting.query.filter_by(key=f"landing_carousel:{zoo_id}").first()
            )

    def test_super_admin_can_delete_establishment_registration(self):
        with self.app.app_context():
            from models import SystemSetting

            super_admin = User.query.filter_by(role="zootique_admin", status="active").first()
            if not super_admin:
                self.skipTest("No active Super Admin account found.")

            suffix = uuid4().hex[:8]
            registration = EstablishmentRegistration(
                establishment_name=f"Delete Registration {suffix}",
                establishment_type="Zoo Park",
                location="Test",
                status="pending",
            )
            db.session.add(registration)
            db.session.commit()
            registration_id = registration.id

            with self.client.session_transaction() as session:
                session["user_id"] = super_admin.id
                session["role"] = "zootique_admin"
                session["_csrf_token"] = "test-csrf"

            response = self.client.post(
                f"/zootique-admin/registrations/{registration_id}/delete",
                data={"csrf_token": "test-csrf"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertIsNone(db.session.get(EstablishmentRegistration, registration_id))

            SystemSetting.query.filter_by(key=f"landing_carousel:{registration_id}").delete()
            db.session.commit()

    def test_approved_registration_view_matches_linked_facilities(self):
        with self.app.app_context():
            super_admin = User.query.filter_by(role="zootique_admin", status="active").first()
            if not super_admin:
                self.skipTest("No active Super Admin account found.")

            with self.client.session_transaction() as session:
                session["user_id"] = super_admin.id
                session["role"] = "zootique_admin"

            response = self.client.get("/zootique-admin/registrations?status=approved")
            self.assertEqual(response.status_code, 200)
            body = response.get_data(as_text=True)
            assigned_facility_ids = {
                zoo_id
                for (zoo_id,) in User.query.filter(
                    User.role == "zoo_admin",
                    User.zoo_id.isnot(None),
                )
                .with_entities(User.zoo_id)
                .distinct()
                .all()
            }
            approved_linked = EstablishmentRegistration.query.filter(
                EstablishmentRegistration.zoo_id.in_(assigned_facility_ids)
                if assigned_facility_ids
                else db.text("FALSE"),
                EstablishmentRegistration.status.in_(("approved", "approved_legacy")),
            ).count()
            self.assertEqual(body.count('class="fw-600"'), approved_linked)

    def test_administrator_roster_counts_only_assigned_facilities(self):
        with self.app.app_context():
            super_admin = User.query.filter_by(role="zootique_admin", status="active").first()
            if not super_admin:
                self.skipTest("No active Super Admin account found.")

            with self.client.session_transaction() as session:
                session["user_id"] = super_admin.id
                session["role"] = "zootique_admin"

            response = self.client.get("/zootique-admin/user-management")
            self.assertEqual(response.status_code, 200)
            body = response.get_data(as_text=True)
            assigned_facility_count = User.query.filter(
                User.role == "zoo_admin",
                User.zoo_id.isnot(None),
            ).with_entities(User.zoo_id).distinct().count()
            self.assertIn(
                f"<span class=\"value\">{assigned_facility_count}</span>",
                body,
            )

    def test_dashboard_total_registered_zoos_matches_assigned_facilities(self):
        with self.app.app_context():
            super_admin = User.query.filter_by(role="zootique_admin", status="active").first()
            if not super_admin:
                self.skipTest("No active Super Admin account found.")

            with self.client.session_transaction() as session:
                session["user_id"] = super_admin.id
                session["role"] = "zootique_admin"

            response = self.client.get("/zootique-admin/")
            self.assertEqual(response.status_code, 200)
            assigned_facility_count = User.query.filter(
                User.role == "zoo_admin",
                User.zoo_id.isnot(None),
            ).with_entities(User.zoo_id).distinct().count()
            self.assertIn(
                f"TOTAL REGISTERED ZOOS</div>\n"
                f"        <div class=\"sa-kpi-row\">\n"
                f"            <div class=\"stat-value\">{assigned_facility_count}</div>",
                response.get_data(as_text=True),
            )

    def test_zoo_staff_booking_full_authority(self):
        with self.app.app_context():
            from uuid import uuid4

            zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            if not zoo:
                self.skipTest("No zoo found.")

            staff_user = User.query.filter_by(zoo_id=zoo.id, role="zoo_staff").first()
            if not staff_user:
                staff_user = User(
                    email=f"staff-{uuid4().hex[:6]}@example.com",
                    full_name="Staff Tester",
                    role="zoo_staff",
                    status="active",
                    zoo_id=zoo.id,
                )
                staff_user.set_password("Password123!")
                db.session.add(staff_user)
                db.session.commit()

            with self.client.session_transaction() as sess:
                sess["user_id"] = staff_user.id
                sess["role"] = "zoo_staff"
                sess["zoo_id"] = zoo.id

            # 1. Staff can view bookings page with Add Booking button & modal
            res = self.client.get("/animal-farm-staff/bookings")
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)
            self.assertIn("Add Booking", html)
            self.assertIn("booking-modal-overlay", html)

            # 2. Staff can create a new booking
            create_res = self.client.post(
                "/animal-farm-staff/bookings/create",
                data={
                    "visitor_name": "VIP Visitor",
                    "date": "2099-05-10",
                    "time": "10:00 AM",
                    "guests": "3",
                    "amount": "150.00",
                    "status": "Pending",
                },
                follow_redirects=True,
            )
            self.assertEqual(create_res.status_code, 200)
            created_booking = Booking.query.filter_by(
                zoo_id=zoo.id, visitor_name="VIP Visitor", date="2099-05-10"
            ).first()
            self.assertIsNotNone(created_booking)
            self.assertEqual(created_booking.guests, 3)

            # 3. Staff can update the booking
            update_res = self.client.post(
                f"/animal-farm-staff/bookings/{created_booking.id}/update",
                data={
                    "visitor_name": "VIP Visitor Updated",
                    "date": "2099-05-11",
                    "time": "11:00 AM",
                    "guests": "4",
                    "amount": "200.00",
                    "status": "Confirmed",
                },
                follow_redirects=True,
            )
            self.assertEqual(update_res.status_code, 200)
            db.session.refresh(created_booking)
            self.assertEqual(created_booking.visitor_name, "VIP Visitor Updated")
            self.assertEqual(created_booking.date, "2099-05-11")
            self.assertEqual(created_booking.guests, 4)
            self.assertEqual(created_booking.status, "Confirmed")

            # 4. Staff can quick confirm / cancel status
            status_res = self.client.post(
                f"/animal-farm-staff/bookings/{created_booking.id}/status",
                data={"status": "Cancelled"},
                follow_redirects=True,
            )
            self.assertEqual(status_res.status_code, 200)
            db.session.refresh(created_booking)
            self.assertEqual(created_booking.status, "Cancelled")

            # 5. Staff can delete the booking permanently
            del_res = self.client.post(
                f"/animal-farm-staff/bookings/{created_booking.id}/delete",
                follow_redirects=True,
            )
            self.assertEqual(del_res.status_code, 200)
            self.assertIsNone(Booking.query.filter_by(id=created_booking.id).first())


if __name__ == "__main__":
    unittest.main()
