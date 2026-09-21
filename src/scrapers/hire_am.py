"""hire.am — старый Jobberbase v1.9 (серверный PHP, без JS-рендеринга).

Жив по http (https/датацентровые IP капризничают — поэтому WARP + DoH-фолбэк).
Структура известна точно:
  - категории:   http://www.hire.am/jobs/{cat}/   (it, hr, pr, transport, ...)
  - пагинация:   /jobs/{cat}/?p=N (свежие сверху, id растут)
  - карточки:    /job/{id}/{slug}/
  - RSS:         /rss/all/ (фолбэк, если категории не отвечают)
Строка категории содержит всё: "TITLE ... at COMPANY in CITY ... DD-MM-YYYY".
Все ошибки глотаются — конвейер не падает.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from html import unescape
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from ..config import HIRE_MAX_ITEMS, HIRE_TIME_BUDGET, SLEEP_BETWEEN_REQUESTS
from ..models import Vacancy

log = logging.getLogger(__name__)

HOST = "hire.am"
BASES = ("http://www.hire.am", "http://hire.am", "https://www.hire.am", "https://hire.am")
DOH_ENDPOINTS = (
    "https://dns.google/resolve",
    "https://cloudflare-dns.com/dns-query",
)

CATEGORIES = {
    "it": "IT", "hr": "HR", "pr": "PR", "transport": "Транспорт",
    "managers": "Менеджмент", "accounting": "Бухгалтерия",
    "medicine": "Медицина", "sales": "Продажи", "other": "Другое",
}
ITEM_RE = re.compile(r"/job/(\d+)")
PAGES_PER_CAT = 12          # страниц на категорию максимум
TIME_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")


def _looks_html(text: str) -> bool:
    low = (text or "")[:2000].lower()
    return ("<html" in low or "<body" in low or "<a " in low or "<div" in low) \
        and "just a moment" not in low


def _no_retry_session(s: requests.Session) -> requests.Session:
    """Копия сессии (с прокси) без urllib3-ретраев: недоступный сайт не должен
    съедать 3 попытки × таймаут на каждый URL."""
    ns = requests.Session()
    ns.headers.update(s.headers)
    ns.proxies.update(s.proxies)
    ns.mount("http://", HTTPAdapter(max_retries=0))
    ns.mount("https://", HTTPAdapter(max_retries=0))
    return ns


def _doh_resolve(session: requests.Session) -> str | None:
    """A-запись hire.am через DoH-JSON (работает даже когда локальный DNS молчит)."""
    for ep in DOH_ENDPOINTS:
        try:
            r = session.get(
                ep, params={"name": HOST, "type": "A"},
                headers={"accept": "application/dns-json"}, timeout=10)
            for ans in r.json().get("Answer", []):
                if ans.get("type") == 1 and ans.get("data"):
                    return ans["data"]
        except Exception as e:  # noqa: BLE001
            log.debug("hire.am: DoH %s не сработал: %s", ep, e)
    return None


class _Site:
    """Хелпер доступа к hire.am с фолбэком DNS и IP-режимом."""

    def __init__(self, session: requests.Session):
        self.s = session
        self.base: str | None = None
        self.ip_mode = False
        self.ip: str | None = None

    def _headers(self) -> dict | None:
        return {"Host": HOST} if self.ip_mode else None

    def _rewrite_to_ip(self, url: str) -> str:
        p = urlparse(url)
        if p.netloc and p.netloc != self.ip:
            return url.replace(f"{p.scheme}://{p.netloc}", f"{p.scheme}://{self.ip}", 1)
        return url

    def get(self, url: str, timeout: int = 25) -> requests.Response:
        """GET с ручным проходом редиректов в IP-режиме."""
        if self.ip_mode:
            url = self._rewrite_to_ip(url)
            for _ in range(4):
                r = self.s.get(url, timeout=timeout, headers=self._headers(),
                               allow_redirects=False)
                loc = r.headers.get("Location") if 300 <= r.status_code < 400 else None
                if not loc:
                    return r
                url = self._rewrite_to_ip(urljoin(url, loc))
            return r
        return self.s.get(url, timeout=timeout, allow_redirects=True)

    def connect(self) -> bool:
        # два круга по базам: у hire.am бывают секундные флаки (прошлый прогон
        # через тот же WARP отдавал 501 вакансий, следующий — ConnectionError)
        for attempt in (1, 2):
            for base in BASES:
                try:
                    r = self.s.get(base + "/", timeout=20, allow_redirects=True)
                    if r.ok and _looks_html(r.text):
                        self.base = base.rstrip("/")
                        log.info("hire.am: отвечает на %s", self.base)
                        return True
                    log.info("hire.am: %s ответил HTTP %s без HTML", base, r.status_code)
                except Exception as e:  # noqa: BLE001
                    log.info("hire.am: %s недоступен (%s)", base, e.__class__.__name__)
            if attempt == 1:
                log.info("hire.am: первая попытка не удалась — ждём 7с и пробуем ещё раз")
                time.sleep(7)
        self.ip = _doh_resolve(self.s)
        if not self.ip:
            log.warning("hire.am: DNS не резолвится ни напрямую, ни через DoH — пропуск")
            return False
        log.info("hire.am: DNS через DoH -> %s, пробуем IP-режим", self.ip)
        for scheme in ("http", "https"):
            try:
                r = self.s.get(f"{scheme}://{self.ip}/", timeout=20,
                               headers={"Host": HOST}, allow_redirects=False)
                log.info("hire.am: IP-режим %s://%s -> HTTP %s", scheme, self.ip, r.status_code)
                if r.ok and _looks_html(r.text):
                    self.ip_mode = True
                    self.base = f"{scheme}://{self.ip}"
                    log.info("hire.am: IP-режим работает (%s)", self.base)
                    return True
            except Exception as e:  # noqa: BLE001
                log.info("hire.am: %s://%s не отвечает (%s)", scheme, self.ip,
                         e.__class__.__name__)
        log.warning("hire.am: сайт не отвечает даже по IP — пропуск")
        return False


def _clean(s: str) -> str:
    s = unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip(" .,-")


def _parse_row(div, category: str) -> Vacancy | None:
    """Одна строка-карточка со страницы категории."""
    info = div.find("span", class_="row-info")
    a = info.find("a", href=ITEM_RE.search) if info else None
    if not a:
        return None
    href = a.get("href", "")
    m = ITEM_RE.search(href)
    if not m:
        return None
    ext_id = m.group(1)
    title = (a.get("title") or a.get_text(strip=True) or "").strip()
    if not title or title.lower() == "jobber":
        return None

    raw = str(info)
    company = city = ""
    is_remote = False
    # "... </a> <span class="la">at</span> COMPANY <span class="la">in</span> CITY ..."
    mm = re.search(
        r"</a>\s*<span class=\"la\">at</span>(.*?)"
        r"(?:<span class=\"la\">in</span>(.*?))?(?:</span>|$)", raw, re.S)
    if mm:
        company = _clean(mm.group(1))
        city = _clean(mm.group(2) or "")
        # вариант без "in": "COMPANY, Anywhere" / "COMPANY, Город" — переносим хвост
        if not city and "," in company:
            from ..geo import classify
            prefix, tail = company.rsplit(",", 1)
            tail = tail.strip()
            tc = classify(tail)
            if tc == "remote":
                company, city, is_remote = prefix.strip(), "", True
            elif tc == "armenia":
                company, city = prefix.strip(), tail

    if city.lower() in ("anywhere", "any where", "home office", "home-based", "remote"):
        is_remote = True
        city = ""

    posted = None
    tm = TIME_RE.search(str(div))
    if tm:
        try:
            posted = datetime.strptime(f"{tm.group(3)}-{tm.group(2)}-{tm.group(1)}",
                                       "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass

    url = href if href.startswith("http") else f"http://www.{HOST}{href}"
    return Vacancy(
        source="hire",
        uid=f"hire:{ext_id}",
        ext_id=ext_id,
        title_orig=title[:200],
        city=city,
        company=company,
        category=category,
        is_remote=is_remote,
        url=url,
        posted_at=posted,
    )


def _parse_category_page(html: str, category: str) -> list[Vacancy]:
    soup = BeautifulSoup(html, "lxml")
    out: list[Vacancy] = []
    seen: set[str] = set()
    for div in soup.find_all("div", class_=re.compile(r"^row(-alt)?$")):
        v = _parse_row(div, category)
        if v and v.uid not in seen:
            seen.add(v.uid)
            out.append(v)
    return out


def _rss_fallback(site: _Site) -> list[Vacancy]:
    """Фолбэк: RSS /rss/all/ — заголовки и ссылки (без города/компании)."""
    out: list[Vacancy] = []
    try:
        r = site.get(site.base + "/rss/all/", timeout=25)
        if not r.ok:
            return out
        for m in re.finditer(
                r"<item>.*?</item>", r.text, re.S | re.I):
            block = m.group(0)
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
            l = re.search(r"<link>(.*?)</link>", block, re.S)
            d = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
            title = _clean(t.group(1)) if t else ""
            link = (l.group(1) or "").strip() if l else ""
            if not title or not link:
                continue
            im = ITEM_RE.search(link)
            ext_id = im.group(1) if im else str(abs(hash(link)) % 10**10)
            posted = None
            if d:
                try:
                    from email.utils import parsedate_to_datetime
                    posted = parsedate_to_datetime(d.group(1)).date().isoformat()
                except Exception:  # noqa: BLE001
                    pass
            out.append(Vacancy(
                source="hire", uid=f"hire:{ext_id}", ext_id=ext_id,
                title_orig=title[:200],
                url=link if link.startswith("http") else f"http://www.{HOST}{link}",
                posted_at=posted,
            ))
        log.info("hire.am: RSS-фолбэк -> %d вакансий", len(out))
    except Exception as e:  # noqa: BLE001
        log.warning("hire.am: RSS не получен: %s", e)
    return out


def scrape(session: requests.Session) -> list[Vacancy]:
    started = time.time()
    site = _Site(_no_retry_session(session))
    try:
        if not site.connect():
            return []
    except Exception as e:  # noqa: BLE001
        log.warning("hire.am: подключение не удалось (%s) — пропуск", e)
        return []

    out: list[Vacancy] = []
    seen_ids: set[str] = set()
    statuses: dict[int, int] = {}

    def add(v: Vacancy | None) -> None:
        if v and v.ext_id not in seen_ids:
            seen_ids.add(v.ext_id)
            out.append(v)

    # 1) категории + пагинация
    for cat_slug, cat_name in CATEGORIES.items():
        if len(out) >= HIRE_MAX_ITEMS or time.time() - started > HIRE_TIME_BUDGET:
            break
        page = 1
        got_in_cat = 0
        while page <= PAGES_PER_CAT:
            if len(out) >= HIRE_MAX_ITEMS or time.time() - started > HIRE_TIME_BUDGET:
                break
            url = f"{site.base}/jobs/{cat_slug}/" if page == 1 \
                else f"{site.base}/jobs/{cat_slug}/?p={page}"
            try:
                time.sleep(max(SLEEP_BETWEEN_REQUESTS, 0.5))
                r = site.get(url)
                statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
                if not r.ok or not _looks_html(r.text):
                    break
                rows = _parse_category_page(r.text, cat_name)
                fresh = 0
                for v in rows:
                    if v.ext_id not in seen_ids:
                        fresh += 1
                    add(v)
                got_in_cat += len(rows)
                if not rows or fresh == 0:
                    break  # страницы кончились (или пошли повторы)
                page += 1
            except Exception as e:  # noqa: BLE001
                log.debug("hire.am: %s p=%d не получена: %s", cat_slug, page, e)
                break
        if got_in_cat:
            log.info("hire.am: категория %s -> %d строк (итого %d)",
                     cat_slug, got_in_cat, len(out))

    # 2) фолбэк: RSS
    if not out:
        out = _rss_fallback(site)

    if statuses:
        st = ", ".join(f"{k}×{v}" for k, v in sorted(statuses.items()))
        log.info("hire.am: HTTP-статусы страниц категорий: %s", st)
    log.info("hire.am: собрано %d вакансий за %.0f c", len(out), time.time() - started)
    return out
