"""Queens Public Library events. Reuses the ICS parser from bpl.py."""
from __future__ import annotations

import logging
from typing import Iterator

from models import Event
from sources.base import Source
from sources.bpl import _parse_ics
from utils.http import get_text

log = logging.getLogger(__name__)
FEED_URL = "https://www.queenslibrary.org/calendar/ical"


class QPL(Source):
    name = "qpl"

    def fetch(self) -> Iterator[Event]:
        try:
            text = get_text(FEED_URL)
        except Exception as e:  # noqa: BLE001
            log.warning("qpl fetch failed: %s", e)
            return
        yield from _parse_ics(text, source=self.name, default_borough="Queens")
