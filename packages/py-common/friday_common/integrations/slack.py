"""Slack adapter -- code-ready, incoming-webhook based (no bot token, no
OAuth install flow, no scopes to request). Needs a `webhook_url` in the
org's stored config (Settings -> Integrations -> Slack): create one at
https://api.slack.com/apps -> an app -> "Incoming Webhooks" -> add a
webhook for a channel. See INTEGRATIONS.md#slack.
"""

import httpx

from .base import ChatProvider


class SlackProvider(ChatProvider):
    def __init__(self, config: dict):
        self.webhook_url = config["webhook_url"]

    async def notify(self, text: str) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(self.webhook_url, json={"text": text})
            resp.raise_for_status()
