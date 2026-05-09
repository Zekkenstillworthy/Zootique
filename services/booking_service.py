from __future__ import annotations

import secrets
from datetime import datetime

from models import Booking, BookingPayment, User, db


class BookingServiceError(Exception):
    pass


class BookingValidationError(BookingServiceError):
    pass


class BookingAuthorizationError(BookingServiceError):
    pass


SUPPORTED_PAYMENT_METHODS = {"card", "gcash", "cash_on_arrival"}


def _normalize_payment_method(method: str | None) -> str:
    raw = (method or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"credit_card", "debit_card"}:
        raw = "card"
    if raw not in SUPPORTED_PAYMENT_METHODS:
        raise BookingValidationError("Unsupported payment method.")
    return raw


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
    db.session.commit()
    return booking


def process_booking_checkout(*, booking: Booking, payer: User, payment_method: str) -> BookingPayment:
    if not booking:
        raise BookingValidationError("Booking not found.")
    if not payer:
        raise BookingAuthorizationError("A signed-in visitor is required.")
    if payer.role != "visitor":
        raise BookingAuthorizationError("Only visitor accounts can pay for bookings.")

    if booking.user_id and booking.user_id != payer.id:
        raise BookingAuthorizationError("This booking is not owned by the current user.")

    if (booking.status or "").lower() == "cancelled":
        raise BookingValidationError("Cancelled bookings cannot be checked out.")

    if (booking.payment_status or "").lower() == "paid":
        raise BookingValidationError("This booking is already paid.")

    method = _normalize_payment_method(payment_method)

    amount = float(booking.amount or 0)
    if amount < 0:
        raise BookingValidationError("Booking amount is invalid.")

    now = datetime.utcnow()
    reference = _new_payment_reference(booking)

    payment = BookingPayment(
        booking_id=booking.id,
        payer_user_id=payer.id,
        amount=amount,
        method=method,
        status="paid",
        reference=reference,
        provider="simulated_gateway",
        paid_at=now,
    )

    booking.user_id = payer.id
    booking.payment_status = "paid"
    booking.payment_reference = reference
    booking.paid_at = now
    if (booking.status or "").lower() in {"", "pending"}:
        booking.status = "Confirmed"

    db.session.add(payment)
    db.session.commit()
    return payment
