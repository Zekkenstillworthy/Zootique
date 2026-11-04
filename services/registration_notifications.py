"""Registration email notifications.

Sends via Resend (HTTP API — works on Vercel and other serverless platforms).
Falls back to SMTP if RESEND_API_KEY is not set, so local dev with an SMTP
relay continues to work without any extra configuration.

Priority:
  1. Resend  — set RESEND_API_KEY and RESEND_FROM (or SMTP_FROM / MAIL_DEFAULT_SENDER).
  2. SMTP    — set SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD as before.
If neither is configured, the attempt is logged and the function returns False.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from flask import current_app
from models import RegistrationEmailAttempt, db


def _sender_address() -> str:
    """Return the best available 'From' address from environment variables."""
    return (
        os.environ.get("RESEND_FROM")
        or os.environ.get("SMTP_FROM")
        or os.environ.get("MAIL_DEFAULT_SENDER")
        or os.environ.get("SMTP_USERNAME")
        or os.environ.get("MAIL_USERNAME")
        or ""
    ).strip()


def _send_via_resend(*, recipient: str, subject: str, body: str, sender: str) -> bool:
    """Send an email using the Resend HTTP API. Returns True on success."""
    try:
        import resend  # type: ignore[import]
    except ImportError:
        current_app.logger.warning("resend package is not installed; cannot send via Resend.")
        return False

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        return False  # caller will fall back to SMTP

    resend.api_key = api_key
    try:
        params: resend.Emails.SendParams = {
            "from": sender,
            "to": [recipient],
            "subject": subject,
            "text": body,
        }
        resend.Emails.send(params)
        return True
    except Exception as exc:
        current_app.logger.warning("Resend failed for %s: %s", recipient, exc)
        raise  # re-raise so the caller can record the error


def _send_via_smtp(*, recipient: str, subject: str, body: str, sender: str) -> bool:
    """Send an email via SMTP. Returns True on success."""
    username = (
        os.environ.get("SMTP_USERNAME")
        or os.environ.get("MAIL_USERNAME")
        or ""
    ).strip()
    password = (
        os.environ.get("SMTP_PASSWORD")
        or os.environ.get("MAIL_PASSWORD")
        or ""
    ).strip()
    host = (
        os.environ.get("SMTP_HOST")
        or os.environ.get("MAIL_SERVER")
        or ("smtp.gmail.com" if (username or password) else "")
    ).strip()

    if not host or not sender:
        return False  # not configured

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    port = int(os.environ.get("SMTP_PORT") or os.environ.get("MAIL_PORT") or "587")
    use_tls = (os.environ.get("SMTP_USE_TLS") or os.environ.get("MAIL_USE_TLS") or "true").lower() not in {"0", "false", "no"}
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)
    return True


def send_registration_notification(*, recipient: str | None, subject: str, body: str, registration=None, notification_type: str = "registration") -> bool:
    if not recipient:
        return False

    attempt = None
    if registration is not None:
        attempt = RegistrationEmailAttempt(
            registration_id=registration.id,
            recipient=recipient,
            subject=subject,
            body=body,
            notification_type=notification_type,
            status="pending",
        )
        db.session.add(attempt)

    sender = _sender_address()

    # --- Try Resend first (works on Vercel / serverless) ---
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if resend_key:
        try:
            sent = _send_via_resend(recipient=recipient, subject=subject, body=body, sender=sender)
            if sent:
                if attempt:
                    attempt.status = "sent"
                return True
        except Exception as exc:
            if attempt:
                attempt.status = "failed"
                attempt.error_message = f"[Resend] {exc}"[:500]
            return False

    # --- Fall back to SMTP (local dev / self-hosted) ---
    if not sender:
        current_app.logger.info(
            "Registration email not sent (neither RESEND_API_KEY nor SMTP/MAIL configured): %s", subject
        )
        if attempt:
            attempt.status = "failed"
            attempt.error_message = "No email provider configured (set RESEND_API_KEY or SMTP credentials)."
        return False

    try:
        _send_via_smtp(recipient=recipient, subject=subject, body=body, sender=sender)
        if attempt:
            attempt.status = "sent"
        return True
    except Exception as exc:
        current_app.logger.warning("SMTP failed for %s: %s", recipient, exc)
        if attempt:
            attempt.status = "failed"
            attempt.error_message = f"[SMTP] {str(exc)}"[:500]
        return False


def send_registration_approved(registration, activation_token: str | None = None) -> bool:
    activation_url = ""
    if activation_token:
        base_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/") or "http://127.0.0.1:5000"
        activation_url = f"\n\nActivate the administrator account here:\n{base_url}/auth/activate-zoo-admin?registration_id={registration.id}&token={activation_token}"
    return send_registration_notification(
        recipient=registration.admin_email,
        subject="Your Zootique establishment registration was approved",
        body=(
            f"Your registration for {registration.establishment_name} was approved. "
            "Your Zootique administrator account is ready to activate."
            f"{activation_url}"
        ),
        registration=registration,
        notification_type="applicant_approved",
    )


def send_registration_rejected(registration) -> bool:
    note = registration.rejection_note or "No additional note was provided."
    return send_registration_notification(
        recipient=registration.admin_email,
        subject="Your Zootique establishment registration needs attention",
        body=(
            f"Your registration for {registration.establishment_name} was rejected.\n\n"
            f"Reviewer note: {note}"
        ),
        registration=registration,
        notification_type="applicant_rejected",
    )


def send_registration_submitted(registration) -> tuple[bool, bool]:
    body = (
        f"Registration received for {registration.establishment_name}.\n\n"
        "Your documents and administrator details are now awaiting Super Admin review."
    )
    applicant_sent = send_registration_notification(
        recipient=registration.admin_email,
        subject="Zootique registration received",
        body=body,
        registration=registration,
        notification_type="applicant_submitted",
    )
    establishment_sent = send_registration_notification(
        recipient=registration.establishment_contact_email,
        subject=f"Registration received for {registration.establishment_name}",
        body=body,
        registration=registration,
        notification_type="establishment_submitted",
    )
    return applicant_sent, establishment_sent


def send_registration_email_verification(registration, token: str) -> bool:
    verification_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not verification_url:
        verification_url = "http://127.0.0.1:5000"
    verification_url = f"{verification_url}/auth/verify-registration-email?registration_id={registration.id}&token={token}"
    return send_registration_notification(
        recipient=registration.admin_email,
        subject="Verify your Zootique registration email",
        body=(
            f"Use this link to verify the applicant email for {registration.establishment_name}:\n\n"
            f"{verification_url}\n\n"
            "This link expires in 30 minutes. Your application will not be submitted for review until verification is complete."
        ),
        registration=registration,
        notification_type="applicant_email_verification",
    )


def send_establishment_confirmation(registration, approved: bool) -> bool:
    status = "approved" if approved else "rejected"
    note = registration.rejection_note or "Please contact Zootique support for more information."
    return send_registration_notification(
        recipient=registration.establishment_contact_email,
        subject=f"Zootique establishment registration {status}",
        body=(
            f"The registration for {registration.establishment_name} was {status}.\n\n"
            + (f"Reviewer note: {note}" if not approved else "The establishment administrator account is now active.")
        ),
        registration=registration,
        notification_type=f"establishment_{status}",
    )


def send_registration_resubmission(registration, documents: list[str]) -> bool:
    return send_registration_notification(
        recipient=registration.admin_email,
        subject=f"Documents need resubmission for {registration.establishment_name}",
        body=(
            f"Please re-upload the following documents for {registration.establishment_name}:\n\n"
            + "\n".join(f"- {item}" for item in documents)
        ),
        registration=registration,
        notification_type="applicant_resubmission",
    )
