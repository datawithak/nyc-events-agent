"""NYC Open Data — Permitted Event Information.
Covers parades, street fairs, festivals, block parties, plaza events.
Dataset: https://data.cityofnewyork.us/City-Government/NYC-Permitted-Event-Information/tvpp-9vvx
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Iterator

from config import API_KEYS, LOOKAHEAD_DAYS
from models import Event
from sources.base import Source
from utils.borough import detect_borough
from utils.dates import now_utc, to_local_iso, to_utc_iso
from utils.http import get_json

log = logging.getLogger(__name__)
ENDPOINT = "https://data.cityofnewyork.us/resource/tvpp-9vvx.json"

# Event types from the NYC permit dataset that ARE public spectator events.
# Anything NOT in this set is a private/internal permit and should be skipped.
_PUBLIC_EVENT_TYPES = {
    "special event",
    "street event",
    "farmers market",
    "greenmarket",
    "plaza partner event",
    "street fair",
    "parade",
    "block party",
    "film permit",       # include filming as it's public info
    "concert",
    "festival",
    "cultural event",
    "community event",
    "flea market",
    "market",
    "craft fair",
    "art fair",
    "food event",
    "run",               # 5K, marathon etc are public
    "race",
    "walk",
}

# Private/internal permits to explicitly exclude even if they pass type check.
_PRIVATE_TITLE_PATTERN = re.compile(
    r"^(softball|baseball|basketball|tennis|volleyball|hockey|bocce|"
    r"football|soccer|cricket|handball|lacrosse|rugby|archery|kickball|"
    r"miscellaneous|graduation|picnic|birthday|private|school|class|"
    r"practice|workout|drill)\b",
    re.IGNORECASE,
)


class NYCOpenData(Source):
    name = "nyc_open_data"
    requires_key = None  # token is optional, raises rate limit if present

    def fetch(self) -> Iterator[Event]:
        start = now_utc().strftime("%Y-%m-%dT%H:%M:%S")
        end = (now_utc() + timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
        headers = {}
        if API_KEYS.get("nyc_open_data"):
            headers["X-App-Token"] = API_KEYS["nyc_open_data"]
        try:
            rows = get_json(
                ENDPOINT,
                params={
                    "$where": f"start_date_time >= '{start}' AND start_date_time <= '{end}'",
                    "$order": "start_date_time ASC",
                    "$limit": 2000,
                },
                headers=headers,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("nyc_open_data failed: %s", e)
            return
        seen = set()
        for raw in rows:
            title = (raw.get("event_name") or "").strip()
            event_type = (raw.get("event_type") or "").strip().lower()

            # Skip private/internal permits — only keep public events
            if event_type and event_type not in _PUBLIC_EVENT_TYPES:
                continue
            if _PRIVATE_TITLE_PATTERN.match(title):
                continue
            if not title or title.lower() in {"miscellaneous", "tbd", "n/a", "na", "none"}:
                continue

            ev = self._parse(raw)
            if ev.hash in seen:  # collapse multi-day permits to one row
                continue
            seen.add(ev.hash)
            yield ev

    def _parse(self, raw: dict) -> Event:
        borough = (raw.get("event_borough") or "").title() or None
        if borough == "Manhattan ":
            borough = "Manhattan"
        address = raw.get("event_location") or raw.get("event_street_side")
        return Event(
            source=self.name,
            source_id=raw.get("event_id"),
            title=raw.get("event_name") or "(unnamed permitted event)",
            description=(
                f"Type: {raw.get('event_type', '')}. "
                f"Agency: {raw.get('event_agency', '')}. "
                f"Street side: {raw.get('event_street_side', '')}."
            ),
            url=None,  # dataset doesn't provide a public-facing URL
            start_utc=to_utc_iso(raw.get("start_date_time")),
            end_utc=to_utc_iso(raw.get("end_date_time")),
            start_local=to_local_iso(raw.get("start_date_time")),
            venue_name=raw.get("event_location"),
            address=address,
            borough=borough or detect_borough(address=address),
            is_free=True,  # permitted public events on city property are free to attend
            price_min=0,
            price_max=0,
            categories=["festival", "public"],
            audiences=["family"],  # permitted street events are family-friendly by default
            raw=raw,
        )
