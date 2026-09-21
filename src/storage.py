"""Хранение состояния: seen.json (какие вакансии уже показывали) и latest.json."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .config import SEEN_FILE, LATEST_JSON
from .models import Vacancy

log = logging.getLogger(__name__)


def load_seen() -> dict[str, str]:
    """uid -> ISO-дата первой показанной публикации (в TG)."""
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("seen.json повреждён, начинаем с пустого состояния")
    return {}


def save_seen(seen: dict[str, str]) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(
        json.dumps(seen, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8")
    log.info("seen.json сохранён: %d uid", len(seen))


def diff_new(vacancies: list[Vacancy], seen: dict[str, str]) -> list[Vacancy]:
    """Только те, кого ещё не отправляли в Telegram."""
    return [v for v in vacancies if v.uid not in seen]


def mark_seen(seen: dict[str, str], vacancies: list[Vacancy]) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added = 0
    for v in vacancies:
        if v.uid not in seen:
            seen[v.uid] = now
            added += 1
    return added


def save_latest(vacancies: list[Vacancy]) -> None:
    """Полный срез текущих вакансий для дашборда."""
    LATEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    LATEST_JSON.write_text(
        json.dumps([v.to_dict() for v in vacancies], ensure_ascii=False),
        encoding="utf-8")
    log.info("latest.json: %d вакансий", len(vacancies))
