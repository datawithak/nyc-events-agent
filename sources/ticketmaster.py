"""Ticketmaster Discovery API — concerts, sports, theater, family.
Docs: https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
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
ENDPOINT = "https://app.ticketmaster.com/discovery/v2/events.json"


class Ticketmaster(Source):
    name = "ticketmaster"
    requires_key = "ticketmaster"

    def fetch(self) -> Iterator[Event]:
        start = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        end = (now_utc() + timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        page = 0
        while True:
            try:
                data = get_json(
                    ENDPOINT,
                    params={
                        "apikey": API_KEYS["ticketmaster"],
                        "city": "New York,Brooklyn,Queens,Bronx,Staten Island",
                        "stateCode": "NY",
                        "countryCode": "US",
                        "startDateTime": start,
                        "endDateTime": end,
                        "size": 200,
                        "page": page,
                        "sort": "date,asc",
                    },
                )
            except Exception as e:  # noqa: BLE001
                log.warning("ticketmaster page %s failed: %s", page, e)
                return
            events = (data.get("_embedded") or {}).get("events") or []
            for raw in events:
                yield self._parse(raw)
            page_info = data.get("page") or {}
            if page + 1 >= page_info.get("totalPages", 0):
                return
            page += 1
            if page >= 5:  # TM Discovery API hard-caps at pages 0-4 (5 pages × 200 = 1000 max).
                return

    def _parse(self, raw: dict) -> Event:
        venues = ((raw.get("_embedded") or {}).get("venues") or [])
        venue = venues[0] if venues else {}
        addr = (venue.get("address") or {}).get("line1")
        city = (venue.get("city") or {}).get("name")
        zip_code = venue.get("postalCode")
        loc = venue.get("location") or {}
        lat = float(loc["latitude"]) if loc.get("latitude") else None
        lon = float(loc["longitude"]) if loc.get("longitude") else None

        dates = raw.get("dates") or {}
        start = (dates.get("start") or {})
        start_iso = start.get("dateTime") or start.get("localDate")

        price_min = price_max = None
        prices = raw.get("priceRanges") or []
        if prices:
            price_min = min(p.get("min", 0) for p in prices)
            price_max = max(p.get("max", 0) for p in prices)
        is_free = (price_min == 0 and price_max == 0) if prices else None

        classifications = raw.get("classifications") or []
        cats = []
        audiences = []
        for c in classifications:
            for k in ("segment", "genre", "subGenre", "type", "subType"):
                v = (c.get(k) or {}).get("name")
                if v and v.lower() not in {"undefined", "other"}:
                    cats.append(v.lower())
            if (c.get("family") is True):
                audiences.append("family")

        return Event(
            source=self.name,
            source_id=raw.get("id"),
            title=raw.get("name") or "",
            description=(raw.get("info") or raw.get("pleaseNote") or ""),
            url=raw.get("url"),
            image_url=(raw.get("images") or [{}])[0].get("url"),
            start_utc=to_utc_iso(start_iso),
            start_local=to_local_iso(start_iso),
            venue_name=venue.get("name"),
            address=", ".join(x for x in [addr, city, zip_code] if x),
            borough=detect_borough(address=addr, city=city, zip_code=zip_code, lat=lat, lon=lon),
            lat=lat,
            lon=lon,
            is_free=is_free,
            price_min=price_min,
            price_max=price_max,
            currency=(prices[0].get("currency") if prices else "USD"),
            categories=cats,
            audiences=audiences,
            raw=raw,
        )
