"""Перевод армянских текстов на русский: каскад бесплатных движков.

Стратегия (важно для датацентровых IP, где Google душит 429):
  1. Батч-режим gtx: несколько названий упаковываются в один запрос через
     переводы строк -> в разы меньше запросов. Число строк на выходе
     проверяется; если Google склеил строки, батч отклоняется.
  2. Построчный gtx для остатка.
  3. MyMemory как последний fallback (жёсткий дневной лимит).
Ничего не перевели -> строка остаётся в оригинале (Excel/дашборд это
переживают), а кэш докатывает её на следующих запусках по крону.

Постоянный кэш data/translations_cache.json: армянские должности
повторяются, поэтому после прогревочных прогонов переводы мгновенны.
"""
from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import quote

import requests

from .config import TRANSLATION_CACHE, SLEEP_BETWEEN_TRANSLATIONS

log = logging.getLogger(__name__)

ARMENIAN_RE = re.compile(r"[\u0530-\u058F]")
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

GTX_URL = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
BATCH_CHUNK_CHARS = 1400
BATCH_PAUSE = 1.5

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})


def needs_translation(text: str) -> bool:
    """Перевод нужен только если есть армянские буквы и нет кириллицы."""
    if not text or CYRILLIC_RE.search(text):
        return False
    return bool(ARMENIAN_RE.search(text))


class TranslationCache:
    def __init__(self, path=TRANSLATION_CACHE):
        self.path = path
        self.data: dict[str, str] = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}
        self._dirty = False

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def put(self, key: str, value: str) -> None:
        self.data[key] = value
        self._dirty = True

    def save(self, force: bool = False) -> None:
        if self._dirty or force:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            self._dirty = False


class _Engines:
    """Circuit breaker: движок после серии неудач отключается до конца запуска."""
    gtx_dead = False
    mm_dead = False
    gtx_429_streak = 0


# ---------------------------------------------------------------- gtx ----

def _gtx(text: str, retries: int = 1) -> str | None:
    """Один запрос к бесплатному эндпоинту Google Translate."""
    if _Engines.gtx_dead:
        return None
    for attempt in range(retries + 1):
        try:
            r = _session.get(GTX_URL, params={
                "client": "gtx", "sl": "hy", "tl": "ru", "dt": "t", "q": text,
            }, timeout=15)
            if r.status_code == 429:
                _Engines.gtx_429_streak += 1
                if _Engines.gtx_429_streak >= 3:
                    _Engines.gtx_dead = True
                    log.warning("gtx: IP перегрет (429×%d), отключаемся до следующего запуска",
                                _Engines.gtx_429_streak)
                    return None
                time.sleep(20)
                continue
            if r.ok:
                _Engines.gtx_429_streak = 0
                segs = r.json()[0]
                return "".join(s[0] for s in segs).strip()
            time.sleep(3)
        except Exception as e:  # noqa: BLE001
            log.debug("gtx ошибка: %s", e)
            time.sleep(3)
    return None


def _gtx_batch(lines: list[str]) -> dict[str, str] | None:
    """Пакетный перевод: строки через \\n одним запросом.

    Возвращает {оригинал: перевод} или None, если структура сломалась.
    """
    joined = "\n".join(lines)
    res = _gtx(joined, retries=1)
    if not res or "\n" not in res and len(lines) > 1:
        return None
    parts = res.split("\n")
    if len(parts) != len(lines):
        return None
    return dict(zip(lines, (p.strip() for p in parts)))


# ----------------------------------------------------------- MyMemory ----

def _mymemory(text: str) -> str | None:
    if _Engines.mm_dead:
        return None
    try:
        r = _session.get(MYMEMORY_URL, params={
            "q": text[:500], "langpair": "hy|ru",
        }, timeout=15)
        if r.ok:
            d = r.json()
            status = d.get("responseStatus")
            txt = (d.get("responseData") or {}).get("translatedText") or ""
            if status == 200 and txt and "WARNING" not in txt.upper()[:40]:
                return txt.strip()
            if status == 429:
                _Engines.mm_dead = True  # дневной лимит исчерпан
                log.warning("mymemory: дневной лимит исчерпан, отключаемся")
                return None
    except Exception:  # noqa: BLE001
        pass
    return None


# ------------------------------------------------------------- оркестр ----

def translate_strings(lines: list[str], cache: TranslationCache) -> dict[str, str]:
    """Переводит список уникальных строк. Возврат: {оригинал: перевод}."""
    result: dict[str, str] = {}
    todo = [s for s in dict.fromkeys(lines)
            if needs_translation(s) and cache.get(s) is None]
    for s in lines:
        cached = cache.get(s)
        if cached is not None:
            result[s] = cached
    if not todo:
        return result
    log.info("перевод: %d новых уникальных строк", len(todo))

    # 1) батчи через gtx
    chunk: list[str] = []
    chars = 0
    leftovers: list[str] = []
    for s in todo:
        if len(s) > BATCH_CHUNK_CHARS // 3:  # слишком длинная — отдельно
            leftovers.append(s)
            continue
        if chars + len(s) + 1 > BATCH_CHUNK_CHARS:
            batch = _gtx_batch(chunk)
            if batch:
                result.update(batch)
                for k, v in batch.items():
                    cache.put(k, v)
            else:
                leftovers.extend(chunk)
            chunk, chars = [], 0
            time.sleep(BATCH_PAUSE)
        chunk.append(s)
        chars += len(s) + 1
    if chunk:
        batch = _gtx_batch(chunk)
        if batch:
            result.update(batch)
            for k, v in batch.items():
                cache.put(k, v)
        else:
            leftovers.extend(chunk)
        time.sleep(BATCH_PAUSE)

    cache.save()

    # 2) построчно: gtx, затем MyMemory
    for i, s in enumerate(leftovers, 1):
        ru = _gtx(s)
        if ru is None:
            ru = _mymemory(s)
        if ru:
            result[s] = ru
            cache.put(s, ru)
        if i % 5 == 0:
            cache.save()
        time.sleep(max(SLEEP_BETWEEN_TRANSLATIONS, 0.4))

    cache.save()
    translated = sum(1 for s in todo if result.get(s))
    log.info("перевод: готово %d из %d строк (остальное — на следующих прогонах)",
             translated, len(todo))
    return result


def translate_vacancies(vacancies, cache: TranslationCache | None = None) -> None:
    """In-place проставляет title_ru, чинит армянские city/category."""
    cache = cache or TranslationCache()

    fields = ("title_orig", "city", "category")
    # собираем все уникальные армянские строки из всех полей
    pool: list[str] = []
    for v in vacancies:
        for f in fields:
            s = (getattr(v, f) or "").strip()
            if s and needs_translation(s):
                pool.append(s)
    mapping = translate_strings(pool, cache)

    for v in vacancies:
        t = (v.title_orig or "").strip()
        if t in mapping:
            v.title_ru = mapping[t]
        for f in ("city", "category"):
            s = (getattr(v, f) or "").strip()
            if s in mapping:
                setattr(v, f, mapping[s])

    cache.save()
