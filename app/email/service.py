"""Centralized, best-effort SMTP delivery for workflow notifications."""
from email.message import EmailMessage as MIMEEmailMessage
from email.utils import formataddr
import logging
import smtplib
import ssl
from collections.abc import Mapping

from app.config import SMTPSettings, load_smtp_settings
from app.email.templates import render_template
from app.email.types import EmailMessage

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """A workflow email could not be configured or delivered."""


def notify_workflow_email(
    template_key: str,
    recipient: str,
    context: Mapping,
) -> bool:
    """Send a workflow message if SMTP is configured; never raise delivery errors."""
    try:
        settings = load_smtp_settings()
        if settings is None:
            logger.debug("workflow_email_disabled event=%s", template_key)
            return False
        message = render_template(template_key, "v1", recipient, context)
        _deliver(message, settings)
        return True
    except Exception as error:
        logger.warning(
            "workflow_email_failed event=%s error_type=%s",
            template_key,
            type(error).__name__,
        )
        return False


def _deliver(message: EmailMessage, settings: SMTPSettings) -> None:
    mime_message = MIMEEmailMessage()
    mime_message["From"] = formataddr((settings.sender_name, settings.sender_email))
    mime_message["To"] = message.recipient
    mime_message["Subject"] = message.subject
    mime_message.set_content(message.text_body)

    client_type = smtplib.SMTP_SSL if settings.use_ssl else smtplib.SMTP
    try:
        with client_type(
            settings.host,
            settings.port,
            timeout=settings.timeout,
            **({"context": ssl.create_default_context()} if settings.use_ssl else {}),
        ) as client:
            if settings.use_tls:
                client.ehlo()
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if settings.username is not None and settings.password is not None:
                client.login(settings.username, settings.password)
            refused = client.send_message(mime_message)
            if message.recipient in refused:
                raise smtplib.SMTPRecipientsRefused(refused)
    except Exception as error:
        raise EmailDeliveryError("SMTP delivery failed") from error
