"""Telegram-уведомления о новых вакансиях.

Отправляем только дельту (uid, которых нет в state/seen.json).
Вакансии группируются в сообщения по TG_PER_MESSAGE штук,
не более TG_MAX_MESSAGES сообщений за прогон (остальное — сводкой).
"""
from __future__ import annotations

import html
import logging
import time

import requests

from .config import (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                     TG_MAX_MESSAGES, TG_PER_MESSAGE)
from .models import Vacancy, sort_key

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/sendMessage"

SOURCE_NAMES = {
    "staff": "staff.am",
    "worknet": "worknet.am",
    "list": "list.am",
    "hire": "hire.am",
}


def configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _send(token: str, chat_id: str, text: str) -> bool:
    try:
        r = requests.post(
            API.format(token=token),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if r.status_code == 429:  # flood limit
            retry_after = r.json().get("parameters", {}).get("retry_after", 3)
            log.warning("tg: flood limit, ждём %ss", retry_after)
            time.sleep(retry_after + 1)
            return _send(token, chat_id, text)
        if not r.ok:
            log.warning("tg: sendMessage %s: %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("tg: ошибка отправки: %s", e)
        return False


def _esc(s: str) -> str:
    return html.escape(s or "")


def _fmt_vacancy(v: Vacancy) -> str:
    title = _esc(v.title_ru or v.title_orig)
    parts = [f'🔹 <a href="{_esc(v.url)}"><b>{title}</b></a>']
    if v.title_ru and v.title_ru != v.title_orig:
        parts.append(f'   ({_esc(v.title_orig)})')
    meta = []
    if v.salary:
        meta.append(f"💰 {_esc(v.salary)}")
    if v.city:
        meta.append(f"📍 {_esc(v.city)}")
    if v.company:
        meta.append(f"🏢 {_esc(v.company)}")
    if v.is_remote:
        meta.append("🖥 удалённо")
    if meta:
        parts.append("   " + " | ".join(meta))
    parts.append(f"   ↗ {SOURCE_NAMES.get(v.source, v.source)}")
    return "\n".join(parts)


def notify_new(vacancies: list[Vacancy]) -> int:
    """Шлёт новые вакансии. Возвращает число реально отправленных вакансий."""
    if not configured():
        log.info("tg: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не заданы — уведомления пропущены")
        return 0

    fresh = sorted(vacancies, key=sort_key)
    if not fresh:
        log.info("tg: новых вакансий нет")
        return 0

    header = f"🆕 <b>Новые вакансии в Армении: {len(fresh)}</b>\n\n"
    messages: list[str] = []
    chunk: list[str] = []
    for v in fresh:
        chunk.append(_fmt_vacancy(v))
        if len(chunk) >= TG_PER_MESSAGE:
            messages.append("\n\n".join(chunk))
            chunk = []
    if chunk:
        messages.append("\n\n".join(chunk))

    sent = 0
    limit = min(len(messages), TG_MAX_MESSAGES)
    if len(messages) > TG_MAX_MESSAGES:
        rest = len(fresh) - sum(m.count("🔹") for m in messages[:limit])
        messages = messages[:limit]
        messages[-1] += f"\n\n…и ещё {rest} вакансий — смотрите Excel/дашборд"

    for i, msg in enumerate(messages, 1):
        text = (header if i == 1 else "") + msg
        if _send(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, text):
            sent += msg.count("🔹")
            log.info("tg: отправлено сообщение %d/%d", i, len(messages))
        time.sleep(1.2)  # вежливость к rate limit (30 msg/s, но мы скромнее)

    return sent
