"""Реестр скраперов."""
from __future__ import annotations

import logging

import requests

from ..config import WARP_PROXY, WARP_SOURCES
from ..geo import filter_foreign
from ..session import make_session
from . import hire_am, list_am, staff_am, worknet_am

log = logging.getLogger(__name__)


def collect_all(session: requests.Session) -> tuple[list, dict]:
    """Запускает все источники, собирает вакансии и статистику.

    Ошибка одного источника никогда не валит остальные.
    Источники из WARP_SOURCES идут через WARP-прокси (если он поднят),
    остальные — напрямую.
    """
    jobs: list = []
    stats: dict[str, str] = {}

    runners = {
        "staff": staff_am.scrape,
        "worknet": worknet_am.scrape,
        "list": list_am.scrape,
        "hire": hire_am.scrape,
    }

    warp_sessions: dict[str, requests.Session] = {}
    for name, fn in runners.items():
        try:
            sess = session
            if name in WARP_SOURCES and WARP_PROXY:
                if name not in warp_sessions:
                    warp_sessions[name] = make_session(use_warp=True)
                sess = warp_sessions[name]
            found = fn(sess)
            jobs.extend(found)
            stats[name] = f"{len(found)} вакансий"
            log.info("[OK] %s: %d", name, len(found))
        except Exception as e:  # noqa: BLE001
            stats[name] = f"ОШИБКА: {e.__class__.__name__}: {e}"
            log.exception("источник %s упал", name)

    # глобальная дедупликация по uid
    seen: set[str] = set()
    uniq: list = []
    for v in jobs:
        if v.uid not in seen:
            seen.add(v.uid)
            uniq.append(v)

    # гео-фильтр: брату нужна работа в Армении — зарубежное выбрасываем
    uniq, geo_stats = filter_foreign(uniq)
    stats["гео-фильтр"] = (
        f"отсеяно {geo_stats['dropped']} зарубежных · "
        f"{geo_stats['remote']} удалёнка · {geo_stats['empty_city']} без локации"
    )
    stats["warp"] = (f"включён для: {', '.join(sorted(WARP_SOURCES))}"
                     if WARP_PROXY else "выключен (WARP_PROXY не задан)")

    return uniq, stats
