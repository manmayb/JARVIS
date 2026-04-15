"""One-shot Google Calendar OAuth helper.

Run this script locally to generate token.json in the project root.
"""

from __future__ import annotations

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from core.config import settings
from core.errors import ConfigurationError

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = Path(__file__).resolve().parent / "token.json"


def main() -> None:
    """Run the browser-based OAuth flow and persist token.json."""
    client_id = settings.google_calendar_client_id
    client_secret = settings.google_calendar_client_secret
    if not client_id or not client_secret:
        raise ConfigurationError(
            "GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET must be set."
        )

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved Google Calendar credentials to {TOKEN_PATH}")


if __name__ == "__main__":
    main()
