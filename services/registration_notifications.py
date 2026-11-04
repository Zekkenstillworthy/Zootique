"""Registration email notifications.

Dedicated email service using Brevo (Sendinblue) Transactional REST API over HTTPS (port 443).
Works reliably on serverless environments like Vercel with no blocked SMTP ports.
Falls back to local SMTP only for offline development.
"""

from __future__ import annotations

import json
import os
import smtplib
import urllib.request
import urllib.error
from email.message import EmailMessage

from flask import current_app
from models import RegistrationEmailAttempt, db


def _sender_address() -> str:
    """Return the sender email address."""
    return (
        os.environ.get("BREVO_SENDER_EMAIL")
        or os.environ.get("SMTP_FROM")
        or os.environ.get("SMTP_USERNAME")
        or "zootique22@gmail.com"
    ).strip()


def _send_via_brevo(*, recipient: str, subject: str, body: str, sender: str) -> bool:
    """Send an email using Brevo's v3 Transactional Email REST API over HTTPS."""
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    if not api_key:
        raise ValueError("BREVO_API_KEY environment variable is not configured.")

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
    }

    # Extract clean email and name if sender is in format 'Name <email@domain.com>'
    clean_sender = sender
    sender_name = "Zootique"
    if "<" in sender and ">" in sender:
        sender_name = sender.split("<")[0].strip() or "Zootique"
        clean_sender = sender.split("<")[1].split(">")[0].strip()

    payload = {
        "sender": {"name": sender_name, "email": clean_sender},
        "to": [{"email": recipient}],
        "subject": subject,
        "textContent": body,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status in (200, 201, 202):
                return True
            current_app.logger.warning("Brevo responded with unexpected status %s", response.status)
            return False
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        current_app.logger.warning("Brevo HTTP error %s: %s", exc.code, err_body)
        raise RuntimeError(f"Brevo HTTP {exc.code}: {err_body}") from exc
    except Exception as exc:
        current_app.logger.warning("Brevo send error: %s", exc)
        raise


def _send_via_smtp(*, recipient: str, subject: str, body: str, sender: str) -> bool:
    """Send an email via SMTP (local dev only)."""
    username = (os.environ.get("SMTP_USERNAME") or os.environ.get("MAIL_USERNAME") or "").strip()
    password = (os.environ.get("SMTP_PASSWORD") or os.environ.get("MAIL_PASSWORD") or "").strip()
    host = (os.environ.get("SMTP_HOST") or os.environ.get("MAIL_SERVER") or "").strip()

    if not host or not sender:
        return False

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

    # --- Primary: Brevo HTTP REST API (HTTPS port 443) ---
    brevo_key = os.environ.get("BREVO_API_KEY", "").strip()
    if brevo_key:
        try:
            if _send_via_brevo(recipient=recipient, subject=subject, body=body, sender=sender):
                if attempt:
                    attempt.status = "sent"
                return True
        except Exception as exc:
            if attempt:
                attempt.status = "failed"
                attempt.error_message = f"[Brevo] {exc}"[:500]
            return False

    # --- Local Dev Fallback: SMTP ---
    try:
        if _send_via_smtp(recipient=recipient, subject=subject, body=body, sender=sender):
            if attempt:
                attempt.status = "sent"
            return True
    except Exception as exc:
        current_app.logger.warning("SMTP failed for %s: %s", recipient, exc)
        if attempt:
            attempt.status = "failed"
            attempt.error_message = f"[SMTP] {str(exc)}"[:500]
        return False

    if attempt:
        attempt.status = "failed"
        attempt.error_message = "No email provider configured (set BREVO_API_KEY or SMTP credentials)."
    return False


def send_registration_approved(registration, activation_token: str | None = None) -> bool:
    activation_url = ""
    if activation_token:
        base_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/") or "https://zootique.vercel.app"
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


def send_registration_rejected(registration, resubmission_token: str | None = None) -> bool:
    note = registration.rejection_note or "No additional note was provided."
    base_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/") or "https://zootique.vercel.app"
    resubmission_section = ""
    if resubmission_token:
        resubmission_url = (
            f"{base_url}/auth/resubmit-registration"
            f"?registration_id={registration.id}&token={resubmission_token}"
        )
        resubmission_section = (
            f"\n\nTo appeal or re-upload your documents, use the link below:\n"
            f"{resubmission_url}\n\n"
            "This resubmission link expires in 7 days."
        )
    return send_registration_notification(
        recipient=registration.admin_email,
        subject="Your Zootique establishment registration needs attention",
        body=(
            f"Your registration for {registration.establishment_name} was rejected.\n\n"
            f"Reviewer note: {note}"
            f"{resubmission_section}"
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
        verification_url = "https://zootique.vercel.app"
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
