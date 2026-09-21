"""Гео-фильтр: брату нужна работа в Армении, зарубежные вакансии не нужны.

Логика классификации локации (поле city, ДО перевода):
  - пустая          -> оставляем (сайт армянский, локация не указана — скорее всего Ереван)
  - «удалённо»      -> оставляем, помечаем is_remote (работать можно и из Еревана)
  - город Армении   -> оставляем
  - зарубежный хинт -> ВЫБРАСЫВАЕМ
  - неизвестное     -> оставляем, но пишем в лог (список уточняется по логам)

Совпадения ищутся по словоформам ru/en/hy (армянский включён, т.к. фильтр
работает до перевода).
"""
from __future__ import annotations

import logging
import re
from collections import Counter

log = logging.getLogger(__name__)

# --- города/регионы Армении: ru + en + hy ---------------------------------
ARMENIA_HINTS: tuple[str, ...] = (
    # страна целиком
    "армения", "armenia", "հայաստան", "hayastan",
    # Ереван
    "ереван", "yerevan", "երևան", "ереван",
    # крупнейшие города
    "гюмри", "gyumri", "գյումրի",
    "ванадзор", "vanadzor", "վանաձոր",
    "раздан", "hrazdan", "հրազդան",
    "абовян", "abovyan", "աբովյան",
    "эчмиадзин", "ejmiatsin", "etchmiadzin", "էջմիածին",
    "вагаршапат", "vagharshapat", "վաղարշապատ",
    "аштарак", "ashtarak", "աշտարակ",
    "армавир", "armavir", "արմավիր",
    "арарат", "ararat", "արարատ",
    "арташат", "artashat", "արտաշատ",
    "малишика", "мргашат", "mrgashat",
    "капан", "kapan", "կապան",
    "горис", "goris", "գորիս",
    "сисиан", "sisian", "սիսիան",
    "мегри", "meghri", "megri", "մեղրի",
    "гавар", "gavar", "գավառ",
    "севан", "sevan", "սևան",
    "мартуни", "martuni", "մարտունի",
    "варденис", "vardenis", "վարդենիս",
    "иджеван", "ijevan", "իջևան",
    "дилижан", "dilijan", "դիլիջան",
    "ноемберян", "noyemberyan", "նոյեմբերյան",
    "берд", "berd", "բերդ",
    "алаверди", "alaverdi", "ալավերդի",
    "спитак", "spitak", "սպիտակ",
    "степанаван", "stepanavan", "ստեփանավան",
    "ташир", "tashir", "տաշիր",
    "чаренцаван", "charentsavan", "չարենցավան",
    "бюрегаван", "byureghavan", "բյուրեղավան",
    "веди", "vedi", "վեդի",
    "мецамор", "metsamor", "մեծամոր",
    "маралик", "maralik", "մարալիկ",
    "джермук", "jermuk", "ջերմուկ",
    "цахкадзор", "tsaghkadzor", "tsakhkadzor", "ծաղկաձոր",
    "агарак", "agarak", "ագարակ",
    "ахтала", "ahtala", "ախտալա",
    "шамлуг", "shamlugh", "shamlug", "շամլուղ",
    "ариндж", "arindj", "առինջ",
    "птхни", "ptghni",
    "нор-гехи", "нор гехи", "nor geghi",
    "байбурт", "bayburd", "բայբուրդ",
    # варианты написания и малые города (по фактическим логам)
    "вахаршапат", "вагаршапат", "vagharshapat",
    "дилиджан", "dilidjan",
    "прошян", "proshyan", "պռոշյան",
    "балаовит", "balaovit", "բալաովիտ",
    "апаран", "aparan", "ապարան",
    "вайк", "vaik", "վայք",
    "масис", "masis", "մասիս",
    "каджаран", "kadzharan", "kajaran",
    "егвард", "yeghvard", "eghward", "եղվարդ",
    "мехри", "мехран",
    "айнтап", "ayntap", "այնտապ",
    "ехегнадзор", "егегнадзор", "yeghegnadzor", "եղեգնաձոր",
    "артик", "artik", "արթիկ",
    "арзни", "arzni", "արզնի",
    "памбак", "pambak",
    "гугарк", "gugark",
    "давташен", "davtashen",
    "арабкир", "arabkir", "արաբկիր",
    "нор норк", "nor nork",
    "гогаван", "gogavan", "գոգավան",
    "кохб", "kogh", "koghb", "կողբ",
    "чамбарак", "chambarak", "ճամբարակ",
    "мхчян", "mkhchyan", "մխչյան",
    # области (марзы)
    "ширак", "shirak", "շիրակ",
    "лорри", "лори", "lori", "լոռի",
    "тавуш", "tavush", "տավուշ",
    "котайк", "kotayk", "կոտայք",
    "гегаркуник", "gegharkunik", "գեղարքունիք",
    "сюник", "syunik", "սյունիք",
    "вайоц-дзор", "вайоц дзор", "vayots dzor", "vayots-dzor", "վայոց ձոր",
    "арагацотн", "aragatsotn", "արագածոտն",
)

# --- зарубежные хинты ------------------------------------------------------
FOREIGN_HINTS: tuple[str, ...] = (
    # Россия/СНГ
    "москва", "moscow", "московск", "москв", "мocкв",
    "санкт-петербург", "санкт петербург", "saint petersburg", "st petersburg", "спб", "питер",
    "росси", "russia", "russian", "ռուսաստան",
    "беларус", "минск", "belarus", "minsk",
    "казахстан", "алматы", "астана", "kazakhstan", "almaty",
    "украин", "киев", "ukraine", "kyiv", "kiev",
    # Закавказье
    "грузия", "georgia", "тбилиси", "tbilisi", "թբիլիսի", "վրաստան",
    "батуми", "batumi", "кутаиси", "kutaisi", "рустави",
    "азербайджан", "азер", "баку", "baku", "azerbaijan", "բաքու",
    # Ближний Восток / Азия
    "дубай", "dubai", "оаэ", "uae", "emirates", "абу-даби", "abu dhabi",
    "турция", "turkey", "турци", "istanbul", "стамбул", "анкара", "ankara", "թուրքիա",
    "ирани", "иран", "iran", "tehran", "тегеран",
    "исраил", "израил", "israel", "тель-авив",
    # Запад
    "сша", "usa", "united states", "америк", "america",
    "европ", "europe", "германи", "germany", "берлин", "berlin",
    "мюнхен", "франкфурт", "munich", "frankfurt",
    "лондон", "london", "париж", "paris", "франци", "france",
    "испани", "spain", "итали", "italy", "милан", "рим",
    "польш", "poland", "варшав", "warsaw", "вроцлав", "краков",
    "нидерланд", "амстердам", "netherlands", "amsterdam",
    "бельги", "брюссель", "belgium", "brussels",
    "швейцари", "цюрих", "switzerland", "zurich", "swiss",
    "австри", "вена", "austria", "vienna",
    "чехи", "праг", "czech", "prague",
    "norway", "норвег", "швец", "sweden", "швеци", "стокгольм",
    "кита", "china", "шанхай", "пекин", "индия", "india",
    "канад", "canada", "торонт", "toronto", "ванкув",
    "нью-йорк", "new york", "лос-анджелес", "los angeles",
    "авентура", "aventura", "флорида", "florida", "майами", "miami",
    "бостон", "boston", "чикаго", "chicago", "даллас", "dallas",
    "калифорни", "california", "техас", "texas", "нью-джерси", "new jersey",
    "шэньчжэнь", "shenzhen", "сан-диего", "san diego", "сиэттл", "seattle",
)

# аккуратно: «груз» может совпасть с «грузчик» — убираем его, оставляем точные
FOREIGN_HINTS = tuple(h for h in FOREIGN_HINTS if h != "груз")

# Подстраховка для вакансий БЕЗ города: заграница часто прячется в заголовке
# («Хлебная мастерская в РФ, Москва»), а город у hire.am чаще всего пустой.
# Здесь только однозначные топонимы/маркеры: никакой языковой лексики
# («Russian speaking», «German Language Instructor» — это работа в Ереване),
# и без «сша/америк» (рынок США у армянской компании — легитимная вакансия).
FOREIGN_TITLE_HINTS: tuple[str, ...] = (
    "рф", "москва", "московск", "мocкв", "moscow",
    "санкт-петербург", "санкт петербург", "saint petersburg",
    "тбилиси", "tbilisi", "батуми", "batumi", "баку", "baku",
    "дубай", "dubai", "оаэ", "стамбул", "istanbul",
    "нью-йорк", "new york", "лос-анджелес", "los angeles",
    "лондон", "london", "берлин", "berlin", "варшав", "warsaw",
    "за рубеж", "рубежом", "за границ", "abroad",
    # армянские — разметка идёт ДО перевода, и title_orig бывает армянским:
    # «Հացի արտադրամաս ՌԴ, Մոսկվա քաղաքում» (ՌԴ = РФ, Մոսկվա = Москва)
    "ռդ", "մոսկվ", "ռուսաստան", "թբիլիսի", "վրաստան", "բաքու",
    "դուբայ", "ստամբուլ", "լոնդոն", "բեռլին", "նյու յորք",
    "լոս անջելես", "պետերբուրգ",
)

REMOTE_HINTS: tuple[str, ...] = (
    "удалённ", "удаленн", "дистанционн", "remote", "из дома", "home office",
    "հեռակա", "հեռավար", "work from home", "wfh", "anywhere",
)

_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _norm(s: str) -> str:
    """Нижний регистр без пунктуации (чтобы 'Вайоц-Дзор' не резались на '-')."""
    s = (s or "").lower().replace("ё", "е")
    s = _WORD_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _has(text_norm: str, hints: tuple[str, ...]) -> bool:
    """Короткие хинты (<=4) — по границе слова ('веди' != 'проведении'),
    длинные — по подстроке ('росси' ловит 'России')."""
    for h in hints:
        hn = _norm(h)
        if not hn:
            continue
        if len(hn) <= 4:
            if re.search(rf"(?<!\w){re.escape(hn)}(?!\w)", text_norm):
                return True
        elif hn in text_norm:
            return True
    return False


def classify(city: str) -> str:
    """'armenia' | 'foreign' | 'remote' | 'unknown' | 'empty'."""
    c = (city or "").strip()
    if not c:
        return "empty"
    n = _norm(c)
    if _has(n, REMOTE_HINTS):
        return "remote"
    if _has(n, FOREIGN_HINTS):
        return "foreign"
    if _has(n, ARMENIA_HINTS):
        return "armenia"
    return "unknown"


def tag_vacancies(vacancies: list) -> Counter:
    """In-place проставляет v.geo по локации (удалёнка -> is_remote=True).

    Зарубежные вакансии НЕ выбрасываются: они помечаются geo='foreign' и
    скрываются фильтром «Без заграницы» на дашборде, не уходят в Telegram,
    а в Excel помечаются в колонке «Гео».

    Если город пустой/неопознанный — дополнительно сканируем заголовок и
    компанию по FOREIGN_TITLE_HINTS: у hire.am город почти всегда пустой,
    и без этого «…в РФ, Москва» просачивалась бы на дашборд.
    """
    counts: Counter = Counter()
    by_title: Counter = Counter()
    for v in vacancies:
        cat = classify(v.city)
        if cat in ("empty", "unknown"):
            extra = " ".join(
                part for part in (getattr(v, "title_orig", ""),
                                  getattr(v, "title_ru", ""),
                                  getattr(v, "company", "")) if part)
            if extra and _has(_norm(extra), FOREIGN_TITLE_HINTS):
                cat = "foreign"
                by_title[(v.city or "").strip()[:40] or "(без города)"] += 1
        v.geo = cat
        if cat == "remote":
            v.is_remote = True
        counts[cat] += 1
    if by_title:
        top = ", ".join(f"{c}×{n}" for c, n in by_title.most_common(10))
        log.info("гео-разметка: зарубежные по заголовку/компании (город пустой): %s", top)
    log.info("гео-разметка: Армения %d · удалёнка %d · зарубежных %d · "
             "без локации %d · не опознано %d",
             counts["armenia"], counts["remote"], counts["foreign"],
             counts["empty"], counts["unknown"])
    unknown = Counter((v.city or "").strip()[:40] for v in vacancies
                      if v.geo == "unknown")
    if unknown:
        top = ", ".join(f"{c}×{n}" for c, n in unknown.most_common(15))
        log.info("гео-разметка: нераспознанные локации (считаем местными): %s", top)
    foreign = Counter((v.city or "").strip()[:40] for v in vacancies
                      if v.geo == "foreign")
    if foreign:
        top = ", ".join(f"{c}×{n}" for c, n in foreign.most_common(10))
        log.info("гео-разметка: зарубежные локации (скрыты фильтром): %s", top)
    return counts


GEO_RU = {
    "armenia": "Армения",
    "remote": "удалённо",
    "foreign": "заграница",
    "unknown": "не опознано",
    "empty": "",
}


def stats_line(counts: Counter) -> str:
    """Единый формат строки «гео» для сводки/дашборда."""
    return (f"заграница: {counts['foreign']} (скрыты фильтром) · удалёнка: {counts['remote']} · "
            f"без локации: {counts['empty']} · не опознано: {counts['unknown']}")


def filter_foreign(vacancies: list) -> tuple[list, dict]:
    """Убирает вакансии с зарубежной локацией.

    Возвращает (оставшиеся, статистика для логов/сводки):
      dropped, remote, empty_city, unknown_cities (Counter), dropped_cities (Counter)
    """
    kept: list = []
    dropped_cities: Counter = Counter()
    unknown_cities: Counter = Counter()
    n_remote = n_empty = n_dropped = 0

    for v in vacancies:
        cat = classify(v.city)
        if cat == "foreign":
            n_dropped += 1
            dropped_cities[(v.city or "").strip()[:40]] += 1
            continue
        if cat == "remote":
            n_remote += 1
            v.is_remote = True
        elif cat == "empty":
            n_empty += 1
        elif cat == "unknown":
            unknown_cities[(v.city or "").strip()[:40]] += 1
        kept.append(v)

    stats = {
        "dropped": n_dropped,
        "remote": n_remote,
        "empty_city": n_empty,
        "dropped_cities": dropped_cities,
        "unknown_cities": unknown_cities,
    }
    log.info("гео-фильтр: отсеяно %d зарубежных, оставлено %d "
             "(%d удалёнка, %d без локации, %d нераспознанная локация)",
             n_dropped, len(kept), n_remote, n_empty, sum(unknown_cities.values()))
    if dropped_cities:
        top = ", ".join(f"{c}×{n}" for c, n in dropped_cities.most_common(10))
        log.info("гео-фильтр: выброшенные локации: %s", top)
    if unknown_cities:
        top = ", ".join(f"{c}×{n}" for c, n in unknown_cities.most_common(15))
        log.info("гео-фильтр: нераспознанные локации (оставлены): %s", top)
    return kept, stats
