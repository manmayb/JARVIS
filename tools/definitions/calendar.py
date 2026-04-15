"""Google Calendar integration tool.

Gated behind GOOGLE_CALENDAR_CREDENTIALS_PATH env var — if not set,
this tool is never registered and the LLM never sees it.
"""

from tools.registry import register_tool
from core.config import settings


@register_tool(
    name="calendar_get_events",
    description="Retrieve today's events from the user's Google Calendar.",
    parameters={"type": "object", "properties": {}},
    permission_tier="base",
    task_types=["query"],
    cache_ttl_seconds=30,
    requires=["GOOGLE_CALENDAR_CREDENTIALS_PATH"]
)
async def calendar_get_events() -> str:
    """List upcoming calendar events using the Google Calendar API.

    Requires a valid OAuth2 credentials JSON file at the path specified
    by GOOGLE_CALENDAR_CREDENTIALS_PATH.
    """
    try:
        import asyncio
        from core.oauth_google import get_calendar_service
        service = get_calendar_service()
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: service.events().list(
                calendarId='primary', timeMin=now,
                maxResults=10, singleEvents=True,
                orderBy='startTime'
            ).execute()
        )
        events = result.get('items', [])
        if not events:
            return "No upcoming events found."
        lines = [f"Found {len(events)} upcoming event(s):"]
        for ev in events:
            start = ev['start'].get('dateTime', ev['start'].get('date'))
            lines.append(f"  • {start} — {ev.get('summary', 'Untitled')}")
        return "\n".join(lines)
    except ImportError:
        return "TOOL_ERROR: google-api-python-client not installed."
    except Exception as exc:
        return f"TOOL_ERROR: {exc}"


@register_tool(
    name="calendar_create_event",
    description="Schedule a new event in the user's Google Calendar. Provide title, time, and optionally attendees.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start_datetime": {"type": "string", "description": "ISO 8601 start time"},
            "end_datetime": {"type": "string", "description": "ISO 8601 end time"},
            "description": {"type": "string"},
            "attendees": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["title", "start_datetime", "end_datetime"]
    },
    permission_tier="user",
    task_types=["action"],
    requires=["GOOGLE_CALENDAR_CREDENTIALS_PATH"]
)
async def calendar_create_event(title: str, start_datetime: str,
                                 end_datetime: str,
                                 description: str = "",
                                 attendees: list[str] = []) -> str:
    """Create a new Google Calendar event."""
    try:
        import asyncio
        from core.oauth_google import get_calendar_service
        service = get_calendar_service()
        event_body = {
            'summary': title,
            'description': description,
            'start': {'dateTime': start_datetime, 'timeZone': 'UTC'},
            'end': {'dateTime': end_datetime, 'timeZone': 'UTC'},
        }
        if attendees:
            event_body['attendees'] = [{'email': a} for a in attendees]

        result = await asyncio.to_thread(
            lambda: service.events().insert(
                calendarId='primary', body=event_body
            ).execute()
        )
        return f"Event created: '{title}' — {result.get('htmlLink', 'no link')}"
    except ImportError:
        return "TOOL_ERROR: google-api-python-client not installed."
    except Exception as exc:
        return f"TOOL_ERROR: {exc}"
