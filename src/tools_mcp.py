"""
FastMCP tool definitions for Polymarket MCP Server.

These are thin wrappers around PolyStorage methods.
All business logic lives in PolyStorage.
"""

import os
from typing import Annotated, Optional

import mcp.types as mcp_types
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

from src.poly_storage import PolyStorage, MARKET_FILTERS, MARKET_SORTS
from src.poly_objects import PolyEvent
from src.utils import calculate_compound_percentage

# Create MCP server instance first (needed for middleware access)
mcp = FastMCP("Polymarket MCP Server")


class ArgumentSanitizerMiddleware(Middleware):
    """
    Strip extra/unknown fields from tool arguments before Pydantic validation.

    Some MCP clients (e.g., n8n) include metadata fields like 'tool', 'id', 'toolCallId'
    inside the arguments dict. FastMCP's strict Pydantic validation rejects these
    unexpected fields. This middleware filters arguments to only include parameters
    defined in the tool's JSON schema.
    """

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        message = context.message
        arguments = message.arguments or {}

        # Get the tool to access its parameter schema
        tools = await mcp._tool_manager.get_tools()
        tool = tools.get(message.name)

        if tool and arguments:
            # Get valid parameter names from the tool's JSON schema
            valid_params = set(tool.parameters.get("properties", {}).keys())
            # Filter to only include valid parameters, silently dropping extras
            cleaned_args = {k: v for k, v in arguments.items() if k in valid_params}

            # Create new message with cleaned arguments
            new_message = mcp_types.CallToolRequestParams(name=message.name, arguments=cleaned_args)
            context = context.copy(message=new_message)

        return await call_next(context)


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


# Register middlewares in order: sanitize args first, then authenticate
mcp.add_middleware(ArgumentSanitizerMiddleware())
mcp.add_middleware(BearerAuthMiddleware())

@mcp.tool()
def global_stats(
    with_bucket_analytics: Annotated[bool, "Include liquidity distribution across size tiers ($5K to $100K+)."] = False,
    with_hunted_analytics: Annotated[bool, "Include profit extraction metrics for high-confidence markets (>90% dominant outcome). Shows 'hunted' liquidity (minority bets likely to lose) vs 'hunters' (majority bets likely to win)."] = False,
) -> dict:
    """
    Get Polymarket platform overview: active events/markets count, total liquidity (USD), and last sync time.
    """
    return PolyStorage.get_instance().get_decorated_statistics(
        withBuckedAnalytics=with_bucket_analytics,
        withHuntedAnalytics=with_hunted_analytics,
    )

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