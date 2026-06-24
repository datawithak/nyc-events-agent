"""Yelp Events API — community events across all categories.

Free-tier API key: https://docs.developer.yelp.com/docs/fusion-intro
  1. Create an account at https://www.yelp.com/developers
  2. Create an app → get an API key
  3. Set YELP_API_KEY in .env

Covers: singles mixers, fitness classes, bar crawls, kids activities, food
tastings, comedy nights, art openings, networking events, community meetups —
the long tail that major ticketing platforms miss entirely.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterator

from config import API_KEYS, LOOKAHEAD_DAYS
from models import Event
from sources.base import Source
from utils.borough import detect_borough
from utils.dates import now_utc, to_local_iso, to_utc_iso
from utils.http import get_json

log = logging.getLogger(__name__)
ENDPOINT = "https://api.yelp.com/v3/events"

# Pull across all meaningful categories.
CATEGORIES = [
    "nightlife", "arts", "food-and-drink", "music", "sports-active-life",
    "community", "kids-family", "comedy", "film", "other",
]


class YelpEvents(Source):
    name = "yelp_events"
    requires_key = "yelp"

    def fetch(self) -> Iterator[Event]:
        start_ms = int(now_utc().timestamp())
        end_ms = int((now_utc() + timedelta(days=LOOKAHEAD_DAYS)).timestamp())
        headers = {"Authorization": f"Bearer {API_KEYS['yelp']}"}

        for category in CATEGORIES:
            offset = 0
            while True:
                try:
                    data = get_json(
                        ENDPOINT,
                        params={
                            "location": "New York City, NY",
                            "start_date": start_ms,
                            "end_date": end_ms,
                            "categories": category,
                            "limit": 50,
                            "offset": offset,
                            "sort_on": "time_start",
                            "sort_by": "asc",
                        },
                        headers=headers,
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("yelp_events [%s] offset=%d failed: %s", category, offset, e)
                    break

                events = data.get("events") or []
                if not events:
                    break

                for raw in events:
                    yield self._parse(raw)

                total = data.get("total", 0)
                offset += len(events)
                if offset >= min(total, 1000):  # Yelp caps at 1000 per search
                    break

    def _parse(self, raw: dict) -> Event:
        loc = raw.get("location") or {}
        address = " ".join(filter(None, [
            loc.get("address1"),
            loc.get("address2"),
            loc.get("city"),
            loc.get("state"),
            loc.get("zip_code"),
        ]))
        lat = raw.get("latitude")
        lon = raw.get("longitude")
        is_free = raw.get("is_free")
        price = raw.get("cost")

        audiences: list[str] = []
        if raw.get("is_canceled"):
            return None  # skip cancelled

        age_limit = raw.get("attending_count")  # not age, just in case
        # Yelp has explicit is_21_plus on some events
        if "21" in (raw.get("name") or "").lower() or raw.get("is_21_plus"):
            audiences.append("21+")

        return Event(
            source=self.name,
            source_id=raw.get("id"),
            title=raw.get("name") or "",
            description=raw.get("description"),
            url=raw.get("event_site_url"),
            image_url=raw.get("image_url"),
            start_utc=to_utc_iso(raw.get("time_start")),
            end_utc=to_utc_iso(raw.get("time_end")),
            start_local=to_local_iso(raw.get("time_start")),
            venue_name=raw.get("business_id"),  # Yelp business ID; name not always given
            address=address or None,
            borough=detect_borough(
                address=address,
                city=loc.get("city"),
                zip_code=loc.get("zip_code"),
                lat=lat,
                lon=lon,
            ),
            lat=lat,
            lon=lon,
            is_free=is_free,
            price_min=float(price) if price is not None else None,
            audiences=audiences,
            raw=raw,
        )
