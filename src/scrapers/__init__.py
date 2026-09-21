"""Реестр скраперов."""
from __future__ import annotations

import logging

import requests

from . import hire_am, list_am, staff_am, worknet_am

log = logging.getLogger(__name__)


def collect_all(session: requests.Session) -> tuple[list, dict]:
    """Запускает все источники, собирает вакансии и статистику.

    Ошибка одного источника никогда не валит остальные.
    """
    jobs: list = []
    stats: dict[str, str] = {}

    runners = {
        "staff": lambda: staff_am.scrape(session),
        "worknet": lambda: worknet_am.scrape(session),
        "list": lambda: list_am.scrape(session),
        "hire": lambda: hire_am.scrape(session),
    }

    for name, fn in runners.items():
        try:
            found = fn()
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
    return uniq, stats
