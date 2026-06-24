"""Brooklyn Public Library events. Uses the public iCal feed for the system.
If the .ics URL changes, find the latest at https://www.bklynlibrary.org/calendar
"""
from __future__ import annotations

import logging
from typing import Iterator

from models import Event
from sources.base import Source
from utils.dates import to_local_iso, to_utc_iso
from utils.http import get_text

log = logging.getLogger(__name__)
FEED_URL = "https://www.bklynlibrary.org/calendar/ical"


class BPL(Source):
    name = "bpl"

    def fetch(self) -> Iterator[Event]:
        try:
            text = get_text(FEED_URL)
        except Exception as e:  # noqa: BLE001
            log.warning("bpl fetch failed: %s", e)
            return
        yield from _parse_ics(text, source=self.name, default_borough="Brooklyn")


def _parse_ics(text: str, *, source: str, default_borough: str | None = None) -> Iterator[Event]:
    """Minimal ICS parser — only the VEVENT fields we care about.
    Avoids a dependency on the `icalendar` package."""
    current: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith(" ") and current is not None:
            # Continuation line per RFC 5545.
            current["_last_value"] = current.get("_last_value", "") + line[1:]
            continue
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT" and current is not None:
            yield Event(
                source=source,
                source_id=current.get("UID"),
                title=_unescape(current.get("SUMMARY", "")),
                description=_unescape(current.get("DESCRIPTION", "")),
                url=current.get("URL"),
                start_utc=to_utc_iso(current.get("DTSTART")),
                end_utc=to_utc_iso(current.get("DTEND")),
                start_local=to_local_iso(current.get("DTSTART")),
                venue_name=current.get("LOCATION"),
                address=current.get("LOCATION"),
                borough=default_borough,
                is_free=True,
                price_min=0,
                price_max=0,
                categories=["education", "library"],
                raw=current,
            )
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.split(";", 1)[0]  # strip params like DTSTART;TZID=...
        current[key] = value
        current["_last_value"] = value


def _unescape(s: str) -> str:
    return s.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
