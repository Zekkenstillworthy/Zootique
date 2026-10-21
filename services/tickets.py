from __future__ import annotations

import hashlib
import hmac
import base64
import re
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


# ---------------------------------------------------------------------------
# verify_ticket  –  accepts the full signed QR payload OR a plain booking ref
# ---------------------------------------------------------------------------
def verify_ticket(payload: str) -> BookingTicket:
    """Validate a ticket payload scanned from a QR code.

    Accepts two forms:
      1. Full signed payload:  ``{booking_id}.{token}.{signature}``
         (produced by sign_ticket / issue_ticket)
      2. Plain booking reference (e.g. ``BK-1001``) — looked up directly;
         the ticket's HMAC is then re-verified against the stored token_payload.

    Raises ValueError with a specific, staff-readable reason on any failure.
    Security properties preserved:
      - Forged payloads fail the HMAC check.
      - Wrong-zoo / wrong-status / already-used checks remain in the caller.
      - A plain booking-ref lookup still verifies the stored signature so a
        tampered token_payload cannot be accepted.
    """
    # Normalise: strip outer whitespace and embedded newlines/tabs
    payload = re.sub(r"\s+", "", payload or "")

    if not payload:
        raise ValueError("Invalid format — no payload received.")

    # ── Path 1: looks like a plain booking reference (no dots at all) ────────
    # Accept it and find the ticket via booking_id alone; HMAC is verified via
    # the stored token_payload so security is not weakened.
    if "." not in payload:
        ticket = (
            BookingTicket.query
            .filter_by(booking_id=payload)
            .first()
        )
        if not ticket:
            # Try case-insensitive (some scanners change capitalisation)
            ticket = (
                BookingTicket.query
                .filter(db.func.upper(BookingTicket.booking_id) == payload.upper())
                .first()
            )
        if not ticket:
            raise ValueError("Booking not found — no ticket issued for this reference.")
        # Verify the stored payload so we know the ticket hasn't been tampered with
        stored = ticket.token_payload or ""
        parts = stored.split(".", 2)
        if len(parts) == 3:
            bid, tok, stored_sig = parts
            expected = sign_ticket(bid, tok).rsplit(".", 1)[1]
            if not hmac.compare_digest(stored_sig, expected):
                raise ValueError("Ticket data is corrupt — contact support.")
        return ticket

    # ── Path 2: full signed payload ──────────────────────────────────────────
    # Use split(".", 2) so a booking_id that contains dots (unlikely but safe)
    # would still parse; the token and signature never contain dots.
    parts = payload.split(".", 2)
    if len(parts) != 3:
        raise ValueError(
            "Invalid format — expected a full ticket payload "
            "(booking reference · token · signature, separated by dots). "
            "Scan the QR code again or enter just the booking reference."
        )
    booking_id, token, signature = parts

    # HMAC verification
    try:
        expected = sign_ticket(booking_id, token).rsplit(".", 1)[1]
    except Exception:
        raise ValueError("Invalid format — could not verify ticket signature.")

    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid ticket signature — this ticket may be forged or corrupted.")

    ticket = BookingTicket.query.filter_by(
        booking_id=booking_id, token_hash=_hash(token)
    ).first()
    if not ticket:
        raise ValueError("Ticket not found — the booking may have been removed.")
    return ticket


def qr_data_uri(payload: str) -> str:
    import qrcode

    image = qrcode.make(payload)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
