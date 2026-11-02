"""MongoDB Atlas adapter -- STUB, and the one integration where "stub"
might mean "you don't need this file at all." Most forks that want a
managed database instead of self-hosted Postgres should just point
`DATABASE_URL` at a managed Postgres instance (Atlas's own Postgres-
compatible or any RDS-style provider) -- that needs zero code changes,
only `.env`.

This `BaaSProvider` stub is for the smaller case: a fork that wants
Atlas's *extra* services beyond "a database" -- App Services
functions/triggers, Atlas Search, Device Sync -- callable from a Friday
app. Atlas's Admin API (https://www.mongodb.com/docs/atlas/
reference/api-resources-spec/) uses digest auth with a public/private API
key pair (`public_key`/`private_key` below). See INTEGRATIONS.md#atlas.
"""

from .base import BaaSProvider


class AtlasProvider(BaaSProvider):
    def __init__(self, config: dict):
        self.public_key = config["public_key"]
        self.private_key = config["private_key"]
        self.project_id = config["project_id"]

    async def health_check(self) -> dict:
        raise NotImplementedError("Atlas adapter is a stub -- see INTEGRATIONS.md#atlas and this file's docstring")
