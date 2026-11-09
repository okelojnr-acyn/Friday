"""Google Calendar adapter -- code-ready. Needs `client_id`,
`client_secret`, and `refresh_token` in the org's stored config (Settings
-> Integrations -> Google Calendar); the refresh_token is obtained
through the real OAuth2 consent flow this now has
(`kernel/internal/integrations/google_oauth.go`'s `GoogleOAuthStart`/
`GoogleOAuthCallback`), not pasted in by hand -- same
bring-your-own-credentials posture as Stripe/Slack, just with an extra
step to get the one field that can't be a plain static key. See
INTEGRATIONS.md#google-calendar for the admin-facing side of this.

Talks to Google's REST API directly over `httpx` rather than any Google
API client library, consistent with this package's "no dependency we
don't need" posture (see `stripe.py`). `create_event` refreshes a short-
lived access token from the stored refresh_token on every call -- Google
access tokens are ~1hr, there's no caching layer here worth the
complexity for how infrequently Minions will call this.
"""

import httpx

from .base import CalendarProvider

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class GoogleCalendarProvider(CalendarProvider):
    def __init__(self, config: dict):
        self.client_id = config["client_id"]
        self.client_secret = config["client_secret"]
        self.refresh_token = config["refresh_token"]

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    async def create_event(self, title: str, start_iso: str, end_iso: str, attendees: list[str]) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            access_token = await self._access_token(client)
            resp = await client.post(
                GOOGLE_EVENTS_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "summary": title,
                    "start": {"dateTime": start_iso},
                    "end": {"dateTime": end_iso},
                    "attendees": [{"email": email} for email in attendees],
                },
            )
            resp.raise_for_status()
            return resp.json()
