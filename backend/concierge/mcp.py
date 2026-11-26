"""The mock provider service: an MCP server, in a container of its own.

It stands for the slow external system that knows the providers. One tool, `search_providers`, waits `sleep_seconds` (a slow
service) and then answers with the best matches: providers with their open slots and why they fit. The research agent calls it
over MCP and forwards the answer (see research.py). The data is the seeded fictional catalogue, read-only.
"""

import asyncio
import json
import os
from datetime import date

from mcp.server.fastmcp import FastMCP

from concierge.config import DATABASE_URL
from concierge.domain import Database, PgAvailability, PgCatalog, SearchRequest, match_preferences

mcp = FastMCP("provider-service", host="0.0.0.0", port=int(os.environ.get("PORT", "8001")))


@mcp.tool()
async def search_providers(
    location: str, date_from: str, date_to: str, preferences: list[str] | None = None, sleep_seconds: float = 4
) -> str:
    """Search the physiotherapy providers for a location (a Munich neighbourhood, or 'Munich') and a date window (YYYY-MM-DD).
    `preferences` are short phrases such as 'back pain' or 'evening'. Slow: it takes `sleep_seconds`. Returns JSON: the best
    providers (at most 3, best first), each with its open slots and the reasons it fits."""
    await asyncio.sleep(min(max(sleep_seconds, 0), 20))  # the simulated slow service
    request = SearchRequest(
        location=location,
        date_from=date.fromisoformat(date_from),
        date_to=date.fromisoformat(date_to),
        preferences=preferences or [],
    )
    async with Database(DATABASE_URL) as db:
        catalog, availability = PgCatalog(db), PgAvailability(db)
        providers = await catalog.discover(request)
        found = []
        for provider in providers:
            slots = await availability.slots(provider.id, request.date_from, request.date_to)
            matched, concerns = match_preferences(provider, request.preferences)
            if slots and (matched or not request.preferences):  # a provider that meets none of the preferences is skipped
                found.append((len(concerns), -len(matched), provider.price_band, provider.id, provider, slots, matched))
    found.sort(key=lambda f: f[:4])  # fewest unmet preferences first, then most matches, then cheapest
    shortlist = [
        {
            "rank": rank,
            "provider": provider.model_dump(),
            "slots": [s.model_dump(mode="json") for s in slots[:3]],
            "reasons": [*matched, f"price band {provider.price_band} of 3"],
        }
        for rank, (_, _, _, _, provider, slots, matched) in enumerate(found[:3], start=1)
    ]
    return json.dumps({"considered": len(providers), "providers": shortlist})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
