"""worknet.am — платформа вакансий (в т.ч. гос. сектор).

Фронтенд worknet.am — Next.js, но данные он берёт из открытого JSON API:
    https://wback.joby.am/api/public/jobs?page=1&per_page=100
Ответ — стандартная Laravel-пагинация: {current_page, data[], last_page, total}.
Справочники локаций/категорий: /api/categories?group=location|job
(в них есть готовые name_ru, поэтому перевод не нужен).
"""
from __future__ import annotations

import logging
import time

import requests

from ..config import WORKNET_PER_PAGE, SLEEP_BETWEEN_REQUESTS
from ..models import Vacancy
from ..session import polite_get

log = logging.getLogger(__name__)

API = "https://wback.joby.am/api"
SITE = "https://worknet.am"


def _fetch_reference(session: requests.Session, group: str) -> dict[str, str]:
    """id -> человекочитаемое название (ru, при отсутствии en/hy)."""
    ref: dict[str, str] = {}
    try:
        r = polite_get(session, f"{API}/categories", params={"group": group},
                       headers={"Accept": "application/json"})
        r.raise_for_status()
        payload = r.json()
        # API иногда отдаёт голый список, иногда {"data": [...]}
        items = payload if isinstance(payload, list) else payload.get("data", [])
        for item in items:
            name = item.get("name_ru") or item.get("name_en") or item.get("name_hy") or ""
            if name:
                ref[str(item.get("id"))] = name.strip()
    except Exception as e:
        log.warning("worknet: справочник %s недоступен: %s", group, e)
    return ref


def _fmt_salary(raw: str) -> str:
    try:
        val = float(raw)
        if val <= 0:
            return ""
        return f"{int(val):,} AMD".replace(",", " ")
    except (TypeError, ValueError):
        return str(raw) if raw else ""


def scrape(session: requests.Session) -> list[Vacancy]:
    locations = _fetch_reference(session, "location")
    categories = _fetch_reference(session, "job")
    time.sleep(SLEEP_BETWEEN_REQUESTS)

    out: list[Vacancy] = []
    page = 1
    last_page = 1
    while page <= max(last_page, 1):
        try:
            r = polite_get(session, f"{API}/public/jobs",
                           params={"page": page, "per_page": WORKNET_PER_PAGE},
                           headers={"Accept": "application/json"})
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            log.warning("worknet: страница %s не получена: %s", page, e)
            break

        data = payload.get("data", [])
        last_page = int(payload.get("last_page") or 1)
        for j in data:
            try:
                ext_id = str(j["id"])
                city = locations.get(str(j.get("location") or ""), "")
                category = categories.get(str(j.get("category") or ""), "")
                company = ""
                if isinstance(j.get("company"), dict):
                    company = (j["company"].get("name") or "").strip()
                out.append(Vacancy(
                    source="worknet",
                    uid=f"worknet:{ext_id}",
                    ext_id=ext_id,
                    title_orig=(j.get("title") or "").strip() or "(без названия)",
                    salary=_fmt_salary(j.get("salary")),
                    city=city,
                    company=company,
                    category=category,
                    is_remote=False,
                    url=f"{SITE}/hy/jobs/{ext_id}",
                    posted_at=(j.get("created_at") or "") or None,
                ))
            except Exception:
                log.exception("worknet: не удалось разобрать вакансию")
        log.info("worknet: страница %s/%s -> %d вакансий (итого %d/%s)",
                 page, last_page, len(data), len(out), payload.get("total", "?"))
        if not data:
            break
        page += 1
        time.sleep(SLEEP_BETWEEN_REQUESTS)
    return out
