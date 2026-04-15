"""Email integration tool.

Gated behind SMTP_HOST + SMTP_USER + SMTP_PASSWORD env vars — if any are
missing, this tool is never registered and the LLM never sees it.
"""

from tools.registry import register_tool
from core.config import settings


@register_tool(
    name="email_send",
    description="Send an email to a recipient. Provide to, subject, and body.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "cc": {"type": "string", "description": "Optional CC address"}
        },
        "required": ["to", "subject", "body"]
    },
    permission_tier="user",
    task_types=["action"],
    requires=["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"]
)
async def email_send(to: str, subject: str, body: str,
                     cc: str | None = None) -> str:
    """Send an email via SMTP using aiosmtplib (async, STARTTLS).

    Validates that `to` contains an @ symbol before attempting to send.
    Returns a structured status message.
    """
    if "@" not in to:
        return f"TOOL_ERROR: Invalid email address — '{to}' does not contain @."

    try:
        import aiosmtplib  # type: ignore
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = settings.smtp_user
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.set_content(body)

        result = await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=getattr(settings, "smtp_port", 587),
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
        )
        return f"Email sent to {to} with subject '{subject}'."
    except ImportError:
        return "TOOL_ERROR: aiosmtplib not installed. Run: pip install aiosmtplib"
    except Exception as exc:
        return f"TOOL_ERROR: Failed to send email — {exc}"
