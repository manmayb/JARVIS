"""Google Calendar integration tool."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from core.errors import ConfigurationError
from core.oauth_google import get_calendar_service
from tools.registry import register_tool


@register_tool(
    name="list_events",
    description=(
        "List upcoming events from the user's primary Google Calendar. "
        "`time_min` must be an RFC3339 timestamp or ISO-8601 string."
    ),
    parameters={
        "type": "object",
        "properties": {
            "max_results": {"type": "integer", "default": 10},
            "time_min": {"type": "string", "description": "RFC3339/ISO-8601 start time"},
        },
    },
    permission_tier="base",
    task_types=["query"],
    cache_ttl_seconds=30,
    requires=["GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET"],
)
async def list_events(max_results: int = 10, time_min: str | None = None) -> dict:
    """List events from the primary Google Calendar asynchronously."""
    try:
        service = get_calendar_service()
        query_time = time_min or datetime.now(timezone.utc).isoformat()

        def _call():
            return service.events().list(
                calendarId="primary",
                timeMin=query_time,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

        result = await asyncio.to_thread(_call)
        events = []
        for item in result.get("items", []):
            start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
            events.append(
                {
                    "id": item.get("id"),
                    "summary": item.get("summary", "Untitled"),
                    "start": start,
                    "end": item.get("end", {}).get("dateTime") or item.get("end", {}).get("date"),
                    "htmlLink": item.get("htmlLink"),
                }
            )
        return {"status": "ok", "events": events, "count": len(events)}
    except ConfigurationError as exc:
        return {"status": "error", "detail": str(exc)}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@register_tool(
    name="create_event",
    description=(
        "Create a Google Calendar event. Provide title and ISO-8601 start/end "
        "timestamps; attendees should be email addresses."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start_datetime": {"type": "string", "description": "ISO 8601 start time"},
            "end_datetime": {"type": "string", "description": "ISO 8601 end time"},
            "description": {"type": "string"},
            "attendees": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "start_datetime", "end_datetime"],
    },
    permission_tier="user",
    task_types=["action"],
    requires=["GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET"],
)
async def create_event(
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    attendees: list[str] | None = None,
) -> dict:
    """Create a new event in the primary Google Calendar."""
    try:
        service = get_calendar_service()
        event_body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_datetime},
            "end": {"dateTime": end_datetime},
        }
        if attendees:
            event_body["attendees"] = [{"email": email} for email in attendees if email]

        def _call():
            return service.events().insert(calendarId="primary", body=event_body).execute()

        response = await asyncio.to_thread(_call)
        return {
            "status": "created",
            "event_id": response["id"],
            "html_link": response.get("htmlLink"),
        }
    except ConfigurationError as exc:
        return {"status": "error", "detail": str(exc)}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
