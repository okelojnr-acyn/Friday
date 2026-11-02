"""Calendly adapter -- STUB. Not wired to a real API yet; this file is the
starting shape for a coding agent to finish, following `stripe.py` or
`slack.py` as the worked example of "real adapter against this same
interface."

To complete this: Calendly's API (https://developer.calendly.com) uses a
personal access token (`api_key` below) as a Bearer token.
`create_event` has no direct Calendly equivalent -- Calendly is
scheduling-link-driven, not create-event-driven, so the real
implementation is closer to "fetch or generate the org's booking link"
(`GET /scheduled_events` to list bookings, or returning a static
`event_type` link for the caller to share) than a literal event-creation
POST. Decide that shape before filling in the method body. See
INTEGRATIONS.md#calendly.
"""

from .base import CalendarProvider


class CalendlyProvider(CalendarProvider):
    def __init__(self, config: dict):
        self.api_key = config["api_key"]

    async def create_event(self, title: str, start_iso: str, end_iso: str, attendees: list[str]) -> dict:
        raise NotImplementedError(
            "Calendly adapter is a stub -- see INTEGRATIONS.md#calendly and this file's docstring"
        )
