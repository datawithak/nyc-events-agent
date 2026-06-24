"""SeatGeek Platform API — concerts, sports, comedy, theater.
Docs: https://platform.seatgeek.com/
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
ENDPOINT = "https://api.seatgeek.com/2/events"


class SeatGeek(Source):
    name = "seatgeek"
    requires_key = "seatgeek"

    def fetch(self) -> Iterator[Event]:
        start = now_utc().strftime("%Y-%m-%d")
        end = (now_utc() + timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y-%m-%d")
        page = 1
        while True:
            try:
                data = get_json(
                    ENDPOINT,
                    params={
                        "client_id": API_KEYS["seatgeek"],
                        "venue.city": "New York",
                        "venue.state": "NY",
                        "datetime_utc.gte": start,
                        "datetime_utc.lte": end,
                        "per_page": 100,
                        "page": page,
                    },
                )
            except Exception as e:  # noqa: BLE001
                log.warning("seatgeek page %s failed: %s", page, e)
                return
            events = data.get("events") or []
            if not events:
                return
            for raw in events:
                yield self._parse(raw)
            meta = data.get("meta") or {}
            if page * meta.get("per_page", 100) >= meta.get("total", 0):
                return
            page += 1
            if page > 20:
                return

    def _parse(self, raw: dict) -> Event:
        venue = raw.get("venue") or {}
        loc = venue.get("location") or {}
        lat = loc.get("lat")
        lon = loc.get("lon")
        stats = raw.get("stats") or {}
        price_min = stats.get("lowest_price")
        price_max = stats.get("highest_price")
        is_free = (price_min == 0) if price_min is not None else None

        cats = [t["name"].lower() for t in (raw.get("taxonomies") or []) if t.get("name")]

        return Event(
            source=self.name,
            source_id=str(raw.get("id")) if raw.get("id") is not None else None,
            title=raw.get("title") or raw.get("short_title") or "",
            description=raw.get("description"),
            url=raw.get("url"),
            image_url=(raw.get("performers") or [{}])[0].get("image"),
            start_utc=to_utc_iso(raw.get("datetime_utc")),
            start_local=to_local_iso(raw.get("datetime_local")),
            venue_name=venue.get("name"),
            address=venue.get("address"),
            borough=detect_borough(
                address=venue.get("address"),
                city=venue.get("city"),
                zip_code=venue.get("postal_code"),
                lat=lat,
                lon=lon,
            ),
            lat=lat,
            lon=lon,
            is_free=is_free,
            price_min=price_min,
            price_max=price_max,
            categories=cats,
            raw=raw,
        )
