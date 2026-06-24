"""City Parks Foundation — SummerStage and free park events across all 5 boroughs.

CPF runs the SummerStage concert series (free + ticketed shows at Central Park
and neighbourhood venues across all boroughs) and other free outdoor
programming. Their events RSS is publicly accessible.
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

# Primary events feed — all CPF programs including SummerStage.
FEED_URL = "https://www.cityparksfoundation.org/events/feed/"


class CityParksFoundation(Source):
    name = "city_parks_foundation"

    def fetch(self) -> Iterator[Event]:
        try:
            text = get_text(FEED_URL)
        except Exception as e:  # noqa: BLE001
            log.warning("city_parks_foundation fetch failed: %s", e)
            return
        feed = feedparser.parse(text)
        log.debug("city_parks_foundation: %d entries", len(feed.entries))
        for entry in feed.entries:
            yield self._parse(entry)

    def _parse(self, entry) -> Event:
        tags = [t.get("term", "") for t in (entry.get("tags") or [])]
        is_free = "Free" in tags or "free" in " ".join(tags).lower()

        # Location is sometimes in the title (e.g. "SummerStage at Central Park")
        # or in summary text. Extract borough from both.
        summary = entry.get("summary", "")
        title = entry.get("title", "")
        address_hint = f"{title} {summary}"

        return Event(
            source=self.name,
            source_id=entry.get("id") or entry.get("link"),
            title=title,
            description=summary,
            url=entry.get("link"),
            start_utc=to_utc_iso(entry.get("published")),
            start_local=to_local_iso(entry.get("published")),
            borough=detect_borough(address=address_hint),
            is_free=is_free,
            price_min=0.0 if is_free else None,
            price_max=0.0 if is_free else None,
            categories=["music", "outdoors", "festival"],
            audiences=["family"],
            raw=dict(entry),
        )
