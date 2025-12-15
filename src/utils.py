"""
Utility functions for Polymarket MCP.

Standalone helpers for formatting, datetime handling, and calculations.
"""

from datetime import datetime, timezone
from typing import Optional


def format_currency(value: float) -> str:
    """Format value as currency."""
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    elif value >= 1_000:
        return f"${value / 1_000:.2f}K"
    else:
        return f"${value:.0f}"

def format_currency_full(value: float) -> str:
    return f"${value:_.2f}"

def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def parse_datetime(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string with timezone handling."""
    if not date_str:
        return None
    try:
        if date_str.endswith("Z"):
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def calculate_compound_percentage(growth_rate: float, cycles: int) -> float:
    """
    Calculate compound growth percentage.

    Args:
        growth_rate: The growth rate per cycle (e.g. 0.05 for 5%)
        cycles: The number of cycles

    Returns:
        The compound growth as a decimal (e.g. 0.1576 for 15.76%)
    """
    return (1 + growth_rate) ** cycles - 1
