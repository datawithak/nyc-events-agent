"""Shared HTTP session with retries, UA, and polite defaults."""
from __future__ import annotations

import logging
from typing import Any, Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import HTTP_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)

_session: Optional[requests.Session] = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/html, */*"})
        _session = s
    return _session


class TransientHTTPError(Exception):
    pass


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((TransientHTTPError, requests.ConnectionError, requests.Timeout)),
)
def get_json(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Any:
    r = session().get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
    if r.status_code in (429, 500, 502, 503, 504):
        raise TransientHTTPError(f"{r.status_code} on {url}")
    r.raise_for_status()
    return r.json()


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((TransientHTTPError, requests.ConnectionError, requests.Timeout)),
)
def get_text(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> str:
    r = session().get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
    if r.status_code in (429, 500, 502, 503, 504):
        raise TransientHTTPError(f"{r.status_code} on {url}")
    r.raise_for_status()
    return r.text
