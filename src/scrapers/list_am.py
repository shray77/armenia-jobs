"""list.am — армянский «Авито», раздел вакансий category/79.

⚠️ Сайт целиком за Cloudflare. С датацентровых IP (GitHub Actions,
облачные VPS) Cloudflare отдаёт challenge «Just a moment...» и не пускает.
Поэтому:
  1) пробуем cloudscraper (иногда проходит);
  2) если нет — мягко сдаёмся и возвращаем пустой список, конвейер живёт
     на остальных источниках.
Парсер написан устойчиво к вёрстке: ищем все ссылки вида /item/<id>.
"""
from __future__ import annotations

import logging
import re
import time

from bs4 import BeautifulSoup

from ..config import LIST_MAX_PAGES, SLEEP_BETWEEN_REQUESTS
from ..models import Vacancy

log = logging.getLogger(__name__)

BASE = "https://www.list.am"
CATEGORY_URL = BASE + "/category/79"

CF_MARKERS = ("just a moment", "cf-challenge", "challenges.cloudflare.com")
ITEM_RE = re.compile(r"/item/(\d+)")
SALARY_RE = re.compile(r"(\d[\d ,.\u0589]*)(֏|\$|₽|amd|usd|rur)", re.I)


def _make_scraper(session):
    """cloudscraper с теми же заголовками; при недоступности — обычная сессия."""
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False})
        # наследуем прокси из окружения/сессии, если заданы
        scraper.proxies.update(session.proxies)
        return scraper
    except Exception as e:
        log.warning("list.am: cloudscraper недоступен (%s), пробуем plain requests", e)
        return session


def _is_cf_page(html: str) -> bool:
    low = html[:4000].lower()
    return any(m in low for m in CF_MARKERS) and "/item/" not in html


def _parse_list_page(html: str) -> list[tuple[str, str, str, str]]:
    """(ext_id, title, salary, url) со страницы списка."""
    soup = BeautifulSoup(html, "lxml")
    items: list[tuple[str, str, str, str]] = []
    for a in soup.find_all("a", href=ITEM_RE.search):
        href = a.get("href", "")
        m = ITEM_RE.search(href)
        if not m:
            continue
        ext_id = m.group(1)
        text = a.get_text(" ", strip=True) or ""
        # Типичная карточка list.am: "Заголовок   город   цена"
        # цена начинается с цифры/валюты — вычленяем эвристикой
        salary = ""
        sm = SALARY_RE.search(text)
        if sm and sm.start() > 3:
            salary = f"{sm.group(1).strip()} {sm.group(2).strip()}"
            text = text[:sm.start()].strip()
        title = text
        if not title:
            continue
        url = href if href.startswith("http") else BASE + href
        items.append((ext_id, title, salary, url))
    return items


def scrape(session, max_pages: int = LIST_MAX_PAGES) -> list[Vacancy]:
    scraper = _make_scraper(session)
    out: list[Vacancy] = []
    seen_ids: set[str] = set()
    blocked = False

    for page in range(1, max_pages + 1):
        url = CATEGORY_URL if page == 1 else f"{CATEGORY_URL}?page={page}"
        try:
            r = scraper.get(url, timeout=40)
        except Exception as e:
            log.warning("list.am: запрос не удался: %s", e)
            break
        if r.status_code == 403 or _is_cf_page(r.text):
            log.warning("list.am: Cloudflare challenge (HTTP %s) — источник "
                        "недоступен с этого IP, пропускаем", r.status_code)
            blocked = True
            break
        items = _parse_list_page(r.text)
        if not items:
            log.info("list.am: страница %s без вакансий (или вёрстка изменилась)", page)
            if page == 1:
                blocked = True  # скорее всего тоже анти-бот, молча выходим
            break
        for ext_id, title, salary, item_url in items:
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)
            out.append(Vacancy(
                source="list",
                uid=f"list:{ext_id}",
                ext_id=ext_id,
                title_orig=title,
                salary=salary,
                city="",   # на list.am город обычно в счётчике справа; извлечь надёжно нельзя
                company="",
                category="",
                is_remote=False,
                url=item_url,
                posted_at=None,
            ))
        log.info("list.am: страница %s -> %d карточек (итого %d)", page, len(items), len(out))
        time.sleep(max(SLEEP_BETWEEN_REQUESTS, 2.0))

    if blocked:
        log.warning("list.am: заблокирован Cloudflare — пропущено. "
                    "Локальный запуск с резидентного IP иногда проходит.")
    return out
