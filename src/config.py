"""Глобальная конфигурация парсера вакансий Армении."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

SEEN_FILE = STATE_DIR / "seen.json"          # uid -> first_seen ISO
TRANSLATION_CACHE = DATA_DIR / "translations_cache.json"
LATEST_JSON = DATA_DIR / "latest.json"       # срез всех вакансий для дашборда

EXCEL_FILE = OUTPUT_DIR / "vacancies.xlsx"
DASHBOARD_FILE = OUTPUT_DIR / "index.html"

# --- Telegram -----------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TG_MAX_MESSAGES = int(os.getenv("TG_MAX_MESSAGES", "30"))
TG_PER_MESSAGE = int(os.getenv("TG_PER_MESSAGE", "10"))

# --- Лимиты обхода --------------------------------------------------------
# staff.am: 50 вакансий на страницу, всего ~1200 => 25 страниц
STAFF_MAX_PAGES = int(os.getenv("STAFF_MAX_PAGES", "30"))
# list.am: Cloudflare, трогаем аккуратно и понемногу
LIST_MAX_PAGES = int(os.getenv("LIST_MAX_PAGES", "3"))
WORKNET_PER_PAGE = int(os.getenv("WORKNET_PER_PAGE", "100"))
# hire.am: сколько карточек максимум и сколько секунд максимум за прогон
HIRE_MAX_ITEMS = int(os.getenv("HIRE_MAX_ITEMS", "200"))
HIRE_TIME_BUDGET = int(os.getenv("HIRE_TIME_BUDGET", "240"))

# --- Cloudflare WARP (опционально) -----------------------------------------
# WARP_PROXY задаёт socks5-прокси (wireproxy), например socks5h://127.0.0.1:40000
# WARP_SOURCES — какие источники пускать через прокси (staff.am работает и так)
WARP_PROXY = os.getenv("WARP_PROXY", "").strip()
WARP_SOURCES = {s.strip() for s in os.getenv("WARP_SOURCES", "list,worknet,hire").split(",") if s.strip()}

REQUEST_TIMEOUT = 30
SLEEP_BETWEEN_REQUESTS = float(os.getenv("SLEEP_BETWEEN_REQUESTS", "1.0"))
SLEEP_BETWEEN_TRANSLATIONS = float(os.getenv("SLEEP_BETWEEN_TRANSLATIONS", "0.3"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

SOURCES = ["staff", "worknet", "list", "hire"]
