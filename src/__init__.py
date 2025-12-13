"""
PolyMarket MCP Server - In-memory cache with background updates.

Core Components:
- PolyStorage: Singleton with in-memory cache and background daemon
- PolyEvent/PolyMarket: Pydantic models for data
- PolyApiClient: Minimal API client returning raw JSON
- MCP Tools: FastMCP tool definitions for LLM agents
"""

from src.poly_objects import PolyEvent, PolyMarket, Outcome
from src.poly_storage import PolyStorage

__all__ = [
    "PolyEvent",
    "PolyMarket",
    "Outcome",
    "PolyStorage",
]

