"""Email integration tool.

Send mail through STARTTLS SMTP using async I/O only. The tool stays
hidden unless the SMTP environment variables are configured.
"""

from email.message import EmailMessage
from email.utils import getaddresses, make_msgid

from core.config import settings
from tools.registry import register_tool


def _recipient_list(to: str, cc: str | None = None) -> list[str]:
    recipients = [addr for _, addr in getaddresses([to, cc or ""]) if addr]
    return recipients


@register_tool(
    name="send_email",
    description=(
        "Send an email to one or more recipients. Use a valid email address "
        "for `to`; `cc` is optional and may contain comma-separated addresses."
    ),
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "cc": {"type": "string", "description": "Optional CC address or comma-separated list"},
        },
        "required": ["to", "subject", "body"],
    },
    permission_tier="user",
    task_types=["action"],
    requires=["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"],
)
async def send_email(to: str, subject: str, body: str, cc: str | None = None) -> dict:
    """Send an email asynchronously using SMTP STARTTLS.

    Args:
        to: Primary recipient address. Must contain an ``@`` character.
        subject: Email subject line.
        body: Plain-text message body.
        cc: Optional carbon-copy recipient(s), comma-separated.

    Returns:
        A dictionary with ``status='sent'`` and the generated ``message_id``
        on success, or ``status='error'`` with a human-readable ``detail`` on
        failure.
    """
    if "@" not in to:
        return {"status": "error", "detail": f"Invalid email address: {to}"}

    try:
        import aiosmtplib

        msg = EmailMessage()
        msg["From"] = settings.smtp_user or ""
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc

        message_id = make_msgid()
        msg["Message-ID"] = message_id
        msg.set_content(body)

        recipients = _recipient_list(to, cc)
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
            recipients=recipients,
        )
        return {"status": "sent", "to": to, "message_id": message_id}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
