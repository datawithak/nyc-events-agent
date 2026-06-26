"""Eventbrite — Kids & Family events in NYC.

Scrapes the public Eventbrite discovery page for kids-and-family events.
Uses the embedded `window.__SERVER_DATA__` JSON (no auth required).

Coverage: ~2,800 upcoming events per run, paginated at 20/page.
Price info is not in listing data; is_free is inferred from title/description.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Iterator

from models import Event
from sources.base import Source
from utils.borough import detect_borough
from utils.categorize import looks_free
from utils.dates import to_local_iso, to_utc_iso
from utils.http import get_text

log = logging.getLogger(__name__)

# NYC kids & family events discovery URL — paginated via ?page=N
BASE_URL = "https://www.eventbrite.com/d/ny--new-york/kids-and-family--events/"

# Max pages to fetch per run (20 events/page → 200 events at 10 pages).
# Eventbrite has ~2,800 results but many are far future or low-quality.
# Fetching 10 pages gives good coverage without hammering the server.
MAX_PAGES = 10

# Seconds between page requests to be polite
PAGE_DELAY = 1.5

# Eventbrite requires a browser-like UA; our custom agent gets blocked.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# The JSON object is large — use a lazy match terminator that stops at };
# followed by a newline or </script>, not just </script>.
_SERVER_DATA_RE = re.compile(
    r"window\.__SERVER_DATA__\s*=\s*(\{.*?\});",
    re.DOTALL,
)


def _extract_server_data(html: str) -> dict | None:
    m = _SERVER_DATA_RE.search(html)
    if not m:
        return None
    try:
        import json
        return json.loads(m.group(1))
    except Exception as e:
        log.warning("eventbrite_kids: JSON parse failed: %s", e)
        return None


def _borough_from_locations(locations: list[dict]) -> str | None:
    """Eventbrite's 'locations' array includes a 'borough' entry for NYC events."""
    for loc in locations:
        if loc.get("type") == "borough":
            name = loc.get("name", "")
            if name in ("Manhattan", "Brooklyn", "Queens", "The Bronx", "Staten Island"):
                return "Bronx" if name == "The Bronx" else name
    return None


class EventbriteKids(Source):
    name = "eventbrite_kids"
    requires_key = None  # public pages only

    def fetch(self) -> Iterator[Event]:
        for page in range(1, MAX_PAGES + 1):
            url = BASE_URL if page == 1 else f"{BASE_URL}?page={page}"
            try:
                html = get_text(url, headers={"User-Agent": _BROWSER_UA})
            except Exception as e:  # noqa: BLE001
                log.warning("eventbrite_kids page %d failed: %s", page, e)
                break

            data = _extract_server_data(html)
            if not data:
                log.warning("eventbrite_kids page %d: no __SERVER_DATA__ found", page)
                break

            try:
                search = data["search_data"]["events"]
                results = search["results"]
                pagination = search["pagination"]
            except (KeyError, TypeError) as e:
                log.warning("eventbrite_kids page %d: unexpected structure: %s", page, e)
                break

            for raw in results:
                ev = self._parse(raw)
                if ev:
                    yield ev

            log.info(
                "eventbrite_kids: fetched page %d/%d (%d events)",
                page,
                pagination.get("page_count", "?"),
                len(results),
            )

            # Stop if we've hit the last page
            if pagination.get("page_number", page) >= pagination.get("page_count", 1):
                break

            time.sleep(PAGE_DELAY)

    def _parse(self, raw: dict) -> Event | None:
        title = raw.get("name", "").strip()
        if not title:
            return None

        venue = raw.get("primary_venue") or {}
        addr = venue.get("address") or {}

        street = addr.get("address_1") or ""
        city = addr.get("city") or ""
        state = addr.get("region") or ""
        zip_code = addr.get("postal_code") or ""
        venue_name = venue.get("name") or ""
        lat = addr.get("latitude")
        lon = addr.get("longitude")
        full_address = addr.get("localized_address_display") or f"{street}, {city}, {state} {zip_code}".strip(", ")

        # Borough: prefer Eventbrite's explicit location hierarchy
        borough = _borough_from_locations(raw.get("locations") or [])
        if not borough:
            borough = detect_borough(
                address=full_address,
                zip_code=zip_code,
                lat=float(lat) if lat else None,
                lon=float(lon) if lon else None,
            )

        # Dates — Eventbrite gives date (YYYY-MM-DD) and time (HH:MM) separately
        tz = raw.get("timezone", "America/New_York")
        start_dt = f"{raw.get('start_date', '')}T{raw.get('start_time', '00:00')}:00"
        end_dt = f"{raw.get('end_date', '')}T{raw.get('end_time', '00:00')}:00"

        # Tags → categories
        categories = ["family", "kids"]
        for tag in raw.get("tags") or []:
            display = (tag.get("display_name") or "").lower().strip()
            if display and display not in ("family & education", "kids and family", "nyc"):
                categories.append(display)

        # Price: not in listing data — infer from title/description
        description = raw.get("summary") or ""
        free_flag = looks_free(title, description)
        is_free = free_flag if free_flag is not None else None
        price_min = 0 if is_free else None

        # Image
        image = raw.get("image") or {}
        image_url = (
            image.get("image_sizes", {}).get("medium")
            or image.get("url")
        )

        return Event(
            source=self.name,
            source_id=str(raw.get("eventbrite_event_id") or raw.get("id") or ""),
            title=title,
            description=description,
            url=raw.get("url"),
            image_url=image_url,
            start_utc=to_utc_iso(start_dt),
            end_utc=to_utc_iso(end_dt),
            start_local=to_local_iso(start_dt),
            venue_name=venue_name,
            address=full_address,
            borough=borough,
            is_free=is_free,
            price_min=price_min,
            price_max=None,
            categories=list(dict.fromkeys(categories)),  # dedupe, preserve order
            audiences=["family", "kids"],
            raw=raw,
        )
