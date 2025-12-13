"""
REST API routes for Polymarket MCP Server.

These endpoints provide REST API access to the same functionality
exposed via MCP tools, for environments without MCP support.
"""

from fastapi import APIRouter

from src.poly_storage import PolyStorage

router = APIRouter()


@router.get("/global_stats")
def global_stats_api() -> dict:
    """
    REST API wrapper for global_stats MCP tool.

    Returns total active events, markets, liquidity distribution, and liquidity balance.
    """
    return PolyStorage.get_instance().get_decorated_statistics()

