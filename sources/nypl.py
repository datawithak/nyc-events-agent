"""New York Public Library — Manhattan, Bronx, Staten Island branches.
NYPL exposes events as a public JSON endpoint backing its calendar page.
Endpoint may change; if it breaks, fall back to scraping the HTML calendar.
"""
from __future__ import annotations

import logging
from typing import Iterator

from models import Event
from sources.base import Source
from utils.borough import detect_borough
from utils.dates import to_local_iso, to_utc_iso
from utils.http import get_json

log = logging.getLogger(__name__)
ENDPOINT = "https://www.nypl.org/api/calendar/events"


class NYPL(Source):
    name = "nypl"

    def fetch(self) -> Iterator[Event]:
        try:
            data = get_json(ENDPOINT, params={"per_page": 200})
        except Exception as e:  # noqa: BLE001
            log.warning("nypl fetch failed (endpoint may have changed): %s", e)
            return
        events = data.get("events") or data.get("data") or []
        for raw in events:
            yield self._parse(raw)

    def _parse(self, raw: dict) -> Event:
        loc = raw.get("location") or {}
        addr = loc.get("address") or loc.get("street")
        zip_code = loc.get("zip") or loc.get("postal_code")
        return Event(
            source=self.name,
            source_id=str(raw.get("id") or raw.get("uuid") or ""),
            title=raw.get("title", ""),
            description=raw.get("description") or raw.get("body"),
            url=raw.get("url") or raw.get("permalink"),
            start_utc=to_utc_iso(raw.get("start") or raw.get("start_date")),
            end_utc=to_utc_iso(raw.get("end") or raw.get("end_date")),
            start_local=to_local_iso(raw.get("start") or raw.get("start_date")),
            venue_name=loc.get("name") or raw.get("branch"),
            address=addr,
            borough=detect_borough(address=addr, zip_code=zip_code),
            is_free=True,
            price_min=0,
            price_max=0,
            categories=["education", "library"],
            raw=raw,
        )
