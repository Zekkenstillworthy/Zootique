import unittest

from app import create_app
from models import Animal, User, Zoo, db


class StaffPermissionsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            # Get or create a test zoo
            zoo = Zoo.query.order_by(Zoo.id.asc()).first()
            if not zoo:
                zoo = Zoo(name="Staff Test Zoo", type="Safari Park", location="Test Land")
                db.session.add(zoo)
                db.session.commit()
            self.zoo_id = zoo.id

            # Get or create an animal for this zoo
            animal = Animal.query.filter_by(zoo_id=self.zoo_id).first()
            if not animal:
                animal = Animal(zoo_id=self.zoo_id, name="Test Lion", species="Panthera leo")
                db.session.add(animal)
                db.session.commit()
            self.animal_id = animal.id

            # Create or update staff user
            staff_user = User.query.filter_by(email="test_zoo_staff@example.com").first()
            if not staff_user:
                staff_user = User(
                    email="test_zoo_staff@example.com",
                    role="zoo_staff",
                    full_name="Staff Tester",
                    zoo_id=self.zoo_id,
                    status="active",
                )
                staff_user.set_password("Password123")
                db.session.add(staff_user)
            else:
                staff_user.role = "zoo_staff"
                staff_user.zoo_id = self.zoo_id
                staff_user.status = "active"
            db.session.commit()
            self.staff_id = staff_user.id

            # Create or update admin user
            admin_user = User.query.filter_by(email="test_zoo_admin@example.com").first()
            if not admin_user:
                admin_user = User(
                    email="test_zoo_admin@example.com",
                    role="zoo_admin",
                    full_name="Admin Tester",
                    zoo_id=self.zoo_id,
                    status="active",
                )
                admin_user.set_password("Password123")
                db.session.add(admin_user)
            else:
                admin_user.role = "zoo_admin"
                admin_user.zoo_id = self.zoo_id
                admin_user.status = "active"
            db.session.commit()
            self.admin_id = admin_user.id

    def _login_as(self, role: str, user_id: int, full_name: str):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["role"] = role
            sess["full_name"] = full_name
            sess["auth_by_role"] = {
                role: {
                    "user_id": user_id,
                    "full_name": full_name,
                }
            }

    def test_zoo_staff_can_access_animals_management_and_edit_page(self):
        self._login_as("zoo_staff", self.staff_id, "Staff Tester")

        response = self.client.get(
            f"/animal-farm-admin/animals?tab=add&edit_id={self.animal_id}",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Animals", response.data)

    def test_zoo_staff_can_access_bookings(self):
        self._login_as("zoo_staff", self.staff_id, "Staff Tester")

        response = self.client.get("/animal-farm-admin/bookings", follow_redirects=False)
        self.assertEqual(response.status_code, 200)

    def test_zoo_staff_can_access_map_zones(self):
        self._login_as("zoo_staff", self.staff_id, "Staff Tester")

        response = self.client.get("/animal-farm-admin/map-zones", follow_redirects=False)
        self.assertEqual(response.status_code, 200)

    def test_zoo_staff_can_access_park_management_pages(self):
        self._login_as("zoo_staff", self.staff_id, "Staff Tester")

        for endpoint in [
            "/animal-farm-admin/services",
            "/animal-farm-admin/events",
            "/animal-farm-admin/promotions",
            "/animal-farm-admin/park-rules",
            "/animal-farm-admin/availability-settings",
            "/animal-farm-admin/payment-methods",
        ]:
            with self.subTest(endpoint=endpoint):
                res = self.client.get(endpoint, follow_redirects=False)
                self.assertEqual(res.status_code, 200)

    def test_zoo_staff_is_restricted_from_owner_only_pages(self):
        self._login_as("zoo_staff", self.staff_id, "Staff Tester")

        owner_endpoints = [
            "/animal-farm-admin/subscriptions",
            "/animal-farm-admin/staff-management",
            "/animal-farm-admin/profile",
        ]
        for endpoint in owner_endpoints:
            with self.subTest(endpoint=endpoint):
                res = self.client.get(endpoint, follow_redirects=False)
                # Restricted: redirects to dashboard
                self.assertEqual(res.status_code, 302)
                self.assertIn("/animal-farm-admin/", res.location)

    def test_zoo_admin_can_access_owner_pages(self):
        self._login_as("zoo_admin", self.admin_id, "Admin Tester")

        for endpoint in [
            "/animal-farm-admin/subscriptions",
            "/animal-farm-admin/staff-management",
            "/animal-farm-admin/profile",
        ]:
            with self.subTest(endpoint=endpoint):
                res = self.client.get(endpoint, follow_redirects=False)
                self.assertEqual(res.status_code, 200)
