"""
Singleton storage with in-memory cache and background daemon.

Core component of polymarket-mcp:
- Loads all events from disk into memory at startup
- Runs background daemon for updates (incremental fetch, refresh stale, cleanup expired)
- Provides query methods for MCP tools
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.poly_api import PolyApiClient
from src.poly_objects import PolyEvent, PolyMarket, Outcome
from src.tools import format_currency, ensure_utc, parse_datetime


# Daemon configuration
DAEMON_CONFIG = {
    "cycle_interval": 300,  # 5 minutes between cycles
    "stale_threshold": 3600,  # Refresh if older than 1 hour
    "expired_threshold": 604800,  # Remove if expired > 7 days
    "rate_limit_delay": 0.1,  # Delay between API requests
}


@dataclass
class DaemonStats:
    """Statistics from a daemon cycle."""

    events_fetched: int = 0
    events_refreshed: int = 0
    events_removed: int = 0
    errors: List[str] = None  # type: ignore

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class PolyStorage:
    """
    Singleton storage with in-memory cache and background daemon.

    Lifecycle:
    1. __init__() - Create instance, set paths
    2. start() - Load disk → memory, start daemon
    3. stop() - Stop daemon, flush state to disk

    Query methods are synchronous (read from memory).
    """

    _instance: Optional["PolyStorage"] = None

    def __init__(
        self,
        data_dir: str = "data",
        daemon_config: Optional[dict] = None,
    ):
        """
        Initialize storage (but don't load data yet).

        Args:
            data_dir: Base directory for data storage
            daemon_config: Optional daemon configuration override
        """
        self._data_dir = Path(data_dir)
        self._events_dir = self._data_dir / "events"
        self._state_file = self._data_dir / "state.json"

        # Ensure directories exist
        self._events_dir.mkdir(parents=True, exist_ok=True)

        # Daemon config
        self._config = {**DAEMON_CONFIG, **(daemon_config or {})}

        # In-memory cache
        self._events: Dict[str, PolyEvent] = {}
        self._raw_cache: Dict[str, dict] = {}  # For disk sync

        # State
        self._watermark: int = 0
        self._last_sync: Optional[datetime] = None
        self._started: bool = False
        self._daemon_task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls, **kwargs) -> "PolyStorage":
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None

    # === Lifecycle Methods ===

    async def start(self) -> None:
        """
        Start the storage system.

        1. Load state from disk
        2. Load all events from disk into memory
        3. Start background daemon
        """
        if self._started:
            return

        # Load state
        await self._load_state()

        # Load all events from disk
        await self._load_from_disk()

        # Start daemon
        self._daemon_task = asyncio.create_task(self._daemon_loop())

        self._started = True
        print(
            f"PolyStorage started: {len(self._events)} events loaded, watermark={self._watermark}"
        )

    async def stop(self) -> None:
        """
        Stop the storage system.

        1. Stop daemon
        2. Save state to disk
        """
        if not self._started:
            return

        # Stop daemon
        if self._daemon_task:
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass
            self._daemon_task = None

        # Save state
        await self._save_state()

        self._started = False
        print("PolyStorage stopped")

    # === Query Methods (for MCP tools) ===

    def get_all_events(self) -> List[PolyEvent]:
        """Get all cached events."""
        return list(self._events.values())

    def get_all_markets(self) -> List[PolyMarket]:
        """Get all markets flattened from all events."""
        markets: List[PolyMarket] = []
        for event in self._events.values():
            markets.extend(event.markets)
        return markets

    def get_event(self, event_id: str) -> Optional[PolyEvent]:
        """Get single event by ID."""
        return self._events.get(event_id)

    def filter_events(self, filter_fn: Callable[[PolyEvent], bool]) -> List[PolyEvent]:
        """Filter events using a custom function."""
        return [e for e in self._events.values() if filter_fn(e)]

    def filter_markets(
        self, filter_fn: Callable[[PolyMarket], bool]
    ) -> List[PolyMarket]:
        """Filter markets using a custom function."""
        markets = self.get_all_markets()
        return [m for m in markets if filter_fn(m)]

    def get_decorated_event(self, event_id: str) -> dict:
        result = {
            "event_id": event_id,
            "title": "N/A",
            "description": "N/A",
            "active": False,
        }
        event = self.get_event(event_id)
        if not event:
            return result

        result["title"] = event.title
        result["description"] = event.description
        result["active"] = event.active and not event.closed and not event.archived

        result["liquidity"] = event.liquidity
        result["tags"] = event.tags
        
        markets = event.get_markets()
        markets_data = []
        for market in markets:
            if not market.is_active():
                continue
            market_tmp={
                "market_id": market.market_id,
                "question": market.question,
                "expiry": market.expiry.isoformat() if market.expiry else None,
                "liquidity": f"${market.total_liquidity:.2f}",
                "liquidity_percentage": f"{market.total_liquidity / event.liquidity * 100:.2f}%" if event.liquidity > 0 else "0.00%",
                "outcomes": [{"name": o.name, "probability": f"{100*o.price:.2f}%",} for o in market.outcomes],
            }
            if market.title:
                market_tmp["title"] = market.title
            if market.description!=event.description:
                market_tmp["description"] = market.description
            markets_data.append(market_tmp)

        result["markets"] = markets_data
        result["last_sync"] = self._last_sync.isoformat() if self._last_sync else None
        return result

    def get_decorated_statistics(self) -> dict:
        """Get current cache statistics including liquidity distribution and strategy totals."""
        markets = self.get_all_markets()
        active_events = [e for e in self._events.values() if e.is_active()]
        active_markets = [m for m in markets if m.is_active()]

        num_active_events = len(active_events)
        num_active_markets = len(active_markets)
        avg_markets_per_event = num_active_markets / num_active_events if num_active_events > 0 else 0
        total_liquidity = sum(m.total_liquidity for m in active_markets)

        # Calculate liquidity distribution
        bucket_bounds = [100_000, 50_000, 10_000, 5_000]
        bucket_labels = ["$100K+", "$50K-$100K", "$10K-$50K", "$5K-$10K", "<$5K"]
        liquidity_distribution = {label: {"count": 0, "liquidity": 0.0} for label in bucket_labels}

        for market in active_markets:
            liquidity = market.total_liquidity
            if liquidity >= bucket_bounds[0]:
                label = bucket_labels[0]
            elif liquidity >= bucket_bounds[1]:
                label = bucket_labels[1]
            elif liquidity >= bucket_bounds[2]:
                label = bucket_labels[2]
            elif liquidity >= bucket_bounds[3]:
                label = bucket_labels[3]
            else:
                label = bucket_labels[4]

            liquidity_distribution[label]["count"] += 1
            liquidity_distribution[label]["liquidity"] += liquidity

        for label, ld in liquidity_distribution.items():
            liquidity_distribution[label]["liquidity_percentage"] = f"{ld['liquidity'] / total_liquidity * 100:.3f}%" if total_liquidity > 0 else "0.000%"
            liquidity_distribution[label]["count_percentage"] = f"{ld['count'] / num_active_markets * 100:.3f}%" if num_active_markets > 0 else "0.000%"
            liquidity_distribution[label]["liquidity"] = format_currency(ld['liquidity'])

        # Calculate strategy totals (hunted/hunters)
        hunted = 0.0
        hunters = 0.0

        for market in active_markets:
            dominant = market.dominant_outcome
            if market.total_liquidity <= 0 or not dominant:
                continue

            if dominant.price >= 0.90:
                hunted += market.total_liquidity * (1 - dominant.price)
                hunters += market.total_liquidity * dominant.price

        liquidity_balance = {
            "hunted_liquidity": format_currency(hunted),
            "hunters_liquidity": format_currency(hunters),
            "hunted_percentage": f"{hunted / (hunted + hunters) * 100:.3f}%" if hunted + hunters > 0 else "0.000%",
        }

        return {
            "active_events": num_active_events,
            "active_markets": num_active_markets,
            "avg_markets_per_event": f"{avg_markets_per_event:.3f}" if avg_markets_per_event > 0 else "0.000",
            "liquidity_total": format_currency(total_liquidity),
            "liquidity_buckets": liquidity_distribution,
            "liquidity_balance": liquidity_balance,
            "last_sync": self._last_sync.isoformat() if self._last_sync else None,
        }

    # === Daemon Methods ===

    async def _daemon_loop(self) -> None:
        """Background daemon loop."""
        while True:
            try:
                # Run full cycle
                stats = await self._run_daemon_cycle()
                print(
                    f"Daemon cycle: fetched={stats.events_fetched}, "
                    f"refreshed={stats.events_refreshed}, "
                    f"removed={stats.events_removed}"
                )

                # Wait for next cycle
                await asyncio.sleep(self._config["cycle_interval"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Daemon error: {e}")
                await asyncio.sleep(60)  # Wait before retry

    async def _run_daemon_cycle(self) -> DaemonStats:
        """Run a complete daemon cycle."""
        stats = DaemonStats()

        # 1. Incremental fetch new events
        try:
            fetched = await self._fetch_incremental()
            stats.events_fetched = fetched
        except Exception as e:
            stats.errors.append(f"Incremental fetch: {e}")

        # 2. Refresh stale events
        try:
            refreshed = await self._refresh_stale(
                timedelta(seconds=self._config["stale_threshold"])
            )
            stats.events_refreshed = refreshed
        except Exception as e:
            stats.errors.append(f"Refresh stale: {e}")

        # 3. Cleanup expired events
        try:
            removed = await self._cleanup_expired(
                timedelta(seconds=self._config["expired_threshold"])
            )
            stats.events_removed = removed
        except Exception as e:
            stats.errors.append(f"Cleanup expired: {e}")

        self._last_sync = datetime.now(timezone.utc)
        await self._save_state()

        return stats

    async def _fetch_incremental(self) -> int:
        """Fetch new events since watermark."""
        async with PolyApiClient(
            rate_limit_delay=self._config["rate_limit_delay"]
        ) as client:
            raw_events = await client.fetch_events(
                min_event_id=self._watermark if self._watermark > 0 else None,
                active=True,
                closed=False,
            )

        if not raw_events:
            return 0

        count = 0
        for raw in raw_events:
            event = self._parse_raw_to_event(raw)
            if event:
                self._events[event.id] = event
                self._raw_cache[event.id] = raw
                await self._save_event(event.id)
                count += 1

                # Update watermark
                try:
                    event_id = int(event.id)
                    if event_id > self._watermark:
                        self._watermark = event_id
                except ValueError:
                    pass

        return count

    async def _refresh_stale(self, max_age: timedelta) -> int:
        """Refresh events older than max_age."""
        now = datetime.now(timezone.utc)
        stale_ids = [
            event_id
            for event_id, event in self._events.items()
            if event.needs_update(max_age) and event.is_active()
        ]

        if not stale_ids:
            return 0

        count = 0
        async with PolyApiClient(
            rate_limit_delay=self._config["rate_limit_delay"]
        ) as client:
            for event_id in stale_ids:
                raw = await client.fetch_event(event_id)
                if raw:
                    event = self._parse_raw_to_event(raw)
                    if event:
                        self._events[event_id] = event
                        self._raw_cache[event_id] = raw
                        await self._save_event(event_id)
                        count += 1

        return count

    async def _cleanup_expired(self, expired_for: timedelta) -> int:
        """Remove events that have been expired for longer than duration."""
        now = datetime.now(timezone.utc)
        to_delete: List[str] = []

        for event_id, event in self._events.items():
            if event.end_date:
                expired_duration = now - ensure_utc(event.end_date)
                if expired_duration > expired_for:
                    to_delete.append(event_id)

        for event_id in to_delete:
            del self._events[event_id]
            self._raw_cache.pop(event_id, None)
            await self._delete_event_file(event_id)

        return len(to_delete)

    # === Parsing Methods ===

    def _parse_raw_to_event(self, raw: dict) -> Optional[PolyEvent]:
        """Parse raw API response to PolyEvent."""
        try:
            event_id = raw.get("id")
            slug = raw.get("slug")

            if not event_id or not slug:
                return None

            # Parse markets
            markets: List[PolyMarket] = []
            markets_data = raw.get("markets", [])

            # Extract event tags
            raw_tags = raw.get("tags", [])
            event_tags = []
            for tag in raw_tags:
                if isinstance(tag, str):
                    event_tags.append(tag)
                elif isinstance(tag, dict) and "label" in tag:
                    event_tags.append(tag["label"])

            # Extract series info
            series_title = None
            series_slug = None
            series_data = raw.get("series", [])
            if series_data and isinstance(series_data, list) and len(series_data) > 0:
                first_series = series_data[0]
                if isinstance(first_series, dict):
                    series_title = first_series.get("title")
                    series_slug = first_series.get("slug")

            for market_data in markets_data:
                if isinstance(market_data, dict):
                    market = self._parse_market(
                        market_data,
                        str(event_id),
                        event_tags,
                        series_title,
                        series_slug,
                    )
                    if market:
                        markets.append(market)

            return PolyEvent(
                id=str(event_id),
                slug=slug,
                title=raw.get("title"),
                description=raw.get("description"),
                end_date=parse_datetime(raw.get("endDate")),
                active=raw.get("active", True),
                closed=raw.get("closed", False),
                archived=raw.get("archived", False),
                liquidity=float(raw.get("liquidity", 0) or 0),
                volume=float(raw.get("volume", 0) or 0),
                tags=event_tags,
                series_title=series_title,
                series_slug=series_slug,
                markets=markets,
                last_sync_time=datetime.now(timezone.utc),
            )

        except Exception as e:
            print(f"Error parsing event: {e}")
            return None

    def _parse_market(
        self,
        market_data: dict,
        event_id: str,
        event_tags: List[str],
        series_title: Optional[str],
        series_slug: Optional[str],
    ) -> Optional[PolyMarket]:
        """Parse market data from event response."""
        try:
            market_id = market_data.get("id")
            condition_id = market_data.get("conditionId")
            slug = market_data.get("slug", "")
            question = market_data.get("question", "")
            title_raw = market_data.get("groupItemTitle", "")
            title = title_raw if len(title_raw)>0 else None
            
            if not market_id or not condition_id or not slug or not question:
                return None

            # Parse expiry
            expiry = parse_datetime(market_data.get("endDate"))
            if not expiry:
                expiry = datetime.now(timezone.utc)

            # Calculate total liquidity
            liquidity_amm = float(market_data.get("liquidityAmm", 0) or 0)
            liquidity_clob = float(market_data.get("liquidityClob", 0) or 0)
            total_liquidity = liquidity_amm + liquidity_clob

            # Parse outcomes
            outcomes = self._parse_outcomes(market_data, total_liquidity)
            if not outcomes:
                return None

            return PolyMarket(
                market_id=str(market_id),
                condition_id=condition_id,
                event_id=event_id,
                slug=slug,
                question=question,
                title=title,
                description=market_data.get("description"),
                expiry=expiry,
                outcomes=outcomes,
                total_liquidity=total_liquidity,
                tags=event_tags,
                series_title=series_title,
                series_slug=series_slug,
                active=market_data.get("active", True),
                closed=market_data.get("closed", False),
                archived=market_data.get("archived", False),
            )

        except Exception as e:
            print(f"Error parsing market: {e}")
            return None

    def _parse_outcomes(
        self, market_data: dict, total_liquidity: float
    ) -> Optional[List[Outcome]]:
        """Parse outcomes from market data."""
        # Parse clobTokenIds first - required
        clob_token_ids_raw = market_data.get("clobTokenIds")
        if not clob_token_ids_raw:
            return None

        clob_token_ids = []
        if isinstance(clob_token_ids_raw, str):
            try:
                clob_token_ids = json.loads(clob_token_ids_raw)
            except Exception:
                return None
        elif isinstance(clob_token_ids_raw, list):
            clob_token_ids = clob_token_ids_raw
        else:
            return None

        if not clob_token_ids:
            return None

        outcomes_raw = market_data.get("outcomes", [])
        if isinstance(outcomes_raw, str):
            try:
                outcomes_raw = json.loads(outcomes_raw)
            except Exception:
                outcomes_raw = []

        # Get outcome prices
        outcome_prices_str = market_data.get("outcomePrices", "")
        if isinstance(outcome_prices_str, str):
            try:
                outcome_prices = json.loads(outcome_prices_str)
            except Exception:
                outcome_prices = []
        else:
            outcome_prices = outcome_prices_str if outcome_prices_str else []

        outcomes: List[Outcome] = []

        # Handle binary Yes/No markets
        if (
            len(outcomes_raw) == 2
            and "Yes" in outcomes_raw
            and "No" in outcomes_raw
            and len(outcome_prices) >= 2
            and len(clob_token_ids) >= 2
        ):
            try:
                yes_price = float(outcome_prices[0])
                no_price = float(outcome_prices[1])

                yes_liquidity = total_liquidity * yes_price if total_liquidity > 0 else 0
                no_liquidity = total_liquidity * no_price if total_liquidity > 0 else 0

                outcomes.append(
                    Outcome(
                        name="Yes",
                        price=yes_price,
                        liquidity=yes_liquidity,
                        token_id=clob_token_ids[0],
                    )
                )
                outcomes.append(
                    Outcome(
                        name="No",
                        price=no_price,
                        liquidity=no_liquidity,
                        token_id=clob_token_ids[1],
                    )
                )
                return outcomes
            except (ValueError, TypeError, IndexError):
                pass

        # Handle multi-outcome markets
        if (
            outcomes_raw
            and len(outcome_prices) == len(outcomes_raw)
            and len(clob_token_ids) >= len(outcomes_raw)
        ):
            for i, name in enumerate(outcomes_raw):
                if isinstance(name, str):
                    try:
                        price = float(outcome_prices[i])
                        liquidity = total_liquidity * price if total_liquidity > 0 else 0
                        outcomes.append(
                            Outcome(
                                name=name,
                                price=price,
                                liquidity=liquidity,
                                token_id=clob_token_ids[i],
                            )
                        )
                    except (ValueError, TypeError, IndexError):
                        continue

        return outcomes if outcomes else None

    # === Disk I/O Methods ===

    async def _load_state(self) -> None:
        """Load state from disk."""
        if self._state_file.exists():
            try:
                with open(self._state_file, "r") as f:
                    state = json.load(f)
                self._watermark = state.get("watermark", 0)
                last_sync = state.get("last_sync")
                if last_sync:
                    self._last_sync = datetime.fromisoformat(last_sync)
            except Exception as e:
                print(f"Error loading state: {e}")

    async def _save_state(self) -> None:
        """Save state to disk."""
        state = {
            "watermark": self._watermark,
            "last_sync": self._last_sync.isoformat() if self._last_sync else None,
        }

        temp_path = self._state_file.with_suffix(".tmp")
        try:
            with open(temp_path, "w") as f:
                json.dump(state, f, indent=2)
            temp_path.replace(self._state_file)
        except Exception as e:
            print(f"Error saving state: {e}")
            if temp_path.exists():
                temp_path.unlink()

    async def _load_from_disk(self) -> None:
        """Load all events from disk into memory."""
        for path in self._events_dir.glob("*.json"):
            try:
                with open(path, "r") as f:
                    stored = json.load(f)

                # Handle both old format (direct) and new format (with meta)
                if "raw" in stored and "meta" in stored:
                    raw = stored["raw"]
                else:
                    raw = stored

                event = self._parse_raw_to_event(raw)
                if event:
                    self._events[event.id] = event
                    self._raw_cache[event.id] = raw

            except Exception as e:
                print(f"Error loading event from {path}: {e}")

    async def _save_event(self, event_id: str) -> None:
        """Save single event to disk."""
        raw = self._raw_cache.get(event_id)
        if not raw:
            return

        # Store with metadata wrapper
        stored = {
            "raw": raw,
            "meta": {
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "version": 1,
            },
        }

        path = self._events_dir / f"{event_id}.json"
        temp_path = path.with_suffix(".tmp")

        try:
            with open(temp_path, "w") as f:
                json.dump(stored, f, indent=2, default=str)
            temp_path.replace(path)
        except Exception as e:
            print(f"Error saving event {event_id}: {e}")
            if temp_path.exists():
                temp_path.unlink()

    async def _delete_event_file(self, event_id: str) -> None:
        """Delete event file from disk."""
        path = self._events_dir / f"{event_id}.json"
        if path.exists():
            try:
                path.unlink()
            except Exception as e:
                print(f"Error deleting event file {event_id}: {e}")

