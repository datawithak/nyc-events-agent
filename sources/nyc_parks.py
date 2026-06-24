"""NYC Parks events RSS feed.
Free city-park programming across all boroughs.
"""
from __future__ import annotations

import logging
from typing import Iterator

import feedparser

from models import Event
from sources.base import Source
from utils.borough import detect_borough
from utils.dates import to_local_iso, to_utc_iso
from utils.http import get_text

log = logging.getLogger(__name__)
FEED_URL = "https://www.nycgovparks.org/events.rss"


class NYCParks(Source):
    name = "nyc_parks"

    def fetch(self) -> Iterator[Event]:
        # NYC Parks blocks generic bot UAs on the RSS endpoint with 403.
        browser_ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
        try:
            text = get_text(FEED_URL, headers={"User-Agent": browser_ua})
        except Exception as e:  # noqa: BLE001
            log.warning("nyc_parks fetch failed: %s", e)
            return
        feed = feedparser.parse(text)
        for entry in feed.entries:
            yield self._parse(entry)

    def _parse(self, entry) -> Event:
        # RSS items include category fields like "Borough: Brooklyn".
        borough = None
        for tag in entry.get("tags") or []:
            term = (tag.get("term") or "")
            if term.startswith("Borough:"):
                borough = term.split(":", 1)[1].strip()
                break

        summary = entry.get("summary", "")
        start = entry.get("ev_startdate") or entry.get("published")

        return Event(
            source=self.name,
            source_id=entry.get("id") or entry.get("link"),
            title=entry.get("title", ""),
            description=summary,
            url=entry.get("link"),
            start_utc=to_utc_iso(start),
            start_local=to_local_iso(start),
            venue_name=entry.get("ev_location"),
            address=entry.get("ev_location"),
            borough=borough or detect_borough(address=entry.get("ev_location")),
            is_free=True,  # NYC Parks programming is overwhelmingly free
            price_min=0,
            price_max=0,
            categories=["outdoors", "parks"],
            audiences=["family"],
            raw=dict(entry),
        )
