from __future__ import annotations

import hashlib
import hmac
import base64
from io import BytesIO
import secrets

from flask import current_app

from models import Booking, BookingTicket, db


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_ticket(booking: Booking) -> tuple[BookingTicket, str]:
    ticket = BookingTicket.query.filter_by(booking_id=booking.id).first()
    if ticket:
        raise ValueError("A ticket has already been issued for this booking.")
    token = secrets.token_urlsafe(32)
    payload = sign_ticket(booking.id, token)
    ticket = BookingTicket(booking_id=booking.id, token_hash=_hash(token), token_payload=payload)
    db.session.add(ticket)
    db.session.flush()
    return ticket, payload


def sign_ticket(booking_id: str, token: str) -> str:
    secret = str(current_app.config["SECRET_KEY"]).encode("utf-8")
    payload = f"{booking_id}.{token}".encode("utf-8")
    signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return f"{booking_id}.{token}.{signature}"


def verify_ticket(payload: str) -> BookingTicket:
    parts = (payload or "").split(".")
    if len(parts) != 3:
        raise ValueError("Invalid ticket payload.")
    booking_id, token, signature = parts
    expected = sign_ticket(booking_id, token).rsplit(".", 1)[1]
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid ticket signature.")
    ticket = BookingTicket.query.filter_by(booking_id=booking_id, token_hash=_hash(token)).first()
    if not ticket:
        raise ValueError("Ticket not found.")
    return ticket


def qr_data_uri(payload: str) -> str:
    import qrcode

    image = qrcode.make(payload)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
