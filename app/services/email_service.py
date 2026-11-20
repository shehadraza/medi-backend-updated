
import smtplib
from email.message import EmailMessage
from html import escape

from app.core.config import settings


def send_password_reset_email(
    to_email: str,
    reset_url: str
) -> None:
    if not all([
        settings.SMTP_HOST,
        settings.SMTP_USERNAME,
        settings.SMTP_PASSWORD,
        settings.SMTP_FROM_EMAIL,
    ]):
        raise RuntimeError("SMTP email settings are incomplete.")

    message = EmailMessage()
    message["Subject"] = "MEDI - Password Reset Request"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email

    message.set_content(
        f"""
Hello,

We received a request to reset your MEDI account password.

Open this link to reset your password:
{reset_url}

This link expires in 30 minutes and can only be used once.

If you did not request this, you can safely ignore this email.

MEDI Team
"""
    )

    safe_url = escape(reset_url, quote=True)

    message.add_alternative(
        f"""
        <html>
          <body>
            <h2>MEDI Password Reset</h2>
            <p>We received a request to reset your MEDI account password.</p>
            <p>
              <a href="{safe_url}"
                 style="background:#087f8c;color:white;padding:12px 20px;
                        text-decoration:none;border-radius:8px;">
                Reset Password
              </a>
            </p>
            <p>This link expires in 30 minutes and can only be used once.</p>
            <p>If you did not request this, ignore this email.</p>
            <p>MEDI Team</p>
          </body>
        </html>
        """,
        subtype="html"
    )

    with smtplib.SMTP(
        settings.SMTP_HOST,
        settings.SMTP_PORT,
        timeout=20
    ) as server:
        server.ehlo()

        if settings.SMTP_USE_TLS:
            server.starttls()
            server.ehlo()

        server.login(
            settings.SMTP_USERNAME,
            settings.SMTP_PASSWORD
        )

        server.send_message(message)

def send_email_verification_email(
    to_email: str,
    verification_url: str
) -> None:
    if not all([
        settings.SMTP_HOST,
        settings.SMTP_USERNAME,
        settings.SMTP_PASSWORD,
        settings.SMTP_FROM_EMAIL,
    ]):
        raise RuntimeError("SMTP email settings are incomplete.")

    message = EmailMessage()
    message["Subject"] = "MEDI - Verify Your Email Address"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email

    message.set_content(
        f"""
Hello,

Welcome to MEDI!

Please verify your email address to activate your MEDI account.

Open this link to verify your email:
{verification_url}

This link expires in 30 minutes and can only be used once.

If you did not create a MEDI account, you can safely ignore this email.

MEDI Team
"""
    )

    safe_url = escape(verification_url, quote=True)

    message.add_alternative(
        f"""
        <html>
          <body style="font-family:Arial,sans-serif;color:#24352d;">
            <h2>Welcome to MEDI!</h2>
            <p>
              Thank you for creating your MEDI account.
              Please verify your email address to continue.
            </p>
            <p>
              <a href="{safe_url}"
                 style="background:#087f8c;color:white;padding:12px 20px;
                        text-decoration:none;border-radius:8px;">
                Verify Email Address
              </a>
            </p>
            <p>This link expires in 30 minutes and can only be used once.</p>
            <p>If you did not create this account, ignore this email.</p>
            <p>MEDI Team</p>
          </body>
        </html>
        """,
        subtype="html",
    )

    with smtplib.SMTP(
        settings.SMTP_HOST,
        settings.SMTP_PORT,
        timeout=20,
    ) as server:
        server.ehlo()

        if settings.SMTP_USE_TLS:
            server.starttls()
            server.ehlo()

        server.login(
            settings.SMTP_USERNAME,
            settings.SMTP_PASSWORD,
        )

        server.send_message(message)
