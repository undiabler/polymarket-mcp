"""
FastMCP tool definitions for Polymarket MCP Server.

These are thin wrappers around PolyStorage methods.
All business logic lives in PolyStorage.
"""

from contextlib import asynccontextmanager
from typing import Optional
from fastmcp import FastMCP

from src.poly_storage import PolyStorage
from src.poly_objects import PolyEvent
from src.tools import calculate_compound_percentage


@asynccontextmanager
async def lifespan(app):
    """
    Lifespan context manager for FastMCP.

    Handles async startup and shutdown of PolyStorage.
    """
    storage = PolyStorage.get_instance()

    # Startup: load data and start daemon
    await storage.start()

    try:
        yield
    finally:
        # Shutdown: stop daemon gracefully
        await storage.stop()
        print("Server stopped.")


mcp = FastMCP("Polymarket MCP Server", lifespan=lifespan)


@mcp.tool()
def global_stats() -> dict:
    """
    Get current global statistics from Polymarket.

    Returns total active events, markets betting on these events, liquidity distribution (seperated by buckets), and liquidity balance (hunted/hunters).
    Calculation of liquidity balance is based on the assumption that the dominant outcome (>90%) is hunters and the rest is hunted (will be absorbed by hunters).
    Hunted percentage than is a realistic average profit percentage left to be extracted from the market.
    """
    return PolyStorage.get_instance().get_decorated_statistics()

@mcp.tool()
def compound_percentage(growth_percentage: float, cycles: int) -> str:
    """
    Calculate compound percentage over number of cycles based on growth percentage per cycle.
    Usefull tool to calculate average profit percentage left to be extracted from the market over time over multiple cycles of iterations (compound interest formula).

    Args:
        growth_percentage: The percentage of growth per cycle (e.g. 0.05 for 5%)
        cycles: The number of cycles to calculate

    Returns:
        The compound percentage as a string (except initial capital), this metric can be interpreted as total ROI (return on investment) of some initial capital over the given number of cycles.
    """
    result = calculate_compound_percentage(growth_percentage, cycles)
    return f"{result * 100:.3f}%"


@mcp.tool()
def search_events(
    min_liquidity: float = 0,
    max_hours_until_expiry: Optional[int] = None,
    tags: Optional[list[str]] = None,
    search_query: Optional[str] = None,
    active_only: bool = True,
    limit: int = 50,
) -> list[dict]:
    """
    Search events with filters.

    Args:
        min_liquidity: Minimum event liquidity in USDC
        max_hours_until_expiry: Only events expiring within this many hours
        tags: Filter by tags (any match)
        search_query: Search in title/slug (case-insensitive)
        active_only: Only return active events
        limit: Maximum number of results

    Returns:
        List of matching events as dicts
    """
    storage = PolyStorage.get_instance()

    def filter_fn(e: PolyEvent) -> bool:
        if active_only and not e.is_active():
            return False
        if e.liquidity < min_liquidity:
            return False
        if tags and not any(t.lower() in [et.lower() for et in e.tags] for t in tags):
            return False
        if search_query:
            query_lower = search_query.lower()
            if query_lower not in (e.title or "").lower() and query_lower not in e.slug.lower():
                return False
        if max_hours_until_expiry is not None and e.end_date:
            if e.hours_remaining() > max_hours_until_expiry:
                return False
        return True

    events = storage.filter_events(filter_fn)

    # Sort by liquidity descending
    events.sort(key=lambda e: e.liquidity, reverse=True)

    return [e.model_dump(mode="json") for e in events[:limit]]


@mcp.tool()
def get_event(event_id: str) -> dict:
    """
    Get Polymarket's Event (something we can bet on) by ID.

    Event contains title (general question), description, active status, liquidity, tags, and markets (options we can bet on).
    Markets contain id, question, expiry, liquidity, liquidity percentage (for events with multiple choices), outcomes with name and probability (current market expectations).

    Args:
        event_id: The event ID to fetch

    Returns:
        Event as dict
    """
    return PolyStorage.get_instance().get_decorated_event(event_id)


# @mcp.custom_route("/api/get_event", methods=["GET"])
# async def get_event_api(request: Request) -> PlainTextResponse:
#     return get_event(request.query_params.get("event_id"))