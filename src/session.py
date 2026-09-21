"""HTTP-сессия с ретраями и человеческим User-Agent."""
from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import USER_AGENT, REQUEST_TIMEOUT

log = logging.getLogger(__name__)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "hy,ru;q=0.9,en;q=0.8",
    })
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def polite_get(session: requests.Session, url: str, *, sleep: float = 0.0,
               **kwargs) -> requests.Response:
    """GET с опциональной паузой (вежливость к сайтам)."""
    if sleep:
        time.sleep(sleep)
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    return session.get(url, **kwargs)
