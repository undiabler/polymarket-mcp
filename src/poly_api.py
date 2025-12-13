"""
Minimal API client for Polymarket Gamma API.

Returns raw JSON dicts from API - parsing to Pydantic is done elsewhere.
Only 2 methods: fetch_events and fetch_event.
"""

import asyncio
import httpx
from typing import List, Optional


class PolyApiClient:
    """
    Minimal API client for Polymarket Gamma API.

    Data Strategy: Returns raw JSON dicts. Parsing to Pydantic models
    is handled by PolyStorage when loading into memory.
    """

    BASE_URL = "https://gamma-api.polymarket.com"

    def __init__(self, rate_limit_delay: float = 0.1):
        """
        Initialize the API client.

        Args:
            rate_limit_delay: Delay between requests in seconds
        """
        self.rate_limit_delay = rate_limit_delay
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def fetch_events(
        self,
        min_event_id: Optional[int] = None,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        max_events: Optional[int] = None,
    ) -> List[dict]:
        """
        Fetch events with embedded market data from Polymarket Gamma API.

        Returns raw JSON dicts - no parsing to Pydantic models.

        Args:
            min_event_id: Only fetch events with ID > this value (incremental)
            active: Filter for active events
            closed: Filter for closed events
            limit: Number of events per request
            max_events: Maximum total events to fetch

        Returns:
            List of raw event dicts from API
        """
        client = await self._get_client()
        all_events: List[dict] = []
        offset = 0

        while True:
            if max_events and len(all_events) >= max_events:
                break

            params = {
                "limit": limit,
                "offset": offset,
                "active": str(active).lower(),
                "closed": str(closed).lower(),
            }

            try:
                response = await client.get(f"{self.BASE_URL}/events", params=params)
                response.raise_for_status()
                data = response.json()

                if not data:
                    break

                # Filter by min_event_id if specified, but keep raw data
                for event_data in data:
                    if not isinstance(event_data, dict):
                        continue

                    # Validate minimum required fields
                    event_id_str = event_data.get("id")
                    slug = event_data.get("slug")
                    if not event_id_str or not slug:
                        continue

                    # Filter by min_event_id if specified
                    if min_event_id is not None:
                        try:
                            event_id = int(event_id_str)
                            if event_id <= min_event_id:
                                continue
                        except (ValueError, TypeError):
                            continue

                    all_events.append(event_data)

                    if max_events and len(all_events) >= max_events:
                        break

                offset += limit

                # Rate limiting
                await asyncio.sleep(self.rate_limit_delay)

                # Break if we got fewer results than requested
                if len(data) < limit:
                    break

            except httpx.HTTPError as e:
                print(f"Error fetching events at offset {offset}: {e}")
                break

        return all_events

    async def fetch_event(self, event_id: str) -> Optional[dict]:
        """
        Fetch single event with complete embedded market data.

        Returns raw JSON dict - no parsing to Pydantic models.

        Args:
            event_id: Event ID to fetch

        Returns:
            Raw event dict or None
        """
        client = await self._get_client()

        try:
            response = await client.get(f"{self.BASE_URL}/events/{event_id}")
            response.raise_for_status()
            data = response.json()

            if not data:
                return None

            # Validate minimum required fields
            if not data.get("id") or not data.get("slug"):
                return None

            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            print(f"HTTP error fetching event {event_id}: {e}")
            return None
        except Exception as e:
            print(f"Error fetching event {event_id}: {e}")
            return None

