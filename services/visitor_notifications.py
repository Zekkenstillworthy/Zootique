from datetime import date, datetime, timedelta

from models import Booking, Notification, db


ACTIVE_STATUSES = {"confirmed", "pending"}


def _notification_exists(dedupe_key: str) -> bool:
    return db.session.query(Notification.id).filter_by(dedupe_key=dedupe_key).first() is not None


def _ensure_notification(*, user_id: int, booking: Booking, notification_type: str, message: str, dedupe_key: str) -> None:
    if not _notification_exists(dedupe_key):
        db.session.add(Notification(
            user_id=user_id,
            booking_id=booking.id,
            notification_type=notification_type,
            message=message,
            dedupe_key=dedupe_key,
        ))


def ensure_visitor_notifications(user_id: int, bookings: list[Booking]) -> None:
    today = date.today()
    reminder_cutoff = today + timedelta(days=1)

    for booking in bookings:
        status = (booking.status or "").lower()
        if status == "confirmed":
            _ensure_notification(
                user_id=user_id,
                booking=booking,
                notification_type="booking_confirmation",
                message=f"Booking confirmed: {booking.service_name} on {booking.date}.",
                dedupe_key=f"booking-confirmed:{booking.id}",
            )

        try:
            booking_date = datetime.strptime(str(booking.date), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue

        if status == "confirmed" and today <= booking_date <= reminder_cutoff:
            _ensure_notification(
                user_id=user_id,
                booking=booking,
                notification_type="booking_reminder",
                message=f"Upcoming booking: {booking.service_name} on {booking.date}.",
                dedupe_key=f"booking-reminder:{booking.id}:{booking_date.isoformat()}",
            )

        if status not in ACTIVE_STATUSES or not booking.service_id:
            continue

        bookings_on_date = Booking.query.filter(
            Booking.service_id == booking.service_id,
            Booking.date == booking.date,
            db.func.lower(Booking.status).in_(ACTIVE_STATUSES),
        ).count()
        if bookings_on_date >= 50:
            availability_status = "full"
        elif bookings_on_date >= 40:
            availability_status = "limited"
        else:
            continue

        _ensure_notification(
            user_id=user_id,
            booking=booking,
            notification_type="availability",
            message=f"{booking.date} for {booking.service_name} is now {availability_status}.",
            dedupe_key=f"availability:{booking.id}:{booking.date}:{availability_status}",
        )

    db.session.commit()
