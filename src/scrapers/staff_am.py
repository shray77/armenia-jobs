"""staff.am — крупнейший джоб-борд Армении (~1200 активных вакансий).

Сайт на Next.js (pages router): каждая страница /jobs?page=N отдаёт
полный JSON со списком вакансий внутри <script id="__NEXT_DATA__">.
"""
from __future__ import annotations

import json
import logging
import re
import time

from ..config import STAFF_MAX_PAGES, SLEEP_BETWEEN_REQUESTS
from ..models import Vacancy
from ..session import polite_get

log = logging.getLogger(__name__)

BASE = "https://staff.am"
LIST_URL = BASE + "/jobs"

# Штатное количество вакансий на страницу staff.am
PER_PAGE = 50


def _pick(d: dict | None, *langs: str) -> str:
    """Достать перевод поля по цепочке языков: ru -> en -> am -> что угодно."""
    if not isinstance(d, dict):
        return ""
    for lang in ("ru", "en", "am", "am_en"):
        v = d.get(lang)
        if isinstance(v, str) and v.strip():
            if lang == "am_en":  # транслит — низший приоритет, но лучше пустоты
                continue
            return v.strip()
    # остался только транслит
    v = d.get("am_en")
    return v.strip() if isinstance(v, str) else ""


def _parse_page(html: str) -> tuple[list[dict], int]:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
        html, re.S,
    )
    if not m:
        return [], 0
    data = json.loads(m.group(1))
    pp = data.get("props", {}).get("pageProps", {})
    return pp.get("jobs") or [], int(pp.get("totalCount") or 0)


def _job_to_vacancy(j: dict) -> Vacancy | None:
    try:
        ext_id = str(j["id"])
        title = _pick(j.get("title")) or "(без названия)"
        slug = _pick(j.get("slug")) or ext_id
        cat_code = (j.get("category") or {}).get("code") or ""
        if cat_code:
            url = f"{BASE}/en/jobs/{cat_code}/{slug}"
        else:
            url = f"{BASE}/en/jobs/{slug}"
        city = _pick((j.get("job_city") or {}).get("title"))
        company = _pick((j.get("companiesStruct") or {}).get("title"))
        category = _pick((j.get("category") or {}).get("title"))
        activated = ((j.get("activated_at") or {}).get("staffam") or "").strip()
        posted = activated.replace(" ", "T") + "+04:00" if activated else None
        return Vacancy(
            source="staff",
            uid=f"staff:{ext_id}",
            ext_id=ext_id,
            title_orig=title,
            salary="",  # staff.am не отдаёт зарплату в списке
            city=city,
            company=company,
            category=category,
            is_remote=bool(j.get("is_remote")),
            url=url,
            posted_at=posted,
        )
    except Exception:  # защита от изменений структуры
        log.exception("staff.am: не удалось разобрать вакансию: %s", str(j)[:200])
        return None


def scrape(session, max_pages: int = STAFF_MAX_PAGES) -> list[Vacancy]:
    out: list[Vacancy] = []
    total = 0
    for page in range(1, max_pages + 1):
        try:
            r = polite_get(session, LIST_URL, params={"page": page},
                           sleep=SLEEP_BETWEEN_REQUESTS)
            r.raise_for_status()
        except Exception as e:
            log.warning("staff.am: страница %s не получена: %s", page, e)
            break
        jobs, total = _parse_page(r.text)
        if not jobs:
            break
        for j in jobs:
            v = _job_to_vacancy(j)
            if v:
                out.append(v)
        log.info("staff.am: страница %s -> %d вакансий (итого %d/%s)",
                 page, len(jobs), len(out), total or "?")
        if total and len(out) >= total:
            break
        time.sleep(0.3)
    # дедуп на всякий случай
    seen, uniq = set(), []
    for v in out:
        if v.uid not in seen:
            seen.add(v.uid)
            uniq.append(v)
    return uniq
