"""hire.am — на момент написания домен не резолвится (сайт не отвечает).

Скрапер оставлен намеренно: если сайт оживёт, источник автоматически
подключится к конвейеру. Все ошибки глотаются — конвейер не падает.
"""
from __future__ import annotations

import logging

import requests

from ..models import Vacancy

log = logging.getLogger(__name__)

BASE = "https://hire.am"


def _dns_ok() -> bool:
    try:
        import socket
        socket.setdefaulttimeout(5)
        socket.gethostbyname("hire.am")
        return True
    except Exception:  # noqa: BLE001
        return False


def scrape(session: requests.Session) -> list[Vacancy]:
    if not _dns_ok():
        log.info("hire.am: домен не резолвится (сайт не работает) — пропускаем быстро")
        return []
    try:
        r = session.get(BASE + "/jobs", timeout=20)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        log.warning("hire.am: недоступен (%s) — пропускаем", e.__class__.__name__)
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("hire.am: неожиданная ошибка: %s — пропускаем", e)
        return []

    # Сайт оживёт — попробуем хотя бы ссылки на карточки.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "lxml")
    out: list[Vacancy] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 4:
            continue
        if any(k in href for k in ("/job/", "/vacancy/", "/jobs/")) and href not in seen:
            seen.add(href)
            url = href if href.startswith("http") else BASE + href
            ext_id = abs(hash(url)) % 10**10
            out.append(Vacancy(
                source="hire",
                uid=f"hire:{ext_id}",
                ext_id=str(ext_id),
                title_orig=text[:200],
                url=url,
            ))
    log.info("hire.am: собрано %d карточек", len(out))
    return out
