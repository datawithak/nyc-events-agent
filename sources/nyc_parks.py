"""NYC Parks — HTML events calendar scraper.

Scrapes the public NYC Parks events calendar at nycgovparks.org/events.
The RSS feed (/events.rss) is WAF-blocked from datacenter IPs, but the HTML
calendar pages respond fine with a browser UA.

Each category page returns up to 50 events with Schema.org Event markup.
We scrape several targeted categories and deduplicate by URL so the same
event appearing in multiple categories is only yielded once.

Coverage: ~200 unique upcoming events per run across all targeted categories.
All NYC Parks programming is free or low-cost.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Iterator

from models import Event
from sources.base import Source
from utils.dates import to_local_iso, to_utc_iso
from utils.http import get_text

log = logging.getLogger(__name__)

BASE = "https://www.nycgovparks.org"

# Category pages to scrape. Ordered by family-relevance.
# Each returns up to 50 events (site maximum per page).
CATEGORY_PATHS = [
    "/events/kids",
    "/events/all",
    "/events/nature",
    "/events/arts_culture_fun",
    "/events/free_summer_concerts",
    "/events/free_summer_movies",
    "/events/free_summer_theater",
    "/events/festivals",
    "/events/urbanparkrangers",
]

# Delay between category page fetches to be polite
PAGE_DELAY = 1.0

# Browser UA required — generic bot UAs are blocked by Incapsula on some paths
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Schema.org event block — starts at the row div, stops at the next one
_EVENT_BLOCK_RE = re.compile(
    r'<div[^>]+class="row event[^"]*"[^>]*>(.*?)'
    r'(?=<div[^>]+class="row event|<div[^>]+class="events-date-header|$)',
    re.DOTALL,
)

# Schema.org itemprop extractors
_NAME_RE    = re.compile(r'itemprop="name"[^>]*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
_LOC_RE     = re.compile(r'itemprop="name"\s*>([^<]+)</span>', re.DOTALL)
_STREET_RE  = re.compile(r'itemprop="streetAddress"\s+content="([^"]+)"')
_BOROUGH_RE = re.compile(r'itemprop="addressLocality"\s*>([^<]+)</span>')
_START_RE   = re.compile(r'itemprop="startDate"\s+content="([^"]+)"')
_END_RE     = re.compile(r'itemprop="endDate"\s+content="([^"]+)"')
_DESC_RE    = re.compile(r'<p[^>]*>(.*?)</p>', re.DOTALL)
_FREE_RE    = re.compile(r'\b(free|no\s+(?:cost|charge|admission)|complimentary)\b', re.IGNORECASE)


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _parse_event_block(block: str) -> dict | None:
    """Extract structured fields from one Schema.org event block."""
    name_m    = _NAME_RE.search(block)
    start_m   = _START_RE.search(block)
    end_m     = _END_RE.search(block)
    borough_m = _BOROUGH_RE.search(block)
    street_m  = _STREET_RE.search(block)

    if not name_m or not start_m:
        return None

    url_path = name_m.group(1).strip()
    title    = _strip_tags(name_m.group(2))
    if not title:
        return None

    # Venue name is the first itemprop="name" that's NOT a link (the <span> form)
    # We look for it after the event-title link, so we skip the event title match
    # and grab the location span.
    loc_matches = _LOC_RE.findall(block)
    venue_name = loc_matches[0].strip() if loc_matches else ""

    borough_raw = borough_m.group(1).strip() if borough_m else ""
    # NYC Parks uses full names including "Staten Island"; normalise "The Bronx" → "Bronx"
    borough = "Bronx" if "bronx" in borough_raw.lower() else borough_raw

    street = street_m.group(1).strip() if street_m else ""
    full_address = f"{street}, {borough}, NY" if street else f"{borough}, NY"

    start_iso = start_m.group(1)
    end_iso   = end_m.group(1) if end_m else ""

    # Description: first <p> that has actual text
    desc = ""
    for desc_m in _DESC_RE.finditer(block):
        candidate = _strip_tags(desc_m.group(1)).strip()
        if len(candidate) > 20:
            desc = candidate
            break

    # NYC Parks events are overwhelmingly free; flag if explicitly free or unknown
    is_free = 1  # Parks programming is free by default
    if "admission" in block.lower() and not _FREE_RE.search(block):
        is_free = None  # has admission mention but not confirmed free

    # Categories from CSS class string (e.g. "row event cat2 cat15 cat18")
    cat_match = re.search(r'class="row event([^"]*)"', block)
    css_cats  = cat_match.group(1).strip().split() if cat_match else []

    return {
        "url":         BASE + url_path,
        "source_id":   url_path,   # e.g. /events/2026/06/25/kids-in-motion-...
        "title":       title,
        "description": desc,
        "venue_name":  venue_name,
        "borough":     borough,
        "address":     full_address,
        "start_iso":   start_iso,
        "end_iso":     end_iso,
        "is_free":     is_free,
        "css_cats":    css_cats,
    }


class NYCParks(Source):
    name = "nyc_parks"
    requires_key = None  # public HTML, no auth

    def fetch(self) -> Iterator[Event]:
        seen: set[str] = set()

        for i, path in enumerate(CATEGORY_PATHS):
            url = BASE + path
            try:
                html = get_text(url, headers={"User-Agent": _BROWSER_UA})
            except Exception as e:  # noqa: BLE001
                log.warning("nyc_parks: fetch failed for %s: %s", path, e)
                if i < len(CATEGORY_PATHS) - 1:
                    time.sleep(PAGE_DELAY)
                continue

            # Check for WAF block (Incapsula returns a challenge page)
            if "incapsula" in html.lower() or len(html) < 5000:
                log.warning("nyc_parks: WAF block detected on %s", path)
                break

            count = 0
            for block_m in _EVENT_BLOCK_RE.finditer(html):
                block = block_m.group(1)
                parsed = _parse_event_block(block)
                if not parsed:
                    continue

                src_id = parsed["source_id"]
                if src_id in seen:
                    continue
                seen.add(src_id)

                ev = self._make_event(parsed)
                if ev:
                    count += 1
                    yield ev

            log.info("nyc_parks: %s → %d new events (total unique so far: %d)", path, count, len(seen))

            if i < len(CATEGORY_PATHS) - 1:
                time.sleep(PAGE_DELAY)

    def _make_event(self, p: dict) -> Event | None:
        start_utc   = to_utc_iso(p["start_iso"])
        end_utc     = to_utc_iso(p["end_iso"]) if p["end_iso"] else None
        start_local = to_local_iso(p["start_iso"])

        # Tags from CSS categories (cat2, cat15, etc.) don't map to human names
        # in the HTML, so we just use generic tags + "parks"
        categories = ["outdoors", "parks", "free"]
        audiences  = ["family", "kids"]

        return Event(
            source=self.name,
            source_id=p["source_id"],
            title=p["title"],
            description=p["description"],
            url=p["url"],
            image_url=None,
            start_utc=start_utc,
            end_utc=end_utc,
            start_local=start_local,
            venue_name=p["venue_name"],
            address=p["address"],
            borough=p["borough"],
            is_free=p["is_free"],
            price_min=0 if p["is_free"] == 1 else None,
            price_max=None,
            categories=categories,
            audiences=audiences,
            raw=p,
        )
