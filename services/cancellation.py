from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from models import Booking, BookingPayment, LoyaltyTransaction, Notification, User, db
from services.loyalty import record_transaction


def cancel_visitor_booking(*, booking: Booking, user: User) -> bool:
    if (booking.status or "").lower() == "cancelled":
        return False

    slot_datetime = _slot_datetime(booking)
    refund_hours = int(getattr(booking.zoo, "cancellation_refund_hours", 24) or 24)
    eligible_for_refund = slot_datetime is not None and (
        slot_datetime - datetime.now(ZoneInfo("Asia/Manila"))
    ).total_seconds() >= refund_hours * 3600

    booking.status = "Cancelled"
    payment = (
        BookingPayment.query.filter_by(booking_id=booking.id)
        .order_by(BookingPayment.created_at.desc())
        .first()
    )
    if payment and (payment.status or "").lower() in {"paid", "pending"}:
        payment.status = "refund pending" if eligible_for_refund else "cancelled"
    booking.payment_status = (
        "refund pending" if eligible_for_refund else (booking.payment_status or "unpaid")
    )

    previous = LoyaltyTransaction.query.filter_by(booking_id=booking.id).all()
    if not any(tx.transaction_type == "reverse" for tx in previous):
        for transaction in previous:
            if transaction.transaction_type == "redeem" and eligible_for_refund:
                record_transaction(
                    user=user,
                    points=abs(int(transaction.points)),
                    transaction_type="reverse",
                    description=f"Redeemed points returned for cancelled booking {booking.id}",
                    booking_id=booking.id,
                )
            elif transaction.transaction_type == "earn" and transaction.points > 0:
                record_transaction(
                    user=user,
                    points=-int(transaction.points),
                    transaction_type="reverse",
                    description=f"Earned points reversed for cancelled booking {booking.id}",
                    booking_id=booking.id,
                )

    dedupe_key = f"booking-cancelled:{booking.id}"
    if not Notification.query.filter_by(dedupe_key=dedupe_key).first():
        db.session.add(Notification(
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_cancelled",
            message=(
                "Booking cancelled. Refund pending."
                if eligible_for_refund
                else "Booking cancelled. The cancellation was inside the refund window."
            ),
            dedupe_key=dedupe_key,
        ))

    try:
        from services.zoo_notifications import notify_zoo_team
        notify_zoo_team(
            zoo_id=booking.zoo_id,
            notification_type="booking_cancelled",
            message=f"Booking #{booking.id} ({booking.visitor_name} - {booking.service_name} on {booking.date}) was cancelled by the visitor.",
            booking_id=booking.id,
            dedupe_prefix=f"zoo-booking-cancelled:{booking.id}",
            commit=False,
        )
    except Exception:
        pass

    return eligible_for_refund


def _slot_datetime(booking: Booking) -> datetime | None:
    if not booking.date or not booking.time:
        return None
    for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{booking.date} {booking.time}", fmt).replace(
                tzinfo=ZoneInfo("Asia/Manila")
            )
        except ValueError:
            continue
    return None
