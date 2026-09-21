"""HTTP-сессия с ретраями и человеческим User-Agent.

Опционально — через Cloudflare WARP: если задан WARP_PROXY
(например socks5h://127.0.0.1:40000 от wireproxy), make_session(use_warp=True)
повесит его на сессию. Нужен пакет pysocks (в requirements включён).
"""
from __future__ import annotations

import logging
import os
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import USER_AGENT, REQUEST_TIMEOUT

log = logging.getLogger(__name__)


def make_session(use_warp: bool = False) -> requests.Session:
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

    if use_warp:
        proxy = os.getenv("WARP_PROXY", "").strip()
        if not proxy:
            log.info("WARP запрошен, но WARP_PROXY не задан — работаем напрямую")
            return s
        try:
            import socks  # noqa: F401  # проверяем pysocks
            s.proxies.update({"http": proxy, "https": proxy})
            # не светим логин:пароль в логах
            shown = proxy.rsplit("@", 1)[-1]
            log.info("скрапер идёт через WARP-прокси %s", shown)
        except ImportError:
            log.warning("WARP_PROXY задан, но pysocks не установлен — работаем напрямую")
    return s


def polite_get(session: requests.Session, url: str, *, sleep: float = 0.0,
               **kwargs) -> requests.Response:
    """GET с опциональной паузой (вежливость к сайтам)."""
    if sleep:
        time.sleep(sleep)
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    return session.get(url, **kwargs)
