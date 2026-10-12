import unittest
from uuid import uuid4

from app import create_app
from models import Booking, BookingPayment, LoyaltyAccount, LoyaltyTransaction, User, Zoo, db
from services.cancellation import cancel_visitor_booking


class CancellationPolicyTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True

    def test_early_cancellation_refunds_points_and_marks_payment_pending(self):
        with self.app.app_context():
            user = User(
                email=f"cancellation-policy-{uuid4().hex}@example.com",
                role="visitor",
                full_name="Policy Test",
            )
            user.set_password("Password123!")
            zoo = Zoo(name="Cancellation Policy Zoo", location="Test")
            db.session.add_all([user, zoo])
            db.session.flush()
            booking_id = f"CP-{uuid4().hex[:10]}"
            booking = Booking(
                id=booking_id,
                zoo_id=zoo.id,
                user_id=user.id,
                visitor_name=user.full_name,
                date="2099-01-01",
                time="09:00 AM",
                guests=1,
                status="Confirmed",
                amount=100,
                payment_status="paid",
            )
            payment = BookingPayment(
                booking_id=booking.id,
                payer_user_id=user.id,
                amount=100,
                method="card",
                status="paid",
                reference=f"CANCEL-POLICY-PAYMENT-{uuid4().hex}",
            )
            account = LoyaltyAccount(user_id=user.id, balance=110)
            db.session.add_all([booking, payment, account])
            db.session.flush()
            db.session.add_all([
                LoyaltyTransaction(
                    account_id=account.id,
                    points=-100,
                    transaction_type="redeem",
                    description="Redeemed",
                    booking_id=booking.id,
                ),
                LoyaltyTransaction(
                    account_id=account.id,
                    points=10,
                    transaction_type="earn",
                    description="Earned",
                    booking_id=booking.id,
                ),
            ])
            db.session.commit()

            eligible = cancel_visitor_booking(booking=booking, user=user)
            db.session.commit()

            self.assertTrue(eligible)
            self.assertEqual(payment.status, "refund pending")
            self.assertEqual(booking.payment_status, "refund pending")
            self.assertEqual(account.balance, 200)
            self.assertEqual(
                LoyaltyTransaction.query.filter_by(
                    booking_id=booking.id, transaction_type="reverse"
                ).count(),
                2,
            )

            LoyaltyTransaction.query.filter_by(booking_id=booking.id).delete(
                synchronize_session=False
            )
            BookingPayment.query.filter_by(booking_id=booking.id).delete(
                synchronize_session=False
            )
            LoyaltyAccount.query.filter_by(user_id=user.id).delete(
                synchronize_session=False
            )
            db.session.delete(booking)
            db.session.delete(zoo)
            db.session.delete(user)
            db.session.commit()


if __name__ == "__main__":
    unittest.main()
