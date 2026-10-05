"""Registration email notifications.

If SMTP is not configured, notifications are logged so local approval remains usable.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from flask import current_app


def send_registration_notification(*, recipient: str | None, subject: str, body: str) -> None:
    if not recipient:
        return

    host = os.environ.get("SMTP_HOST", "").strip()
    sender = os.environ.get("SMTP_FROM", "").strip()
    if not host or not sender:
        current_app.logger.info("Registration email not sent (SMTP not configured): %s", subject)
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() not in {"0", "false", "no"}
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


def send_registration_approved(registration) -> None:
    send_registration_notification(
        recipient=registration.admin_email,
        subject="Your Zootique establishment registration was approved",
        body=(
            f"Your registration for {registration.establishment_name} was approved. "
            "Your Zootique administrator account is now ready."
        ),
    )


def send_registration_rejected(registration) -> None:
    note = registration.rejection_note or "No additional note was provided."
    send_registration_notification(
        recipient=registration.admin_email,
        subject="Your Zootique establishment registration needs attention",
        body=(
            f"Your registration for {registration.establishment_name} was rejected.\n\n"
            f"Reviewer note: {note}"
        ),
    )
