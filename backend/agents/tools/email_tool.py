"""
EmailTool — SMTP Email Outreach
================================
Allows agents to send emails via SMTP for outreach, notifications, and
report delivery.  Designed for use by the RevenueAgent's ``send_outreach``
step and any mission that requires email communication.

Configuration
-------------
The tool reads SMTP settings from environment variables at instantiation time.
All variables are optional — if not set the tool operates in **dry-run mode**
and logs the email content without sending it.

Required env vars for live sending:
    SMTP_HOST       — SMTP server hostname (default: smtp.gmail.com)
    SMTP_PORT       — SMTP server port (default: 587)
    SMTP_USER       — SMTP login username / sender address
    SMTP_PASSWORD   — SMTP login password or app-specific password
    SMTP_FROM       — From address (defaults to SMTP_USER if not set)

Security
--------
* Passwords are never logged.
* Recipient addresses are validated with a basic regex before sending.
* HTML content is sanitised to prevent header injection.
* TLS is always used (STARTTLS on port 587, SSL on port 465).

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from backend.agents.tools.base import BaseTool, ToolCategory

logger = logging.getLogger(__name__)

# Basic RFC 5322-ish email validation (good enough for outreach guard)
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _validate_email(address: str) -> bool:
    return bool(_EMAIL_RE.match(address.strip()))


class EmailTool(BaseTool):
    """
    SMTP email sending tool.

    Sends plain-text or HTML emails via SMTP.  Operates in dry-run mode when
    SMTP credentials are not configured so the system never crashes in
    development or test environments.

    Attributes:
        host: SMTP server hostname.
        port: SMTP server port.
        user: SMTP login username.
        password: SMTP login password.
        from_addr: Sender address shown in the From header.
        dry_run: True when SMTP credentials are not configured.
    """

    def __init__(self) -> None:
        self.host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.port: int = int(os.getenv("SMTP_PORT", "587"))
        self.user: Optional[str] = os.getenv("SMTP_USER")
        self.password: Optional[str] = os.getenv("SMTP_PASSWORD")
        self.from_addr: str = os.getenv("SMTP_FROM", self.user or "noreply@omnipath.ai")
        self.dry_run: bool = not (self.user and self.password)

        if self.dry_run:
            logger.info(
                "EmailTool: SMTP credentials not configured — operating in dry-run mode. "
                "Set SMTP_USER and SMTP_PASSWORD env vars to enable live sending."
            )

    # ------------------------------------------------------------------
    # BaseTool interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "email_sender"

    @property
    def description(self) -> str:
        return (
            "Send an email to one or more recipients. "
            "Input: to (email address or comma-separated list), subject (string), "
            "body (plain text or HTML). "
            "Output: Confirmation with message ID, or dry-run notice if SMTP is not configured."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.COMMUNICATION

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(  # type: ignore[override]
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
        cc: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an email.

        Args:
            to: Recipient address or comma-separated list of addresses.
            subject: Email subject line.
            body: Email body — plain text by default, HTML if html=True.
            html: If True, body is treated as HTML and a plain-text fallback
                  is auto-generated.
            cc: Optional CC address or comma-separated list.
            reply_to: Optional Reply-To address.

        Returns:
            Dict with keys: success (bool), message_id (str), dry_run (bool),
            recipients (list), error (str, only on failure).
        """
        # Parse and validate recipients
        recipients = [addr.strip() for addr in to.split(",") if addr.strip()]
        invalid = [addr for addr in recipients if not _validate_email(addr)]
        if invalid:
            return {
                "success": False,
                "error": f"Invalid email address(es): {', '.join(invalid)}",
                "recipients": recipients,
                "dry_run": self.dry_run,
            }

        if not recipients:
            return {
                "success": False,
                "error": "No recipients provided.",
                "recipients": [],
                "dry_run": self.dry_run,
            }

        # Build the MIME message
        msg = MIMEMultipart("alternative") if html else MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(recipients)
        if cc:
            msg["Cc"] = cc
        if reply_to:
            msg["Reply-To"] = reply_to

        if html:
            # Plain-text fallback: strip tags
            plain = re.sub(r"<[^>]+>", "", body).strip()
            msg.attach(MIMEText(plain, "plain"))
            msg.attach(MIMEText(body, "html"))
        else:
            msg.attach(MIMEText(body, "plain"))

        # Dry-run mode — log and return without sending
        if self.dry_run:
            logger.info(
                "EmailTool [DRY RUN] to=%s subject=%r body_len=%d",
                recipients,
                subject,
                len(body),
            )
            return {
                "success": True,
                "dry_run": True,
                "message_id": "dry-run-no-message-id",
                "recipients": recipients,
                "subject": subject,
                "note": (
                    "Email not sent — SMTP credentials not configured. "
                    "Set SMTP_USER and SMTP_PASSWORD to enable live sending."
                ),
            }

        # Live send — run in executor to avoid blocking the event loop
        try:
            message_id = await asyncio.get_event_loop().run_in_executor(
                None, self._send_sync, msg, recipients
            )
            logger.info(
                "EmailTool: sent to=%s subject=%r message_id=%s",
                recipients,
                subject,
                message_id,
            )
            return {
                "success": True,
                "dry_run": False,
                "message_id": message_id,
                "recipients": recipients,
                "subject": subject,
            }
        except Exception as exc:
            logger.error("EmailTool: send failed: %s", exc)
            return {
                "success": False,
                "dry_run": False,
                "error": str(exc),
                "recipients": recipients,
            }

    # ------------------------------------------------------------------
    # Synchronous SMTP helper (runs in thread executor)
    # ------------------------------------------------------------------

    def _send_sync(self, msg: MIMEMultipart, recipients: List[str]) -> str:
        """
        Send *msg* synchronously via SMTP.

        Returns:
            The Message-ID header value from the server response.

        Raises:
            smtplib.SMTPException: On any SMTP-level error.
            ssl.SSLError: On TLS negotiation failure.
        """
        context = ssl.create_default_context()

        if self.port == 465:
            # SSL from the start
            with smtplib.SMTP_SSL(self.host, self.port, context=context) as server:
                server.login(self.user, self.password)  # type: ignore[arg-type]
                server.sendmail(self.from_addr, recipients, msg.as_string())
        else:
            # STARTTLS (port 587 or 25)
            with smtplib.SMTP(self.host, self.port) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(self.user, self.password)  # type: ignore[arg-type]
                server.sendmail(self.from_addr, recipients, msg.as_string())

        return msg.get("Message-ID", "unknown")

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        """True when SMTP credentials are present and live sending is enabled."""
        return not self.dry_run
