"""Resident Advisor — NYC electronic music, club nights, nightlife.

Uses RA's public GraphQL API (unofficial but widely used, accessible without
auth). NYC area ID = 8. Returns club nights, concerts, DJ sets, warehouse
parties — everything the mainstream ticketing platforms miss.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterator

from config import LOOKAHEAD_DAYS
from models import Event
from sources.base import Source
from utils.borough import detect_borough
from utils.dates import now_utc, to_local_iso, to_utc_iso
from utils.http import get_json
from utils.http import session

log = logging.getLogger(__name__)
GRAPHQL_URL = "https://ra.co/graphql"
NYC_AREA_ID = 8  # "New York City" confirmed via RA area search

QUERY = """
query eventListings($filters: FilterInputDtoInput, $pageSize: Int, $page: Int) {
  eventListings(filters: $filters, pageSize: $pageSize, page: $page) {
    data {
      id
      listingDate
      event {
        id title date startTime endTime cost minimumAge contentUrl
        isTicketed isFestival
        venue {
          name contentUrl address
          location { latitude longitude }
          area { name }
        }
      }
    }
    totalResults
  }
}
"""


def _gql(variables: dict) -> dict:
    r = session().post(
        GRAPHQL_URL,
        json={"query": QUERY, "variables": variables},
        headers={
            "Content-Type": "application/json",
            "Referer": "https://ra.co/",
        },
        timeout=20,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("errors") and not body.get("data"):
        raise ValueError(f"RA GraphQL error: {body['errors'][0]['message']}")
    return body["data"]["eventListings"]


class ResidentAdvisor(Source):
    name = "resident_advisor"

    def fetch(self) -> Iterator[Event]:
        today = now_utc().strftime("%Y-%m-%d")
        end = (now_utc() + timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y-%m-%d")
        page = 1
        page_size = 100
        total = None

        while True:
            try:
                result = _gql({
                    "filters": {
                        "areas": {"eq": NYC_AREA_ID},
                        "listingDate": {"gte": today, "lte": end},
                    },
                    "pageSize": page_size,
                    "page": page,
                })
            except Exception as e:  # noqa: BLE001
                log.warning("resident_advisor page %d failed: %s", page, e)
                return

            if total is None:
                total = result.get("totalResults", 0)
                log.debug("resident_advisor: %d total events", total)

            items = result.get("data") or []
            if not items:
                return

            for item in items:
                ev = self._parse(item)
                if ev is not None:
                    yield ev

            fetched = (page - 1) * page_size + len(items)
            if fetched >= total or page >= 50:  # 50 pages × 100 = 5000 cap
                return
            page += 1

    def _parse(self, item: dict) -> Event | None:
        raw_ev = item.get("event")
        if not raw_ev:
            return None

        venue = raw_ev.get("venue") or {}
        loc = venue.get("location") or {}
        lat = loc.get("latitude")
        lon = loc.get("longitude")

        cost_str = raw_ev.get("cost") or ""
        is_free, price_min, price_max = _parse_cost(cost_str)

        # RA contentUrl looks like "/events/us/newyork/1234"
        content_url = raw_ev.get("contentUrl") or ""
        url = f"https://ra.co{content_url}" if content_url.startswith("/") else content_url

        # Venue URL for borough hint when address isn't detailed enough.
        address = venue.get("address")

        return Event(
            source=self.name,
            source_id=str(raw_ev.get("id") or ""),
            title=raw_ev.get("title") or "",
            url=url,
            start_utc=to_utc_iso(raw_ev.get("date")),
            start_local=to_local_iso(raw_ev.get("date")),
            end_utc=to_utc_iso(raw_ev.get("endTime")),
            venue_name=venue.get("name"),
            address=address,
            borough=detect_borough(address=address, lat=lat, lon=lon),
            lat=lat,
            lon=lon,
            is_free=is_free,
            price_min=price_min,
            price_max=price_max,
            age_min=raw_ev.get("minimumAge"),
            categories=["nightlife", "music", "electronic"],
            audiences=["adults"],
            raw=raw_ev,
        )


def _parse_cost(cost: str) -> tuple[bool | None, float | None, float | None]:
    """Parse RA's free-form cost string into (is_free, min, max)."""
    import re
    if not cost:
        return None, None, None
    c = cost.strip().lower()
    if c in ("free", "0", "0.00", "$0", "free entry"):
        return True, 0.0, 0.0
    # Extract numbers like "$10-20", "£5 - £10", "$15"
    nums = [float(x) for x in re.findall(r"[\d]+(?:\.\d+)?", c)]
    if not nums:
        return False, None, None
    return False, min(nums), max(nums)
