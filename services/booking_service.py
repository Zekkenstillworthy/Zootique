from __future__ import annotations

import secrets
from datetime import date, datetime

from models import Booking, BookingPayment, User, db
from services.payment import PaymentProviderError, get_payment_provider
from services.zoo_settings import get_payment_methods


class BookingServiceError(Exception):
    pass


class BookingValidationError(BookingServiceError):
    pass


class BookingAuthorizationError(BookingServiceError):
    pass


SUPPORTED_PAYMENT_METHODS = {"card", "gcash", "maya", "cash_on_arrival"}


def _time_to_minutes(value: str, default_minutes: int = 540) -> int:
    val = (value or "").strip()
    if not val or val.lower() in {"all-day", "all day", "flexible", "all-day pass"}:
        return default_minutes
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            parsed = datetime.strptime(val.upper(), fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return default_minutes


def reserve_booking_capacity(*, service, booking_date: date, booking_time: str, guests: int) -> None:
    """Lock the service row and validate capacity before a booking is inserted."""
    if not service:
        raise BookingValidationError("Selected service was not found.")
    if guests < 1:
        raise BookingValidationError("Guests must be at least one.")
    opening = (service.opening_time or "08:00").strip()
    closing = (service.closing_time or "17:00").strip()
    opening_minutes = _time_to_minutes(opening, 480)
    closing_minutes = _time_to_minutes(closing, 1020)
    selected_minutes = _time_to_minutes(booking_time, opening_minutes)
    if selected_minutes < opening_minutes or selected_minutes > closing_minutes:
        raise BookingValidationError("Selected time is outside the service operating hours.")

    locked_service = db.session.query(type(service)).filter_by(id=service.id).with_for_update().first()
    if not locked_service:
        raise BookingValidationError("Selected service is no longer available.")

    active_statuses = {"confirmed", "pending"}
    bookings = Booking.query.filter(
        Booking.service_id == service.id,
        Booking.date == booking_date.isoformat(),
        db.func.lower(Booking.status).in_(active_statuses),
    ).all()
    daily_booked = sum(int(booking.guests or 0) for booking in bookings)
    daily_capacity = int(locked_service.daily_capacity or 0)
    if daily_capacity and daily_booked + guests > daily_capacity:
        raise BookingValidationError("Daily visitor limit reached for this date. There is not enough remaining capacity.")


def _normalize_payment_method(method: str | None) -> str:
    raw = (method or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"credit_card", "debit_card"}:
        raw = "card"
    elif raw == "cash":
        raw = "cash_on_arrival"
    if raw not in SUPPORTED_PAYMENT_METHODS:
        raise BookingValidationError("Unsupported payment method.")
    return raw


def validate_booking_details(*, date_value: str, time_value: str, guests: int) -> None:
    try:
        visit_date = date.fromisoformat((date_value or "").strip())
    except ValueError as exc:
        raise BookingValidationError("Booking date must use YYYY-MM-DD format.") from exc

    if visit_date < date.today():
        raise BookingValidationError("Booking date cannot be in the past.")
    # Arrival time defaults to opening time if not provided
    if not (time_value or "").strip():
        time_value = "09:00 AM"
    if guests < 1 or guests > 50:
        raise BookingValidationError("Guests must be between 1 and 50.")


def _new_payment_reference(booking: Booking) -> str:
    return f"BKP-{booking.id}-{secrets.token_hex(4).upper()}"


def assign_booking_to_staff(*, booking: Booking, staff_user: User, zoo_id: int | None):
    if not booking:
        raise BookingValidationError("Booking is required.")
    if not staff_user:
        raise BookingValidationError("Staff user is required.")
    if staff_user.role != "zoo_staff":
        raise BookingValidationError("Assigned user must be zoo staff.")
    if zoo_id and staff_user.zoo_id != zoo_id:
        raise BookingValidationError("Staff member does not belong to this establishment.")

    booking.assigned_staff_user_id = staff_user.id
    from models import Notification
    dedupe_key = f"staff-booking-assigned:{booking.id}:{staff_user.id}"
    if not Notification.query.filter_by(dedupe_key=dedupe_key).first():
        db.session.add(Notification(
            user_id=staff_user.id,
            booking_id=booking.id,
            notification_type="staff_new_booking",
            message=f"New booking {booking.id} was assigned to you.",
            dedupe_key=dedupe_key,
        ))
    db.session.commit()
    return booking


def process_booking_checkout(*, booking: Booking, payer: User, payment_method: str) -> BookingPayment:
    if not booking:
        raise BookingValidationError("Booking not found.")
    if not payer:
        raise BookingAuthorizationError("A signed-in visitor is required.")
    if payer.role != "visitor":
        raise BookingAuthorizationError("Only visitor accounts can pay for bookings.")

    # Serialize checkout attempts for this booking so two browser submissions
    # cannot both pass the unpaid check before either payment is recorded.
    locked_booking = (
        Booking.query.filter_by(id=booking.id)
        .with_for_update()
        .first()
    )
    if not locked_booking:
        raise BookingValidationError("Booking not found.")
    booking = locked_booking

    if booking.user_id and booking.user_id != payer.id:
        raise BookingAuthorizationError("This booking is not owned by the current user.")

    method = _normalize_payment_method(payment_method)
    if booking.zoo_id and method not in get_payment_methods(booking.zoo_id):
        raise BookingValidationError("This payment method is not enabled for the selected zoo.")

    amount = float(booking.amount or 0)
    if amount < 0:
        raise BookingValidationError("Booking amount is invalid.")

    idempotency_key = f"booking:{booking.id}:payment:{method}"
    existing_payment = BookingPayment.query.filter_by(idempotency_key=idempotency_key).first()
    if existing_payment:
        if existing_payment.status == "paid":
            return existing_payment
        raise BookingValidationError("A previous payment attempt must be resolved before retrying.")

    if (booking.status or "").lower() == "cancelled":
        raise BookingValidationError("Cancelled bookings cannot be checked out.")

    if (booking.payment_status or "").lower() == "paid":
        raise BookingValidationError("This booking is already paid.")

    try:
        provider_result = get_payment_provider().authorize(
            amount=amount,
            method=method,
            idempotency_key=idempotency_key,
        )
    except PaymentProviderError as exc:
        raise BookingValidationError(str(exc)) from exc
    now = datetime.utcnow()
    reference = _new_payment_reference(booking)

    payment = BookingPayment(
        booking_id=booking.id,
        payer_user_id=payer.id,
        amount=amount,
        method=method,
        status=provider_result.status,
        reference=reference,
        provider=provider_result.provider,
        paid_at=now,
        provider_reference=provider_result.provider_reference,
        idempotency_key=idempotency_key,
    )

    booking.user_id = payer.id
    booking.payment_status = provider_result.status
    booking.payment_reference = reference
    booking.paid_at = now
    if (booking.status or "").lower() in {"", "pending"}:
        booking.status = "Confirmed"

    db.session.add(payment)
    db.session.commit()
    return payment
