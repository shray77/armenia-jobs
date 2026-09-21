"""Генерация статического дашборда (output/index.html) для GitHub Pages.

Одиночный HTML-файл: данные инлайнятся как JSON, вся логика на ванильном JS.
Русский интерфейс: поиск, фильтры по источнику/городу/удалёнке, сортировка,
счётчики, ссылка на скачивание vacancies.xlsx.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from html import escape

from .config import DASHBOARD_FILE, EXCEL_FILE
from .models import Vacancy, sort_key

log = logging.getLogger(__name__)


def build_dashboard(vacancies: list[Vacancy], stats: dict[str, str] | None = None) -> None:
    vacancies = sorted(vacancies, key=sort_key)
    data = [v.to_dict() for v in vacancies]
    payload = json.dumps(data, ensure_ascii=False)

    stats = stats or {}
    stats_rows = "".join(
        f"<tr><td>{escape(k)}</td><td>{escape(str(v))}</td></tr>" for k, v in stats.items()
    )
    now = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

    html_doc = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вакансии в Армении — агрегатор</title>
<style>
:root {{
  --bg:#f4f6fa; --card:#ffffff; --ink:#1c2333; --muted:#69738a;
  --accent:#d3502c; --accent2:#1f4e78; --line:#e3e8f0; --ok:#1a7f4b;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:'Segoe UI',system-ui,-apple-system,Roboto,Arial,sans-serif;
  background:var(--bg); color:var(--ink); }}
header {{ background:linear-gradient(135deg,#1f4e78 0%,#173a5a 100%); color:#fff; padding:28px 20px 22px; }}
.wrap {{ max-width:1240px; margin:0 auto; padding:0 16px; }}
h1 {{ margin:0 0 6px; font-size:26px; letter-spacing:.3px; }}
.sub {{ color:#c6d4e6; font-size:14px; }}
.counters {{ display:flex; gap:14px; flex-wrap:wrap; margin-top:18px; }}
.counter {{ background:rgba(255,255,255,.09); border:1px solid rgba(255,255,255,.18);
  border-radius:12px; padding:10px 18px; min-width:130px; }}
.counter b {{ display:block; font-size:24px; }}
.counter span {{ font-size:12px; color:#c6d4e6; }}
.toolbar {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:18px 0 12px; }}
.toolbar input, .toolbar select {{
  padding:9px 12px; border:1px solid var(--line); border-radius:10px;
  background:var(--card); font-size:14px; color:var(--ink); outline:none; }}
.toolbar input {{ flex:1 1 240px; }}
.btn {{ display:inline-block; padding:9px 16px; border-radius:10px; text-decoration:none;
  font-size:14px; font-weight:600; border:none; cursor:pointer; }}
.btn-accent {{ background:var(--accent); color:#fff; }}
.btn-ghost {{ background:var(--card); color:var(--accent2); border:1px solid var(--line); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
  overflow:hidden; box-shadow:0 1px 3px rgba(16,24,40,.05); }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
thead th {{ text-align:left; background:#f0f4f9; color:var(--muted); font-size:12px;
  text-transform:uppercase; letter-spacing:.5px; padding:11px 12px; border-bottom:1px solid var(--line);
  cursor:pointer; user-select:none; white-space:nowrap; }}
tbody td {{ padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
tbody tr:hover {{ background:#f7faff; }}
.badge {{ display:inline-block; padding:2px 8px; border-radius:20px; font-size:11px; font-weight:600; }}
.b-staff {{ background:#e8f0fb; color:#1f4e78; }}
.b-worknet {{ background:#e6f6ee; color:#1a7f4b; }}
.b-list {{ background:#fdeee8; color:#d3502c; }}
.b-hire {{ background:#f1e9fb; color:#6b3fa0; }}
.b-remote {{ background:#fff7df; color:#8a6d00; }}
.b-foreign {{ background:#f3f4f6; color:#6b7280; }}
a {{ color:var(--accent2); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.t-muted {{ color:var(--muted); font-size:12px; }}
.footer {{ padding:16px; text-align:center; color:var(--muted); font-size:12px; line-height:1.6; }}
.empty {{ padding:36px; text-align:center; color:var(--muted); }}
@media (max-width:760px) {{
  .hide-sm {{ display:none; }}
  h1 {{ font-size:21px; }}
}}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>🇦🇲 Вакансии в Армении — агрегатор</h1>
    <div class="sub">staff.am · worknet.am · list.am · hire.am — сбор, перевод на русский, обновление по расписанию. Обновлено: {now}</div>
    <div class="counters">
      <div class="counter"><b id="c-total">…</b><span>вакансий (без заграницы / всего)</span></div>
      <div class="counter"><b id="c-yerevan">…</b><span>Ереван</span></div>
      <div class="counter"><b id="c-remote">…</b><span>удалённо</span></div>
      <div class="counter"><b id="c-companies">…</b><span>компаний</span></div>
    </div>
  </div>
</header>
<div class="wrap">
  <div class="toolbar">
    <input id="q" type="search" placeholder="Поиск: должность, компания, город…">
    <select id="f-source"><option value="">Все источники</option></select>
    <select id="f-city"><option value="">Все локации</option></select>
    <label style="display:flex;align-items:center;gap:6px;font-size:14px">
      <input type="checkbox" id="f-geo" checked style="width:auto"> без заграницы
    </label>
    <label style="display:flex;align-items:center;gap:6px;font-size:14px">
      <input type="checkbox" id="f-remote" style="width:auto"> только удалённые
    </label>
    <a class="btn btn-accent" href="vacancies.xlsx" download>⬇ Excel</a>
    <button class="btn btn-ghost" id="reset">Сброс</button>
  </div>
  <div class="card">
    <div style="overflow-x:auto">
    <table id="tbl">
      <thead><tr>
        <th data-k="posted_at">Опубликовано</th>
        <th>Вакансия</th>
        <th class="hide-sm">Зарплата</th>
        <th>Локация</th>
        <th class="hide-sm">Компания</th>
        <th>Источник</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
    </div>
    <div class="empty" id="empty" hidden>Ничего не найдено — измените фильтры.</div>
  </div>
  <div class="footer">
    Источники: <a href="https://staff.am">staff.am</a> · <a href="https://worknet.am">worknet.am</a> ·
    <a href="https://www.list.am">list.am</a> · <a href="https://hire.am">hire.am</a><br>
    {f'<details style="display:inline"><summary style="cursor:pointer">Статистика последнего сбора</summary><table style="margin:8px auto">{stats_rows}</table></details>' if stats_rows else ''}
    <br>Обновляется автоматически по расписанию (GitHub Actions).
  </div>
</div>
<script>
const DATA = {payload};
const $ = id => document.getElementById(id);
const cTotal = $('c-total'), cYerevan = $('c-yerevan'), cRemote = $('c-remote'), cCompanies = $('c-companies');
const qEl = $('q'), fSource = $('f-source'), fCity = $('f-city'), fRemote = $('f-remote'), fGeo = $('f-geo'), reset = $('reset');
const rowsEl = $('rows'), emptyEl = $('empty');
const SRC = {{staff:'staff.am', worknet:'worknet.am', list:'list.am', hire:'hire.am'}};
const fmtDate = s => {{
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d)) return '—';
  return d.toLocaleString('ru-RU', {{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'}});
}};
const esc = s => (s ?? '').toString().replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);

// счётчики (всего и «без заграницы» — как на сайте по умолчанию)
const visibleNoForeign = DATA.filter(v => v.geo !== 'foreign').length;
const yerevan = DATA.filter(v => (v.city||'').toLowerCase().includes('ереван')).length;
const remote = DATA.filter(v => v.is_remote).length;
const companies = new Set(DATA.filter(v => v.geo !== 'foreign').map(v => (v.company||'').toLowerCase()).filter(Boolean)).size;
cTotal.textContent = `${{visibleNoForeign}}<span style="font-size:13px;color:#c6d4e6"> / ${{DATA.length}}</span>`;
cYerevan.textContent = yerevan;
cRemote.textContent = remote; cCompanies.textContent = companies;

// фильтры
const sources = [...new Set(DATA.map(v => v.source))];
const cities = [...new Set(DATA.map(v => v.city).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ru'));
for (const s of sources) {{
  const o = document.createElement('option'); o.value = s; o.textContent = SRC[s]||s; fSource.appendChild(o);
}}
for (const c of cities) {{
  const o = document.createElement('option'); o.value = c; o.textContent = c; fCity.appendChild(o);
}}

let sortKey = 'posted_at', sortDir = -1;
function rows() {{
  const q = qEl.value.trim().toLowerCase();
  const src = fSource.value, city = fCity.value, rem = fRemote.checked, noForeign = fGeo.checked;
  let r = DATA.filter(v => {{
    if (src && v.source !== src) return false;
    if (city && v.city !== city) return false;
    if (rem && !v.is_remote) return false;
    if (noForeign && v.geo === 'foreign') return false;
    if (q) {{
      const hay = [v.title_orig, v.title_ru, v.company, v.city, v.category].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }}
    return true;
  }});
  r.sort((a,b) => {{
    let x = a[sortKey] ?? '', y = b[sortKey] ?? '';
    if (sortKey === 'posted_at') {{ x = x ? +new Date(x) : 0; y = y ? +new Date(y) : 0; }}
    else {{ x = x.toString().toLowerCase(); y = y.toString().toLowerCase(); }}
    return (x < y ? -1 : x > y ? 1 : 0) * sortDir;
  }});
  return r;
}}
function render() {{
  const r = rows();
  emptyEl.hidden = r.length > 0;
  rowsEl.innerHTML = r.slice(0, 2000).map(v => {{
    const title = v.title_ru || v.title_orig || '(без названия)';
    const orig = v.title_ru && v.title_ru !== v.title_orig
      ? `<div class="t-muted">${{esc(v.title_orig)}}</div>` : '';
    return `<tr>
      <td class="t-muted hide-sm">${{fmtDate(v.posted_at)}}</td>
      <td><a href="${{esc(v.url)}}" target="_blank" rel="noopener"><b>${{esc(title)}}</b></a>${{orig}}
        ${{v.is_remote ? '<span class="badge b-remote">удалённо</span>' : ''}}
        ${{v.geo === 'foreign' ? '<span class="badge b-foreign">заграница</span>' : ''}}
        ${{v.category ? `<div class="t-muted">${{esc(v.category)}}</div>` : ''}}</td>
      <td class="hide-sm">${{esc(v.salary||'—')}}</td>
      <td>${{esc(v.city||'—')}}</td>
      <td class="hide-sm">${{esc(v.company||'—')}}</td>
      <td><span class="badge b-${{v.source}}">${{SRC[v.source]||v.source}}</span></td>
    </tr>`;
  }}).join('');
  document.querySelectorAll('th[data-k]').forEach(th => {{
    th.textContent = th.textContent.replace(/ [▲▼]$/, '');
    if (th.dataset.k === sortKey) th.textContent += sortDir === -1 ? ' ▼' : ' ▲';
  }});
}}
qEl.addEventListener('input', render);
fSource.addEventListener('change', render);
fCity.addEventListener('change', render);
fRemote.addEventListener('change', render);
fGeo.addEventListener('change', render);
reset.addEventListener('click', () => {{
  qEl.value = ''; fSource.value = ''; fCity.value = ''; fRemote.checked = false; fGeo.checked = true; render();
}});
document.querySelectorAll('th[data-k]').forEach(th => th.addEventListener('click', () => {{
  const k = th.dataset.k;
  if (sortKey === k) sortDir *= -1; else {{ sortKey = k; sortDir = -1; }}
  render();
}}));
render();
</script>
</body>
</html>"""

    DASHBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_FILE.write_text(html_doc, encoding="utf-8")
    log.info("дашборд сохранён: %s", DASHBOARD_FILE)
