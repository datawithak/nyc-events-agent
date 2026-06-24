"""Time Out New York — editorial event roundups via their public RSS feeds.

This is a curated, public-facing list (no auth), suitable for indexing per
robots.txt at the time of writing. Each entry is an editorial article, not a
single discrete event — we surface it as one event row and let downstream code
treat it as a roundup. Always check robots.txt before changing this.
"""
from __future__ import annotations

import logging
from typing import Iterator

import feedparser

from models import Event
from sources.base import Source
from utils.dates import to_local_iso, to_utc_iso
from utils.http import get_text

log = logging.getLogger(__name__)
FEED_URL = "https://www.timeout.com/newyork/feed.rss"


class TimeOutNY(Source):
    name = "timeout_ny"

    def fetch(self) -> Iterator[Event]:
        try:
            text = get_text(FEED_URL)
        except Exception as e:  # noqa: BLE001
            log.warning("timeout_ny fetch failed: %s", e)
            return
        feed = feedparser.parse(text)
        for entry in feed.entries:
            title = entry.get("title", "")
            # Filter to event-y posts.
            t = title.lower()
            if not any(k in t for k in ("event", "things to do", "happening", "weekend", "tonight", "this week")):
                continue
            yield Event(
                source=self.name,
                source_id=entry.get("id") or entry.get("link"),
                title=title,
                description=entry.get("summary", ""),
                url=entry.get("link"),
                start_utc=to_utc_iso(entry.get("published")),
                start_local=to_local_iso(entry.get("published")),
                categories=["editorial", "roundup"],
                raw=dict(entry),
            )
