"""Event dataclass + row serialization."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").strip().lower().encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()


@dataclass
class Event:
    source: str
    title: str
    url: Optional[str] = None
    source_id: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    start_utc: Optional[str] = None        # ISO8601 in UTC
    end_utc: Optional[str] = None
    start_local: Optional[str] = None      # ISO8601 in America/New_York
    venue_name: Optional[str] = None
    address: Optional[str] = None
    borough: Optional[str] = None          # Manhattan|Brooklyn|Queens|Bronx|Staten Island
    lat: Optional[float] = None
    lon: Optional[float] = None
    is_free: Optional[bool] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = "USD"
    categories: list[str] = field(default_factory=list)
    audiences: list[str] = field(default_factory=list)
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    raw: Optional[dict] = None

    @property
    def hash(self) -> str:
        # Dedup key: source + source_id when we have one, else title+venue+start.
        if self.source_id:
            return _hash(self.source, self.source_id)
        return _hash(self.source, self.title, self.venue_name or "", self.start_utc or "")

    def to_row(self) -> dict:
        return {
            "hash": self.hash,
            "source": self.source,
            "source_id": self.source_id,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "image_url": self.image_url,
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "start_local": self.start_local,
            "venue_name": self.venue_name,
            "address": self.address,
            "borough": self.borough,
            "lat": self.lat,
            "lon": self.lon,
            "is_free": 1 if self.is_free else (0 if self.is_free is False else None),
            "price_min": self.price_min,
            "price_max": self.price_max,
            "currency": self.currency,
            "categories": json.dumps(self.categories) if self.categories else None,
            "audiences": json.dumps(self.audiences) if self.audiences else None,
            "age_min": self.age_min,
            "age_max": self.age_max,
            "raw": json.dumps(self.raw, default=str) if self.raw is not None else None,
        }
