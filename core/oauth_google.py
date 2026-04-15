"""Google OAuth helpers for Calendar integration."""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from core.config import settings
from core.errors import ConfigurationError

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = Path(__file__).resolve().parent.parent / "token.json"


def get_calendar_service():
    """Return an authenticated Google Calendar API client.

    The client is created from token.json in the project root. If the token is
    missing, invalid, or cannot be refreshed, a ConfigurationError is raised.
    """
    if not TOKEN_PATH.exists():
        raise ConfigurationError(
            "Google Calendar token.json is missing. Run auth_google.py to generate it."
        )

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    except Exception as exc:
        raise ConfigurationError(f"Invalid Google Calendar token.json: {exc}") from exc

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                raise ConfigurationError(f"Failed to refresh Google Calendar token: {exc}") from exc
        else:
            raise ConfigurationError(
                "Google Calendar credentials are invalid or expired. Re-run auth_google.py."
            )

    # Persist refreshed credentials for subsequent runs.
    try:
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    except Exception:
        pass

    return build("calendar", "v3", credentials=creds, cache_discovery=False)
