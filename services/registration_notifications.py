"""Registration email notifications.

Dedicated email service using Brevo (Sendinblue) Transactional REST API over HTTPS (port 443).
Emails are beautifully styled with responsive HTML templates matching Zootique branding.
Falls back to local SMTP only for offline development.
"""

from __future__ import annotations

import html
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


def _wrap_email_html(
    *,
    preheader: str,
    badge_text: str,
    badge_bg: str = "#ecfdf5",
    badge_color: str = "#065f46",
    badge_border: str = "#a7f3d0",
    headline: str,
    subtitle: str,
    content_html: str,
    call_to_action: dict | None = None,
    secondary_info: str | None = None,
) -> str:
    """Generate a clean, responsive HTML email matching Zootique's dark green brand aesthetic."""
    cta_html = ""
    if call_to_action and call_to_action.get("url") and call_to_action.get("label"):
        btn_bg = call_to_action.get("bg", "#1a4f32")
        btn_color = call_to_action.get("color", "#ffffff")
        btn_url = html.escape(call_to_action["url"])
        btn_label = html.escape(call_to_action["label"])
        cta_html = f"""
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin: 28px 0 24px 0;">
          <tr>
            <td align="center" style="border-radius: 6px; background-color: {btn_bg};">
              <a href="{btn_url}" target="_blank" style="font-size: 14px; font-weight: 700; color: {btn_color}; text-decoration: none; padding: 14px 28px; border-radius: 6px; display: inline-block; letter-spacing: 0.3px; border: 1px solid {btn_bg};">
                {btn_label} &rarr;
              </a>
            </td>
          </tr>
        </table>
        """
        if call_to_action.get("note"):
            cta_html += f"""
            <p style="margin: 0 0 16px 0; font-size: 12px; color: #64748b; line-height: 1.5;">
              {html.escape(call_to_action["note"])}
            </p>
            <p style="margin: 0; font-size: 11px; color: #94a3b8; word-break: break-all; line-height: 1.4;">
              If the button doesn't work, copy and paste this URL into your browser:<br>
              <a href="{btn_url}" style="color: #0d9488; text-decoration: underline;">{btn_url}</a>
            </p>
            """

    sec_html = ""
    if secondary_info:
        sec_html = f"""
        <div style="margin-top: 24px; padding-top: 20px; border-top: 1px solid #e2e8f0; font-size: 13px; color: #475569; line-height: 1.6;">
          {secondary_info}
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(headline)}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
  <!-- Hidden preheader text -->
  <div style="display: none; font-size: 1px; color: #f1f5f9; line-height: 1px; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden;">
    {html.escape(preheader)}
  </div>

  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f1f5f9; padding: 32px 16px;">
    <tr>
      <td align="center">
        <!-- Main Card Container -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 580px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 18px rgba(0, 0, 0, 0.06); border: 1px solid #e2e8f0;">
          
          <!-- Brand Header Banner -->
          <tr>
            <td style="background-color: #132a1c; background-image: linear-gradient(135deg, #132a1c 0%, #1a4f32 100%); padding: 32px 36px; text-align: left;">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td>
                    <span style="font-size: 22px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px; display: inline-flex; align-items: center; text-decoration: none;">
                      &#127794; Zootique
                    </span>
                    <span style="display: block; font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: #a7f3d0; margin-top: 4px; font-weight: 600;">
                      Wildlife &amp; Establishment Management
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Content Body -->
          <tr>
            <td style="padding: 36px 36px 28px 36px; background-color: #ffffff;">
              <!-- Status Badge -->
              <div style="display: inline-block; background-color: {badge_bg}; border: 1px solid {badge_border}; color: {badge_color}; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; padding: 4px 10px; border-radius: 4px; margin-bottom: 16px;">
                {html.escape(badge_text)}
              </div>

              <!-- Headline -->
              <h1 style="margin: 0 0 10px 0; font-size: 24px; font-weight: 800; color: #0f172a; line-height: 1.25; letter-spacing: -0.3px;">
                {html.escape(headline)}
              </h1>

              <!-- Subtitle -->
              <p style="margin: 0 0 24px 0; font-size: 14px; color: #64748b; line-height: 1.5;">
                {html.escape(subtitle)}
              </p>

              <!-- Dynamic Section HTML -->
              <div style="font-size: 14px; color: #334155; line-height: 1.6;">
                {content_html}
              </div>

              <!-- Call To Action Button (if present) -->
              {cta_html}

              <!-- Secondary Details -->
              {sec_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f8fafc; padding: 24px 36px; text-align: center; border-top: 1px solid #e2e8f0;">
              <p style="margin: 0 0 6px 0; font-size: 12px; color: #94a3b8; font-weight: 500;">
                &copy; 2026 Zootique Wildlife Management Platform. All rights reserved.
              </p>
              <p style="margin: 0; font-size: 11px; color: #cbd5e1;">
                This automated notification was generated securely regarding your establishment application.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _send_via_brevo(*, recipient: str, subject: str, text_body: str, html_body: str | None, sender: str) -> bool:
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

    clean_sender = sender
    sender_name = "Zootique"
    if "<" in sender and ">" in sender:
        sender_name = sender.split("<")[0].strip() or "Zootique"
        clean_sender = sender.split("<")[1].split(">")[0].strip()

    payload = {
        "sender": {"name": sender_name, "email": clean_sender},
        "to": [{"email": recipient}],
        "subject": subject,
        "textContent": text_body,
    }
    if html_body:
        payload["htmlContent"] = html_body

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


def _send_via_smtp(*, recipient: str, subject: str, text_body: str, html_body: str | None, sender: str) -> bool:
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
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    port = int(os.environ.get("SMTP_PORT") or os.environ.get("MAIL_PORT") or "587")
    use_tls = (os.environ.get("SMTP_USE_TLS") or os.environ.get("MAIL_USE_TLS") or "true").lower() not in {"0", "false", "no"}
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)
    return True


def send_registration_notification(
    *,
    recipient: str | None,
    subject: str,
    body: str,
    html_body: str | None = None,
    registration=None,
    notification_type: str = "registration"
) -> bool:
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

    # --- Primary: Brevo HTTP REST API ---
    brevo_key = os.environ.get("BREVO_API_KEY", "").strip()
    if brevo_key:
        try:
            if _send_via_brevo(recipient=recipient, subject=subject, text_body=body, html_body=html_body, sender=sender):
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
        if _send_via_smtp(recipient=recipient, subject=subject, text_body=body, html_body=html_body, sender=sender):
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


def send_registration_rejected(registration, resubmission_token: str | None = None) -> bool:
    note = registration.rejection_note or "No additional note was provided."
    base_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/") or "https://zootique.vercel.app"

    resubmission_url = ""
    cta = None
    resub_plain = ""
    if resubmission_token:
        resubmission_url = (
            f"{base_url}/auth/resubmit-registration"
            f"?registration_id={registration.id}&token={resubmission_token}"
        )
        cta = {
            "label": "Appeal & Resubmit Documents",
            "url": resubmission_url,
            "bg": "#1a4f32",
            "color": "#ffffff",
            "note": "This resubmission link expires in 7 days.",
        }
        resub_plain = f"\n\nTo appeal or re-upload your documents, use the link below:\n{resubmission_url}\n\nThis link expires in 7 days."

    # HTML Card Content
    content_html = f"""
    <div style="background-color: #fef2f2; border: 1px solid #fecaca; border-left: 4px solid #ef4444; border-radius: 8px; padding: 18px 20px; margin-bottom: 20px;">
      <div style="font-size: 11px; font-weight: 700; color: #991b1b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">
        Reviewer Feedback &amp; Reason
      </div>
      <div style="font-size: 14px; font-weight: 600; color: #7f1d1d; line-height: 1.5;">
        {html.escape(note)}
      </div>
    </div>
    <p style="margin: 0; color: #475569; font-size: 14px; line-height: 1.6;">
      Your application for <strong>{html.escape(registration.establishment_name)}</strong> could not be approved in its current state. Please review the feedback above and click the button below to upload corrected documentation or submit an appeal.
    </p>
    """

    html_email = _wrap_email_html(
        preheader=f"Your registration for {registration.establishment_name} needs attention.",
        badge_text="Application Update",
        badge_bg="#fef2f2",
        badge_color="#991b1b",
        badge_border="#fecaca",
        headline="Registration Needs Attention",
        subtitle=f"Application update for {registration.establishment_name}",
        content_html=content_html,
        call_to_action=cta,
    )

    plain_body = (
        f"Your registration for {registration.establishment_name} was rejected.\n\n"
        f"Reviewer note: {note}"
        f"{resub_plain}"
    )

    return send_registration_notification(
        recipient=registration.admin_email,
        subject=f"Your Zootique registration needs attention: {registration.establishment_name}",
        body=plain_body,
        html_body=html_email,
        registration=registration,
        notification_type="applicant_rejected",
    )


def send_registration_email_verification(registration, token: str) -> bool:
    verification_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/") or "https://zootique.vercel.app"
    verification_url = f"{verification_url}/auth/verify-registration-email?registration_id={registration.id}&token={token}"

    content_html = f"""
    <p style="margin: 0 0 16px 0; color: #334155; font-size: 14px; line-height: 1.6;">
      Thank you for applying to register <strong>{html.escape(registration.establishment_name)}</strong> on Zootique.
    </p>
    <p style="margin: 0 0 20px 0; color: #475569; font-size: 14px; line-height: 1.6;">
      To protect your establishment's account, please verify your email address to submit your application into the Super Admin review queue.
    </p>
    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; text-align: center; margin: 16px 0 24px 0;">
      <span style="display: block; font-size: 11px; text-transform: uppercase; font-weight: 700; color: #64748b; letter-spacing: 1px; margin-bottom: 8px;">
        Or enter this verification token directly:
      </span>
      <code style="font-family: monospace; font-size: 16px; font-weight: 700; color: #132a1c; background: #ffffff; padding: 6px 14px; border-radius: 4px; border: 1px dashed #cbd5e1; display: inline-block; word-break: break-all;">
        {html.escape(token)}
      </code>
    </div>
    """

    html_email = _wrap_email_html(
        preheader=f"Verify your email to complete registration for {registration.establishment_name}",
        badge_text="Email Verification",
        badge_bg="#ecfdf5",
        badge_color="#065f46",
        badge_border="#a7f3d0",
        headline="Verify Your Email Address",
        subtitle=f"Application for {registration.establishment_name}",
        content_html=content_html,
        call_to_action={
            "label": "Verify Email Address",
            "url": verification_url,
            "bg": "#1a4f32",
            "color": "#ffffff",
            "note": "This link expires in 30 minutes. Your application is not queued for review until verified.",
        },
    )

    plain_body = (
        f"Use this link to verify the applicant email for {registration.establishment_name}:\n\n"
        f"{verification_url}\n\n"
        f"Verification token: {token}\n\n"
        "This link expires in 30 minutes. Your application will not be submitted for review until verification is complete."
    )

    return send_registration_notification(
        recipient=registration.admin_email,
        subject=f"Verify your Zootique registration email: {registration.establishment_name}",
        body=plain_body,
        html_body=html_email,
        registration=registration,
        notification_type="applicant_email_verification",
    )


def send_registration_approved(registration, activation_token: str | None = None) -> bool:
    base_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/") or "https://zootique.vercel.app"
    activation_url = ""
    cta = None
    act_plain = ""
    if activation_token:
        activation_url = f"{base_url}/auth/activate-zoo-admin?registration_id={registration.id}&token={activation_token}"
        cta = {
            "label": "Activate Administrator Account",
            "url": activation_url,
            "bg": "#1a4f32",
            "color": "#ffffff",
            "note": "Set your permanent password to begin accessing your establishment dashboard.",
        }
        act_plain = f"\n\nActivate the administrator account here:\n{activation_url}"

    content_html = f"""
    <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; border-left: 4px solid #16a34a; border-radius: 8px; padding: 18px 20px; margin-bottom: 20px;">
      <div style="font-size: 14px; font-weight: 700; color: #166534;">
        Congratulations! Your establishment has been verified and approved.
      </div>
    </div>
    <p style="margin: 0 0 14px 0; color: #334155; font-size: 14px; line-height: 1.6;">
      Your registration for <strong>{html.escape(registration.establishment_name)}</strong> ({html.escape(registration.establishment_type)}) was officially approved by the Zootique Super Admin team.
    </p>
    <p style="margin: 0; color: #475569; font-size: 14px; line-height: 1.6;">
      Click below to activate your Administrator account and start managing exhibits, bookings, and operations.
    </p>
    """

    html_email = _wrap_email_html(
        preheader=f"Your registration for {registration.establishment_name} was approved!",
        badge_text="Application Approved",
        badge_bg="#f0fdf4",
        badge_color="#166534",
        badge_border="#bbf7d0",
        headline="Welcome to Zootique!",
        subtitle=f"{registration.establishment_name} is now approved",
        content_html=content_html,
        call_to_action=cta,
    )

    plain_body = (
        f"Your registration for {registration.establishment_name} was approved. "
        "Your Zootique administrator account is ready to activate."
        f"{act_plain}"
    )

    return send_registration_notification(
        recipient=registration.admin_email,
        subject=f"Approved: Welcome {registration.establishment_name} to Zootique",
        body=plain_body,
        html_body=html_email,
        registration=registration,
        notification_type="applicant_approved",
    )


def send_registration_submitted(registration) -> tuple[bool, bool]:
    content_html = f"""
    <p style="margin: 0 0 16px 0; color: #334155; font-size: 14px; line-height: 1.6;">
      We have successfully received the registration dossier for <strong>{html.escape(registration.establishment_name)}</strong>.
    </p>
    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 18px; margin: 16px 0;">
      <div style="font-size: 12px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Next Steps</div>
      <div style="font-size: 13px; color: #334155; line-height: 1.5;">
        Your documents and establishment details are currently queued for Super Admin review. You will receive an email notification as soon as the review is complete.
      </div>
    </div>
    """

    html_email = _wrap_email_html(
        preheader=f"Registration received for {registration.establishment_name}",
        badge_text="Application Submitted",
        badge_bg="#eff6ff",
        badge_color="#1e40af",
        badge_border="#bfdbfe",
        headline="Registration Received",
        subtitle=f"Under review: {registration.establishment_name}",
        content_html=content_html,
    )

    plain_body = (
        f"Registration received for {registration.establishment_name}.\n\n"
        "Your documents and administrator details are now awaiting Super Admin review."
    )

    applicant_sent = send_registration_notification(
        recipient=registration.admin_email,
        subject=f"Zootique registration received: {registration.establishment_name}",
        body=plain_body,
        html_body=html_email,
        registration=registration,
        notification_type="applicant_submitted",
    )

    establishment_sent = send_registration_notification(
        recipient=registration.establishment_contact_email,
        subject=f"Registration received for {registration.establishment_name}",
        body=plain_body,
        html_body=html_email,
        registration=registration,
        notification_type="establishment_submitted",
    )

    return applicant_sent, establishment_sent


def send_establishment_confirmation(registration, approved: bool) -> bool:
    status_text = "approved" if approved else "declined"
    badge_bg = "#f0fdf4" if approved else "#fef2f2"
    badge_color = "#166534" if approved else "#991b1b"
    badge_border = "#bbf7d0" if approved else "#fecaca"

    note = registration.rejection_note or "Please contact Zootique support for more information."

    desc = "The establishment administrator account is now active and operational." if approved else f"Reviewer note: {note}"

    content_html = f"""
    <p style="margin: 0 0 14px 0; color: #334155; font-size: 14px; line-height: 1.6;">
      This confirmation is sent regarding the registration for <strong>{html.escape(registration.establishment_name)}</strong>.
    </p>
    <div style="background-color: {badge_bg}; border: 1px solid {badge_border}; border-radius: 8px; padding: 16px 18px; margin: 16px 0;">
      <div style="font-size: 13px; font-weight: 600; color: {badge_color}; line-height: 1.5;">
        {html.escape(desc)}
      </div>
    </div>
    """

    html_email = _wrap_email_html(
        preheader=f"Establishment registration status: {status_text.capitalize()}",
        badge_text=f"Status: {status_text.capitalize()}",
        badge_bg=badge_bg,
        badge_color=badge_color,
        badge_border=badge_border,
        headline=f"Registration {status_text.capitalize()}",
        subtitle=f"Establishment notice for {registration.establishment_name}",
        content_html=content_html,
    )

    plain_body = (
        f"The registration for {registration.establishment_name} was {status_text}.\n\n"
        + (f"Reviewer note: {note}" if not approved else "The establishment administrator account is now active.")
    )

    return send_registration_notification(
        recipient=registration.establishment_contact_email,
        subject=f"Zootique establishment registration {status_text}: {registration.establishment_name}",
        body=plain_body,
        html_body=html_email,
        registration=registration,
        notification_type=f"establishment_{status_text}",
    )


def send_registration_resubmission(registration, documents: list[str]) -> bool:
    docs_list_html = "".join(f"<li style='margin-bottom: 6px;'>{html.escape(d)}</li>" for d in documents)
    content_html = f"""
    <p style="margin: 0 0 14px 0; color: #334155; font-size: 14px; line-height: 1.6;">
      The following documents need to be re-uploaded for <strong>{html.escape(registration.establishment_name)}</strong>:
    </p>
    <ul style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 36px; margin: 16px 0; color: #334155; font-size: 13px; font-weight: 600;">
      {docs_list_html}
    </ul>
    """

    html_email = _wrap_email_html(
        preheader=f"Documents need resubmission for {registration.establishment_name}",
        badge_text="Action Required",
        badge_bg="#fffbeb",
        badge_color="#92400e",
        badge_border="#fde68a",
        headline="Document Resubmission Requested",
        subtitle=f"{registration.establishment_name}",
        content_html=content_html,
    )

    plain_body = (
        f"Please re-upload the following documents for {registration.establishment_name}:\n\n"
        + "\n".join(f"- {item}" for item in documents)
    )

    return send_registration_notification(
        recipient=registration.admin_email,
        subject=f"Documents need resubmission for {registration.establishment_name}",
        body=plain_body,
        html_body=html_email,
        registration=registration,
        notification_type="applicant_resubmission",
    )
