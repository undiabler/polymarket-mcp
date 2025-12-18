"""
FastMCP tool definitions for Polymarket MCP Server.

These are thin wrappers around PolyStorage methods.
All business logic lives in PolyStorage.
"""

import os
from typing import Annotated, Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

from src.poly_storage import PolyStorage, MARKET_FILTERS, MARKET_SORTS
from src.poly_objects import PolyEvent
from src.utils import calculate_compound_percentage


class BearerAuthMiddleware(Middleware):
    """Validate Bearer token from Authorization header."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        headers = get_http_headers()
        auth_header = headers.get("authorization", "")

        expected_token = os.getenv("MCP_BEARER_TOKEN")
        if not expected_token:
            raise ToolError("Server misconfigured: MCP_BEARER_TOKEN not set")

        if not auth_header.startswith("Bearer "):
            raise ToolError("Unauthorized: Missing Bearer token")

        token = auth_header[7:]
        if token != expected_token:
            raise ToolError("Unauthorized: Invalid token")

        return await call_next(context)

mcp = FastMCP("Polymarket MCP Server")
mcp.add_middleware(BearerAuthMiddleware())

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
def query_events(
    filtername: Annotated[str, "Filter preset name. Available: default"] = "default",
    sortingname: Annotated[str, "Sort strategy. Available: profit, liquidity, expiry"] = "profit",
    limit: Annotated[int, "Maximum qualifying markets to consider"] = 50,
) -> list[dict]:
    """
    Query events containing markets matching named filter criteria.
    Use this tool for any type of top level market requests (e.g. "give me the top 10 markets by profit", "give me the top 50 markets by liquidity", "give me the top 5 markets by expiry", etc.).
    This implements "events first" approach: filters markets by predefined criteria,
    then extracts their parent events (deduplicated). Each event contains only
    its qualifying markets, sorted by the chosen strategy. For full list of markets, use get_event tool.

    Available filters: default
    Available sorts: profit, liquidity, expiry

    Returns:
        List of events with their qualifying markets
        Liquidity values are in USD, formatted with comma separators (e.g., '$24,156 is 24 thousand dollars and 156 dollars')
    """
    storage = PolyStorage.get_instance()

    # Get qualifying markets
    try:
        markets = storage.query_markets_for_events(filtername, sortingname, limit)
    except ValueError as e:
        return [{"error": str(e)}]

    # Group markets by event_id (preserving order)
    events_list = [] # preserver order of events
    events_map: dict[str, list] = {} # group markets by event_id
    for market in markets:
        if market.event_id not in events_list:
            events_list.append(market.event_id)
        if market.event_id not in events_map:
            events_map[market.event_id] = []
        events_map[market.event_id].append(market.market_id)

    # Build result with events containing their qualifying markets
    result = []
    for event_id in events_list:
        event = storage.get_event(event_id)
        if not event:
            continue

        event_data = storage.get_decorated_event(event_id, specific_markets=events_map[event_id])
        result.append(event_data)

    return result

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