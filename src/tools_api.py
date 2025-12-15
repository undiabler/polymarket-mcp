"""
REST API routes for Polymarket MCP Server.

These endpoints provide REST API access to the same functionality
exposed via MCP tools, for environments without MCP support.
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.poly_storage import PolyStorage

security = HTTPBearer()


def verify_bearer_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Validate Bearer token from Authorization header."""
    expected_token = os.getenv("MCP_BEARER_TOKEN")
    if not expected_token:
        raise HTTPException(status_code=500, detail="MCP_BEARER_TOKEN not set")
    if credentials.credentials != expected_token:
        raise HTTPException(status_code=401, detail="Invalid token")
    return credentials.credentials

router = APIRouter()
# router = APIRouter(dependencies=[Depends(verify_bearer_token)])

@router.get("/global_stats")
def global_stats_api() -> dict:
    """
    REST API wrapper for global_stats MCP tool.

    Returns total active events, markets, liquidity distribution, and liquidity balance.
    """
    return PolyStorage.get_instance().get_decorated_statistics()

@router.get("/event/{event_id}")
def get_event_api(event_id: str) -> dict:
    """
    Alternative REST API endpoint for retrieving a specific event by event_id.

    Args:
        event_id (str): The ID of the event to retrieve.

    Returns:
        dict: Decorated event data.
    """
    return PolyStorage.get_instance().get_decorated_event(event_id)

