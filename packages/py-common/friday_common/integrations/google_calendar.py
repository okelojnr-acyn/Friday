"""Google Calendar adapter -- STUB. Follow `stripe.py`/`slack.py` as the
worked example of a real adapter against this interface.

To complete this: Google Calendar needs OAuth2 (not a static API key) --
the org's stored config should hold a refresh token obtained through
Google's OAuth consent flow (`https://developers.google.com/calendar/api/
quickstart/python`), not a plain secret. `create_event` becomes a
`POST https://www.googleapis.com/calendar/v3/calendars/{id}/events`,
authorized with an access token refreshed from the stored refresh token.
The OAuth consent screen + callback route this needs doesn't exist in the
web shell yet -- that's the first thing to add, not just this adapter.
See INTEGRATIONS.md#google-calendar.
"""

from .base import CalendarProvider


class GoogleCalendarProvider(CalendarProvider):
    def __init__(self, config: dict):
        self.refresh_token = config["refresh_token"]
        self.client_id = config["client_id"]
        self.client_secret = config["client_secret"]

    async def create_event(self, title: str, start_iso: str, end_iso: str, attendees: list[str]) -> dict:
        raise NotImplementedError(
            "Google Calendar adapter is a stub -- see INTEGRATIONS.md#google-calendar and this file's docstring"
        )
