"""Secret NYC — curated, mostly free/cheap things-to-do roundups via RSS."""
from __future__ import annotations

import logging
from typing import Iterator

import feedparser

from models import Event
from sources.base import Source
from utils.dates import to_local_iso, to_utc_iso
from utils.http import get_text

log = logging.getLogger(__name__)
FEED_URL = "https://secretnyc.co/feed/"


class SecretNYC(Source):
    name = "secret_nyc"

    def fetch(self) -> Iterator[Event]:
        try:
            text = get_text(FEED_URL)
        except Exception as e:  # noqa: BLE001
            log.warning("secret_nyc fetch failed: %s", e)
            return
        feed = feedparser.parse(text)
        for entry in feed.entries:
            yield Event(
                source=self.name,
                source_id=entry.get("id") or entry.get("link"),
                title=entry.get("title", ""),
                description=entry.get("summary", ""),
                url=entry.get("link"),
                # Editorial roundup — no specific event date; keep start_utc null
                # so the event isn't purged as "past" by the nightly cleanup.
                start_utc=None,
                start_local=None,
                categories=["editorial", "roundup"],
                raw=dict(entry),
            )
