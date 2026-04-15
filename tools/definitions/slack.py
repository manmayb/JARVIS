"""Slack integration tool.

STATUS: NOT CONFIGURED — requires a Slack Bot Token in .env.
The tool is registered so the LLM can see it, but will explicitly report
its unconfigured state instead of silently faking success.
"""

from tools.registry import register_tool
from core.config import settings


def _is_configured() -> bool:
    """Check whether Slack credentials are available."""
    token = getattr(settings, "slack_bot_token", None)
    return bool(token and not token.startswith("not_set"))


@register_tool(
    name="slack_send_message",
    description="Send a message to a Slack channel or user. Requires SLACK_BOT_TOKEN to be configured.",
    parameters={
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "Channel name (e.g. #general) or user ID"},
            "message": {"type": "string", "description": "The message text to send"}
        },
        "required": ["channel", "message"]
    },
    permission_tier="user",
    task_types=["action"]
)
async def slack_send_message(channel: str, message: str) -> str:
    if not _is_configured():
        return (
            "TOOL_NOT_CONFIGURED: Slack integration is not set up. "
            "To enable it, add SLACK_BOT_TOKEN to your .env file and install the slack-sdk package. "
            "Please inform the user that this action could not be completed."
        )

    try:
        from slack_sdk.web.async_client import AsyncWebClient  # type: ignore
        client = AsyncWebClient(token=settings.slack_bot_token)
        resp = await client.chat_postMessage(channel=channel, text=message)
        return f"Message delivered to {channel}. Timestamp: {resp['ts']}"
    except ImportError:
        return (
            "TOOL_NOT_CONFIGURED: slack-sdk is not installed. "
            "Run: pip install slack-sdk"
        )
    except Exception as exc:
        return f"TOOL_ERROR: Failed to send Slack message — {exc}"
