"""hire.am — «странный» сайт: жив по HTTP, но с датацентровых IP отвечает
неохотно, а DNS из датацентров часто вообще не отдаётся.

Скрапер многослойный, каждый слой опционален:
  1. DNS: обычный резолв -> DoH (dns.google / cloudflare-dns) -> IP-режим
     (коннект по IP с заголовком Host: hire.am, редиректы ходим руками).
  2. Схема: сначала http://, затем https:// (по наблюдениям сайт жив по http).
  3. Парсинг устойчив к вёрстке: JSON-LD JobPosting -> og-теги;
     кандидаты: ссылки-паттерны (/job|/vacanc|/career|/post) + sitemap.xml.
Все ошибки глотаются — конвейер не падает, источник просто вернёт 0.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup

from ..config import HIRE_MAX_ITEMS, HIRE_TIME_BUDGET, SLEEP_BETWEEN_REQUESTS
from ..models import Vacancy

log = logging.getLogger(__name__)

HOST = "hire.am"
BASES = ("http://hire.am", "http://www.hire.am", "https://hire.am", "https://www.hire.am")
DOH_ENDPOINTS = (
    "https://dns.google/resolve",
    "https://cloudflare-dns.com/dns-query",
)

JOB_PATH_RE = re.compile(r"/(?:job|jobs|vacanc\w*|career\w*|positions?|post)/", re.I)
SALARY_RE = re.compile(r"(\d[\d ,.\u0589]{0,20})(֏|\$|amd|usd|драм|դրամ)", re.I)
CITY_DISPLAY = {
    "ереван": "Ереван", "yerevan": "Ереван",
    "гюмри": "Гюмри", "gyumri": "Гюмри",
    "ванадзор": "Ванадзор", "vanadzor": "Ванадзор",
}


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
    no_retry = HTTPAdapter(max_retries=0)
    ns.mount("http://", no_retry)
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

    # -- служебное ---------------------------------------------------------
    def _headers(self) -> dict | None:
        return {"Host": HOST} if self.ip_mode else None

    def _rewrite_to_ip(self, url: str) -> str:
        p = urlparse(url)
        if p.netloc and p.netloc != self.ip:
            return url.replace(f"{p.scheme}://{p.netloc}", f"{p.scheme}://{self.ip}", 1)
        return url

    def get(self, url: str, timeout: int = 25) -> requests.Response:
        """GET с ручным проходом редиректов в IP-режиме (Location с доменом
        мы тоже заворачиваем на IP)."""
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

    # -- подключение ---------------------------------------------------------
    def connect(self) -> bool:
        for base in BASES:
            try:
                r = self.s.get(base + "/", timeout=20, allow_redirects=True)
                if r.ok and _looks_html(r.text):
                    self.base = base.rstrip("/")
                    log.info("hire.am: отвечает на %s", self.base)
                    return True
            except Exception as e:  # noqa: BLE001
                log.info("hire.am: %s недоступен (%s)", base, e.__class__.__name__)
        # IP-режим: резолвим через DoH и коннектимся напрямую по адресу
        self.ip = _doh_resolve(self.s)
        if not self.ip:
            log.warning("hire.am: DNS не резолвится ни напрямую, ни через DoH — пропуск")
            return False
        log.info("hire.am: DNS через DoH -> %s, пробуем IP-режим с Host-заголовком", self.ip)
        for scheme in ("http", "https"):
            try:
                r = self.s.get(f"{scheme}://{self.ip}/", timeout=20,
                               headers={"Host": HOST}, allow_redirects=False)
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

    # -- сбор кандидатов -----------------------------------------------------
    def links_from_html(self, html: str) -> set[str]:
        """Относительные пути страниц-вакансий из всех <a href>."""
        out: set[str] = set()
        for m in re.finditer(r"""href\s*=\s*["']([^"'#\s]+)["']""", html, re.I):
            href = m.group(1).strip()
            if href.startswith(("javascript:", "mailto:", "tel:", "data:")):
                continue
            full = urljoin(self.base + "/", href)
            p = urlparse(full)
            if p.netloc and HOST not in p.netloc and p.netloc != self.ip:
                continue
            if JOB_PATH_RE.search(p.path):
                out.add(p.path)
        return out

    def urls_from_sitemaps(self) -> set[str]:
        """Пути вакансий из sitemap.xml (один уровень индекса)."""
        paths: set[str] = set()
        tried = set()
        queue = ["/sitemap.xml", "/sitemap_index.xml"]
        while queue and len(tried) < 4:
            sm = queue.pop(0)
            if sm in tried:
                continue
            tried.add(sm)
            try:
                r = self.get(sm, timeout=20)
                if not r.ok:
                    continue
                locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text, re.I)[:3000]
                if not locs:
                    continue
                log.info("hire.am: %s -> %d ссылок", sm, len(locs))
                for loc in locs:
                    if loc.endswith(".xml") and "sitemap" in loc.lower():
                        queue.append(loc if loc.startswith("http") else self.base + loc)
                    elif JOB_PATH_RE.search(loc):
                        p = urlparse(loc)
                        paths.add(p.path)
            except Exception as e:  # noqa: BLE001
                log.debug("hire.am: sitemap %s не получен: %s", sm, e)
        return paths


def _parse_jsonld_jobs(html: str, page_url: str) -> list[tuple[dict, str]]:
    """Все JobPosting-объекты со страницы."""
    found: list[tuple[dict, str]] = []
    for block in re.findall(
            r"""<script[^>]*type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
            html, re.I | re.S):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for d in items:
            if not isinstance(d, dict):
                continue
            t = d.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(isinstance(x, str) and x.lower() == "jobposting" for x in types):
                found.append((d, page_url))
            for g in (d.get("@graph") or []):
                if isinstance(g, dict) and str(g.get("@type", "")).lower() == "jobposting":
                    found.append((g, page_url))
    return found


def _vac_from_jsonld(d: dict, fallback_url: str) -> Vacancy | None:
    title = (d.get("title") or d.get("name") or "").strip()
    if not title:
        return None
    # собственная ссылка карточки, если движок её отдал
    jurl = d.get("url") or d.get("@id") or ""
    url = jurl if (isinstance(jurl, str) and jurl.startswith("http")) else fallback_url
    path = urlparse(url).path
    ext_id = hashlib.sha1(path.encode()).hexdigest()[:12]
    org = d.get("hiringOrganization") or {}
    company = (org.get("name") or "").strip() if isinstance(org, dict) else ""

    city = ""
    loc = d.get("jobLocation") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    if isinstance(loc, dict):
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            city = (addr.get("addressLocality") or addr.get("addressRegion") or "").strip()

    posted = d.get("datePosted") or None

    salary = ""
    bs = d.get("baseSalary") or {}
    if isinstance(bs, dict):
        val = bs.get("value") or {}
        if isinstance(val, dict) and val.get("value"):
            unit = (bs.get("unitText") or "").strip()
            salary = f"{val['value']} {unit}".strip()

    return Vacancy(
        source="hire",
        uid=f"hire:{ext_id}",
        ext_id=ext_id,
        title_orig=title[:200],
        salary=salary,
        city=city,
        company=company,
        category="",
        is_remote=bool(re.search(r"remote|удал", title, re.I)),
        url=url,
        posted_at=posted,
    )


def _vac_from_html(html: str, url: str) -> Vacancy | None:
    """Фолбэк без JSON-LD: og:title/h1 + эвристики зарплаты и города."""
    soup = BeautifulSoup(html, "lxml")
    title = ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = og["content"].strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
    if not title or len(title) < 3:
        return None

    text = soup.get_text(" ", strip=True)[:2000]
    salary = ""
    sm = SALARY_RE.search(text)
    if sm:
        salary = f"{sm.group(1).strip()} {sm.group(2).strip()}"

    city = ""
    low = text.lower()
    for hint, display in CITY_DISPLAY.items():
        if hint in low:
            city = display
            break

    return Vacancy(
        source="hire",
        uid="hire:" + hashlib.sha1(urlparse(url).path.encode()).hexdigest()[:12],
        ext_id=hashlib.sha1(urlparse(url).path.encode()).hexdigest()[:12],
        title_orig=title[:200],
        salary=salary,
        city=city,
        is_remote=bool(re.search(r"remote|удал", title, re.I)),
        url=url,
    )


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
    seen_uids: set[str] = set()

    def add(v: Vacancy | None) -> None:
        if v and v.uid not in seen_uids:
            seen_uids.add(v.uid)
            out.append(v)

    # 1) главная -> JSON-LD + ссылки
    candidates: list[str] = []
    try:
        r = site.get(site.base + "/")
        if r.ok:
            for d, _ in _parse_jsonld_jobs(r.text, site.base + "/"):
                v = _vac_from_jsonld(d, site.base + "/")
                # без собственной ссылки вакансию не добавляем (иначе получим
                # «вакансию» с uid главной страницы)
                if v and v.url != site.base + "/":
                    add(v)
            candidates.extend(site.links_from_html(r.text))
            log.info("hire.am: главная -> %d кандидатов-ссылок, %d json-ld вакансий",
                     len(candidates), len(out))
    except Exception as e:  # noqa: BLE001
        log.warning("hire.am: главная не разобралась: %s", e)

    # 2) sitemap
    try:
        for path in site.urls_from_sitemaps():
            if path not in candidates:
                candidates.append(path)
        log.info("hire.am: кандидатов после sitemap: %d", len(candidates))
    except Exception as e:  # noqa: BLE001
        log.debug("hire.am: sitemap пропущен: %s", e)

    if not candidates:
        try:
            r = site.get(site.base + "/")
            snippet = re.sub(r"\s+", " ", (r.text or "")[:300])
            log.info("hire.am: 0 кандидатов; начало главной: %s", snippet)
        except Exception:
            pass
        return out

    # 3) обходим карточки (лимит + тайм-бюджет + вежливая пауза)
    fetch = 0
    for path in candidates:
        if len(out) >= HIRE_MAX_ITEMS or time.time() - started > HIRE_TIME_BUDGET:
            log.info("hire.am: лимит достигнут (%d вакансий / %.0f c)",
                     len(out), time.time() - started)
            break
        url = site.base + path
        try:
            time.sleep(max(SLEEP_BETWEEN_REQUESTS, 0.5))
            r = site.get(url)
            if not r.ok or not _looks_html(r.text):
                continue
            fetch += 1
            for d, _ in _parse_jsonld_jobs(r.text, url):
                v = _vac_from_jsonld(d, url)
                if v:
                    add(v)
                    break
            # json-ld нет — og-фолбэк, если карточка ещё не добавлена
            if not any(o.url == url for o in out):
                v = _vac_from_html(r.text, url)
                if v:
                    add(v)
        except Exception as e:  # noqa: BLE001
            log.debug("hire.am: карточка %s не разобралась: %s", path, e)

    log.info("hire.am: собрано %d вакансий (просмотрено карточек: %d, кандидатов: %d)",
             len(out), fetch, len(candidates))
    return out
