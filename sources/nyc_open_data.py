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

# Keywords that signal an event is genuinely family/kid-oriented.
# Only events whose title or event_type matches get the "family"/"kids" audience tag.
# Everything else gets no audience tag — NYC Open Data permits cover everything from
# weddings to construction sites; we cannot assume "family-friendly" by default.
_FAMILY_KW = re.compile(
    r"\b(family|families|kid s?|kids?|children|child|toddler|youth|baby|babies|"
    r"junior|teen|student|school|playground|puppet|storytime|story\s*time|"
    r"sesame|disney|carnival|circus|magic\s*show|bounce|petting\s*zoo)\b",
    re.IGNORECASE,
)


def _infer_audiences(title: str, event_type: str = "") -> list[str]:
    """Return ['family', 'kids'] only when the title/type explicitly signals it."""
    if _FAMILY_KW.search(f"{title} {event_type}"):
        return ["family", "kids"]
    return []

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

# ── Private/internal permit filters ──────────────────────────────────────────
# We use three separate lists to avoid regex-boundary issues with a single
# giant alternation pattern.

# 1. Titles that START with a private/sports/internal keyword.
#    re.match() anchors at the start, so no ^ needed in the pattern.
_PREFIX_BLOCK = re.compile(
    r"^(softball|baseball|basketball|tennis|volleyball|hockey|bocce|"
    r"football|soccer|cricket|handball|lacrosse|rugby|archery|kickball|"
    r"graduation|picnic|birthday|private|practice|workout|drill|"
    r"gathering|meeting|ceremony|rehearsal|banquet|luncheon|reception|"
    r"seminar|conference|retreat|assembly|barbecue|bbq|cookout|"
    # NYC Parks internal placeholders — note: no \b needed after [: ] because
    # re.match already consumed to the right position; we just need something
    # after the keyword to separate "HOLD: EVENT" from a real "Hold On" title.
    r"muts\b|tbd\b|construction\b|"
    r"parks\s+event\b|park\s+event\b|"
    r"film\s+shoot\b|photo\s+shoot\b|"
    # FIFA / World Cup blackout dates (FWC2026, FWC 2026, FIFA Match …)
    r"fwc\s*\d+|fifa\b)",
    re.IGNORECASE,
)

# 2. Keywords that can appear ANYWHERE in the title.
#    Use re.search() to catch "Cherry Lawn Closure", "Rain Date - Parade", etc.
_ANYWHERE_BLOCK = re.compile(
    r"\b(closure|closed|rain\s+date|filming|film\s+shoot|photo\s+shoot)\b"
    # "HOLD" as a standalone word/prefix (catches "HOLD:", "HOLD -", "HOLD EVENT")
    r"|\bhold\b"
    # School event designations always followed by a number: "PS 270", "IS 270Q", "JHS 70", "CSD 2"
    # Require digit right after abbreviation to avoid blocking "MS Walk" / "HS Jazz Fest" etc.
    r"|\b(ps|is|jhs|ms|hs|csd)\s*[/\\]?\s*(ps|is|jhs|ms|hs|csd)?\s*\d"
    r"|\bdistrict\s+\d"
    # Generic private-school/permit language anywhere in title
    r"|\b(outdoor\s+learning|learning\s+permit|school\s+carnival|"
    r"school\s+fair|school\s+field\s+trip)\b",
    re.IGNORECASE,
)

# 3. Titles that are EXACTLY (or nearly) a single vague word — no real event info.
_VAGUE_TITLE = re.compile(
    r"^(celebration|event|gathering|program|programming|closed|closure|"
    r"hold|tbd|n/?a|none|unknown|untitled|party|barbecue|bbq|cookout|"
    r"picnic|rehearsal|ceremony|meeting|assembly|seminar|conference)\s*$",
    re.IGNORECASE,
)


def _is_junk_title(title: str) -> bool:
    """Return True if the title looks like a private/internal permit."""
    return bool(
        _PREFIX_BLOCK.match(title)
        or _ANYWHERE_BLOCK.search(title)
        or _VAGUE_TITLE.match(title)
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
            if not title or title.lower() in {"miscellaneous", "tbd", "n/a", "na", "none", "parks event", "park event", "closed"}:
                continue
            if _is_junk_title(title):
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
            audiences=_infer_audiences(
                raw.get("event_name") or "",
                raw.get("event_type") or "",
            ),
            raw=raw,
        )
