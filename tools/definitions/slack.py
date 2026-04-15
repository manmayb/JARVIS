"""Slack integration tool.

Channels can be provided as Slack channel names like ``#general`` or as
channel IDs like ``C0123456789``. The tool stays hidden unless the Slack
credentials are configured.
"""

from core.config import settings
from tools.registry import register_tool


@register_tool(
    name="send_slack_message",
    description=(
        "Send a message to Slack. `channel` may be a channel name such as "
        "#general or a channel ID; if omitted, the default channel is used."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "The message text to send"},
            "channel": {
                "type": "string",
                "description": "Optional Slack channel name (e.g. #general) or channel ID",
            },
        },
        "required": ["message"],
    },
    permission_tier="user",
    task_types=["action"],
    requires=["SLACK_BOT_TOKEN", "SLACK_DEFAULT_CHANNEL"],
)
async def send_slack_message(message: str, channel: str | None = None) -> dict:
    """Send a Slack message asynchronously.

    Args:
        message: The message body to post.
        channel: Optional channel name like ``#general`` or a channel ID.
            Falls back to ``SLACK_DEFAULT_CHANNEL`` when omitted.

    Returns:
        ``{"status": "sent", "channel": ..., "ts": ...}`` on success, or
        a structured error dictionary on failure.
    """
    resolved_channel = channel or settings.slack_default_channel
    if not resolved_channel:
        return {"status": "error", "detail": "No Slack channel configured"}

    try:
        from slack_sdk.errors import SlackApiError
        from slack_sdk.web.async_client import AsyncWebClient

        client = AsyncWebClient(token=settings.slack_bot_token)
        response = await client.chat_postMessage(channel=resolved_channel, text=message)
        return {"status": "sent", "channel": resolved_channel, "ts": response["ts"]}
    except SlackApiError as exc:
        detail = getattr(exc.response, "data", None) or str(exc)
        return {"status": "error", "detail": str(detail)}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
