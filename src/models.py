"""Модель вакансии и сериализация."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Vacancy:
    source: str                 # staff | worknet | list | hire
    uid: str                    # уникальный ключ "источник:внешний_id"
    ext_id: str                 # внешний id на сайте-источнике
    title_orig: str             # название как на сайте
    title_ru: str = ""          # перевод на русский (пусто = не требуется/не удалось)
    salary: str = ""            # зарплата как строка (как на сайте)
    city: str = ""              # локация
    company: str = ""
    category: str = ""
    is_remote: bool = False
    url: str = ""
    posted_at: Optional[str] = None  # ISO-строка если известна

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Vacancy":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def sort_key(v: Vacancy):
    """Свежие сверху; без даты — в конец."""
    if not v.posted_at:
        ts = 0
    else:
        try:
            ts = datetime.fromisoformat(v.posted_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            ts = 0
    return (1 if ts else 0, -ts, v.source, v.uid)
