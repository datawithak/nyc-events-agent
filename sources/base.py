"""Base source class. Subclasses register themselves on import."""
from __future__ import annotations

import logging
from typing import Iterator

from models import Event
from utils.categorize import categorize, infer_age_bounds, looks_free

registry: list[type["Source"]] = []
log = logging.getLogger(__name__)


class Source:
    name: str = "base"
    requires_key: str | None = None  # config.API_KEYS key, if any

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name != "base":
            registry.append(cls)

    def is_enabled(self) -> bool:
        if not self.requires_key:
            return True
        from config import API_KEYS
        return bool(API_KEYS.get(self.requires_key))

    def fetch(self) -> Iterator[Event]:  # pragma: no cover - abstract
        raise NotImplementedError

    @staticmethod
    def enrich(ev: Event) -> Event:
        """Fill in categories/audiences/age bounds/free hints from title+desc."""
        cats, auds = categorize(ev.title or "", ev.description or "")
        ev.categories = list({*(ev.categories or []), *cats})
        ev.audiences = list({*(ev.audiences or []), *auds})
        if ev.age_min is None and ev.age_max is None:
            ev.age_min, ev.age_max = infer_age_bounds(ev.title or "", ev.description or "")
        if ev.is_free is None:
            ev.is_free = looks_free(ev.title or "", ev.description or "")
        return ev
