"""
Pydantic data models for Polymarket events and markets.

Events-first design: Events are primary entities containing all market data.
These models are used in-memory only - raw JSON is stored on disk.
"""

from datetime import datetime, timezone, timedelta
from typing import Callable, List, Optional
from pydantic import BaseModel, Field

from src.tools import ensure_utc


class Outcome(BaseModel):
    """Represents a market outcome with liquidity data."""

    name: str
    price: float  # Current trading price (0-1)
    liquidity: float  # Outcome-specific liquidity in USDC
    token_id: str  # CLOB token ID - REQUIRED for trading

    @property
    def percentage(self) -> float:
        """Price as percentage (alias for consistency)."""
        return self.price


class PolyMarket(BaseModel):
    """
    Flattened market representation with event reference.

    Contains complete market data from events API with calculated fields
    for profit analysis.
    """

    market_id: str  # From "id" field
    condition_id: str  # From "conditionId" field - REQUIRED for position matching
    event_id: str  # Parent event reference
    slug: str
    question: str
    title: Optional[str] = None
    description: Optional[str] = None
    expiry: datetime
    outcomes: List[Outcome]
    total_liquidity: float
    tags: List[str] = Field(default_factory=list)
    series_title: Optional[str] = None
    series_slug: Optional[str] = None
    active: bool = True
    closed: bool = False
    archived: bool = False

    def model_post_init(self, __context):
        """Ensure expiry is timezone-aware (UTC)."""
        if self.expiry.tzinfo is None:
            object.__setattr__(self, "expiry", self.expiry.replace(tzinfo=timezone.utc))

    @property
    def dominant_outcome(self) -> Optional[Outcome]:
        """Get the outcome with highest price/probability."""
        if not self.outcomes:
            return None
        return max(self.outcomes, key=lambda o: o.price)

    @property
    def opposing_liquidity(self) -> float:
        """Get liquidity of non-dominant outcomes."""
        dominant = self.dominant_outcome
        if not dominant:
            return 0.0
        return sum(o.liquidity for o in self.outcomes if o.name != dominant.name)

    def profit_percentages(self, investment: float = 1000.0) -> tuple[float, float]:
        """
        Calculate profit percentages for this market.

        Returns:
            Tuple of (total_profit_percentage, profit_per_hour)
        """
        if self.total_liquidity <= 0 or investment <= 0:
            return (0.0, 0.0)

        # Calculate profit based on liquidity share capture
        dominant = self.dominant_outcome
        if not dominant:
            return (0.0, 0.0)

        opposing = self.opposing_liquidity
        new_total = self.total_liquidity + investment
        our_share = investment / new_total
        capturable = opposing * our_share
        total_profit = capturable / investment if investment > 0 else 0.0

        # Calculate hours remaining
        now = datetime.now(timezone.utc)
        expiry = ensure_utc(self.expiry)
        hours_remaining = max(1, (expiry - now).total_seconds() / 3600)
        profit_per_hour = total_profit / hours_remaining

        return (total_profit, profit_per_hour)

    def is_active(self) -> bool:
        """Check if market is still tradeable."""
        if self.closed or self.archived or not self.active:
            return False

        now = datetime.now(timezone.utc)
        expiry = ensure_utc(self.expiry)
        return expiry > now and self.total_liquidity > 0

    def hours_remaining(self) -> float:
        """Get hours until market expiry."""
        now = datetime.now(timezone.utc)
        expiry = ensure_utc(self.expiry)
        return max(0, (expiry - now).total_seconds() / 3600)


class PolyEvent(BaseModel):
    """
    Event-centric data model containing all market data.

    Foundation-level filtering: active, tradable, not expired.
    """

    id: str
    slug: str
    title: Optional[str] = None
    description: Optional[str] = None
    end_date: Optional[datetime] = None
    active: bool = True
    closed: bool = False
    archived: bool = False
    liquidity: float = 0.0
    volume: float = 0.0
    tags: List[str] = Field(default_factory=list)
    series_title: Optional[str] = None
    series_slug: Optional[str] = None
    markets: List[PolyMarket] = Field(default_factory=list)

    # Sync tracking
    last_sync_time: Optional[datetime] = None

    def model_post_init(self, __context):
        """Ensure end_date is timezone-aware (UTC)."""
        if self.end_date and self.end_date.tzinfo is None:
            object.__setattr__(
                self, "end_date", self.end_date.replace(tzinfo=timezone.utc)
            )

    def get_markets(
        self, filter_fn: Optional[Callable[[PolyMarket], bool]] = None
    ) -> List[PolyMarket]:
        """
        Get markets with optional filtering.

        Args:
            filter_fn: Optional filter function for markets

        Returns:
            List of markets (filtered if filter_fn provided)
        """
        if filter_fn is None:
            return self.markets
        return [m for m in self.markets if filter_fn(m)]

    def is_expiring_in(self, duration: timedelta) -> bool:
        """
        Check if event expires within the given duration.

        Args:
            duration: Time window to check

        Returns:
            True if event expires within duration from now
        """
        if not self.end_date:
            return False

        now = datetime.now(timezone.utc)
        end = ensure_utc(self.end_date)
        time_until = end - now

        return timedelta(0) <= time_until <= duration

    def is_active(self) -> bool:
        """Check if event is still active and tradeable."""
        if self.closed or self.archived or not self.active:
            return False

        if self.end_date:
            now = datetime.now(timezone.utc)
            return ensure_utc(self.end_date) > now

        return True

    def needs_update(self, duration: timedelta) -> bool:
        """
        Check if event data is stale and needs refresh.

        Args:
            duration: Maximum age before considering stale

        Returns:
            True if last sync is older than duration
        """
        if not self.last_sync_time:
            return True

        now = datetime.now(timezone.utc)
        age = now - ensure_utc(self.last_sync_time)
        return age >= duration

    def get_url(self) -> str:
        """Get Polymarket URL for this event."""
        return f"https://polymarket.com/event/{self.slug}"

    def hours_remaining(self) -> float:
        """Get hours until event expiry."""
        if not self.end_date:
            return float("inf")
        now = datetime.now(timezone.utc)
        return max(0, (ensure_utc(self.end_date) - now).total_seconds() / 3600)

    @property
    def total_market_liquidity(self) -> float:
        """Sum of all market liquidity in this event."""
        return sum(m.total_liquidity for m in self.markets)

