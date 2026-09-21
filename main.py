#!/usr/bin/env python3
"""Агрегатор вакансий Армении.

Конвейер: сбор (staff.am, worknet.am, list.am, hire.am)
  → перевод армянских названий на русский
  → Excel (output/vacancies.xlsx)
  → дашборд (output/index.html для GitHub Pages)
  → Telegram-уведомления о новых вакансиях (дельта по state/seen.json)

Запускается локально или по крону в GitHub Actions.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from src.scrapers import collect_all
from src.session import make_session
from src.translate import translate_vacancies
from src.storage import load_seen, save_seen, diff_new, mark_seen, save_latest
from src.excel import build_excel
from src.dashboard import build_dashboard
from src.telegram_notify import notify_new

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def github_summary(text: str) -> None:
    """Если работаем в GitHub Actions — пишем в Step Summary."""
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


def main() -> int:
    started = datetime.now(timezone.utc)
    log.info("=== Сбор вакансий Армении, старт %s ===", started.strftime("%d.%m.%Y %H:%M UTC"))

    session = make_session()

    # 1. Сбор
    vacancies, stats = collect_all(session)
    log.info("итого собрано уникальных вакансий: %d", len(vacancies))

    if not vacancies:
        log.error("ни один источник не вернул вакансии — проверьте сеть/структуру сайтов")
        github_summary("## ❌ Вакансии не собраны\n\nВсе источники вернули пусто или упали.\n")
        return 1

    # 2. Сразу сохраняем сырой срез — данные не потеряются,
    #    даже если перевод/уведомления упадут
    save_latest(vacancies)

    # 3. Перевод
    translate_vacancies(vacancies)
    save_latest(vacancies)

    # 4. Excel
    build_excel(vacancies)

    # 5. Дашборд
    build_dashboard(vacancies, stats)

    # 6. Telegram: только новые; зарубежные не шлём (брату нужна работа в
    #    Армении), но помечаем как показанные — чтобы не всплывали каждый прогон
    seen = load_seen()
    fresh = diff_new(vacancies, seen)
    tg_fresh = [v for v in fresh if v.geo != "foreign"]
    log.info("новых вакансий с прошлого запуска: %d (в TG: %d после отсечки заграницы)",
             len(fresh), len(tg_fresh))
    sent = notify_new(tg_fresh)

    # помечаем как показанные все собранные (не только отправленные),
    # иначе при большом притоке TG-спам будет бесконечным
    mark_seen(seen, vacancies)
    # но ограничиваем рост файла: храним максимум 20 000 последних uid
    if len(seen) > 20000:
        items = sorted(seen.items(), key=lambda kv: kv[1])[-20000:]
        seen = dict(items)
    save_seen(seen)

    # Сводка
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    lines = ["## ✅ Сбор вакансий завершён", "",
             f"**Всего вакансий:** {len(vacancies)} · **новых:** {len(fresh)} · "
             f"**отправлено в TG:** {sent} · **время:** {elapsed:.0f} c", "",
             "| Источник | Результат |", "|---|---|"]
    for name, res in stats.items():
        lines.append(f"| {name} | {res} |")
    summary = "\n".join(lines) + "\n"
    github_summary(summary)
    print("\n" + summary)

    log.info("=== Готово за %.0f c ===", elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
