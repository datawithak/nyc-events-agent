"""Lincoln Center — Summer for the City (free & choose-what-you-pay events).
Scrapes the Summer for the City calendar page.
Coverage: Upper West Side / Lincoln Center Plaza — hundreds of free summer events.
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

from models import Event
from sources.base import Source
from utils.dates import to_utc_iso, to_local_iso
from utils.http import get_text

log = logging.getLogger(__name__)

BASE_URL = "https://www.lincolncenter.org"
SERIES_URL = f"{BASE_URL}/series/summer-for-the-city/v/calendar"


class LincolnCenter(Source):
    name = "lincoln_center"
    requires_key = None

    def fetch(self) -> Iterator[Event]:
        try:
            html = get_text(SERIES_URL)
        except Exception as e:
            log.warning("lincoln_center fetch failed: %s", e)
            return

        # Parse event blocks from the HTML
        # LC uses structured data — look for JSON-LD or data attributes
        import json

        # Try JSON-LD structured data first
        ld_blocks = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        )
        for block in ld_blocks:
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") not in ("Event", "MusicEvent", "TheaterEvent",
                                                   "DanceEvent", "ScreeningEvent"):
                        continue
                    ev = self._from_ld(item)
                    if ev:
                        yield ev
            except (json.JSONDecodeError, KeyError):
                continue

        # Fallback: look for event links and titles via HTML patterns
        # LC event cards typically look like: /event/<slug>
        event_links = re.findall(
            r'href="(/(?:events?|performances?)/[^"]+)"[^>]*>.*?</a>',
            html, re.DOTALL
        )
        seen_urls: set[str] = set()
        for path in event_links:
            url = BASE_URL + path
            if url in seen_urls:
                continue
            seen_urls.add(url)
            # We got a link but need to parse dates — skip deep scraping for now
            # The JSON-LD path above is the primary mechanism

    def _from_ld(self, item: dict) -> Event | None:
        """Parse a JSON-LD Event item."""
        try:
            name = item.get("name", "").strip()
            if not name:
                return None

            start_raw = item.get("startDate") or item.get("startTime")
            end_raw   = item.get("endDate")   or item.get("endTime")

            location = item.get("location") or {}
            if isinstance(location, list):
                location = location[0]
            venue = location.get("name", "Lincoln Center")
            address_obj = location.get("address") or {}
            address = (
                address_obj.get("streetAddress", "")
                + ", New York, "
                + address_obj.get("postalCode", "10023")
            ).strip(", ")

            url = item.get("url") or item.get("@id") or ""
            if url and not url.startswith("http"):
                url = BASE_URL + url

            # Offers / price
            offers = item.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0]
            price_min = None
            is_free = True
            if isinstance(offers, dict):
                price_val = offers.get("price")
                if price_val not in (None, "", "0", 0):
                    try:
                        price_min = float(price_val)
                        is_free = price_min == 0
                    except (ValueError, TypeError):
                        pass

            description = item.get("description", "")
            image_url   = None
            img = item.get("image")
            if isinstance(img, str):
                image_url = img
            elif isinstance(img, dict):
                image_url = img.get("url")

            return Event(
                source=self.name,
                source_id=item.get("@id") or url or name,
                title=name,
                description=description,
                url=url or None,
                image_url=image_url,
                start_utc=to_utc_iso(start_raw),
                end_utc=to_utc_iso(end_raw),
                start_local=to_local_iso(start_raw),
                venue_name=venue,
                address=address or "10 Lincoln Center Plaza, New York, 10023",
                borough="Manhattan",
                is_free=is_free,
                price_min=price_min,
                price_max=price_min,
                categories=["arts", "music", "theater", "outdoor"],
                audiences=["adults", "family"],
                raw=item,
            )
        except Exception as e:
            log.debug("lincoln_center parse error: %s", e)
            return None
