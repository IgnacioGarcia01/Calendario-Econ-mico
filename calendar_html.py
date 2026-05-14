#!/usr/bin/env python3
"""
Genera un calendario económico bursátil en HTML autocontenido.

Uso:
    python calendar_html.py              → calendar_2026.html
    python calendar_html.py 2027         → calendar_2027.html
    FRED_API_KEY=xxx python calendar_html.py

Dependencias:
    pip install exchange_calendars fredapi requests beautifulsoup4 lxml
"""

import os, sys, json, time, datetime, requests
from collections import defaultdict
from bs4 import BeautifulSoup
import exchange_calendars as xcals
import yfinance as yf

# ── Configuración ────────────────────────────────────────────────────────────
FRED_API_KEY = os.environ.get("FRED_API_KEY", "9cdfa757d31b717158d6e3161e6bfaf6")

# ── Watchlist de empresas ─────────────────────────────────────────────────────
# Editá estas listas agregando o quitando tickers.
# ARG: sufijo .BA para empresas de la Bolsa de Buenos Aires.
WATCHLIST_USA = {
    "AAPL":  "Apple",
    "MSFT":  "Microsoft",
    "GOOGL": "Alphabet",
    "AMZN":  "Amazon",
    "META":  "Meta",
    "NVDA":  "NVIDIA",
    "TSLA":  "Tesla",
    "JPM":   "JPMorgan",
    "MELI":  "MercadoLibre",
    "BRK-B": "Berkshire Hathaway",
}

WATCHLIST_ARG = {
    "GGAL.BA": "Grupo Galicia",
    "YPF.BA":  "YPF",
    "PAMP.BA": "Pampa Energía",
    "BMA.BA":  "Banco Macro",
    "TXAR.BA": "Ternium Argentina",
    "ALUA.BA": "Aluar",
    "BBAR.BA": "BBVA Argentina",
    "CEPU.BA": "Central Puerto",
}

FRED_RELEASES = {
    10:  ("CPI",               "⚡", "high"),
    11:  ("PPI",               "📦", "mid"),
    50:  ("Nóminas (NFP)",     "💼", "high"),
    53:  ("GDP",               "📊", "high"),
    56:  ("Ventas Minoristas", "🛒", "mid"),
    91:  ("FOMC / Fed Rate",   "🏦", "high"),
    82:  ("Balanza Comercial", "⚖️", "mid"),
    113: ("Conf. Michigan",    "📉", "mid"),
}

MESES_ES = ["","Enero","Febrero","Marzo","Abril","Mayo","Junio",
            "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
DIAS_ES  = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]

# ── Fuentes de datos ─────────────────────────────────────────────────────────

# ── MAE Licitaciones — cookies de sesión ─────────────────────────────────────
# Cuando expiren, abrí DevTools en marketdata.mae.com.ar/calendario-licitaciones,
# copiá todos los valores de cookie y pegálos en el archivo mae_cookies.txt
# (una por línea, formato:  nombre=valor)
# Si no existe el archivo, se leen las cookies hardcodeadas acá abajo.
MAE_COOKIES_FILE = "mae_cookies.txt"

MAE_COOKIES_DEFAULT = {
    "visid_incap_2512514": "EusMcSVpSU6fGYWWJTqFEQB0A2kAAAAAQUIPAAAAAACynplf7XQE4jCbWs5JMB8l",
    "visid_incap_3146611": "iBi4YcmwQCCuaWrAewEP1eqdA2kAAAAAQUIPAAAAAAB03IJrOFvH1tSGV8WMfLxl",
    "visid_incap_3149172": "U8g/iAKKQ++8U8xYB4S85e2dA2kAAAAAQUIPAAAAAADo+ENzYW8kFRtUWbszj0bg",
    "visid_incap_2609428": "/94MWvphScG1RcT2myHSm2FNSWkAAAAAQUIPAAAAAACzTbXfOT3U5/TX+bYXceeK",
    "visid_incap_2617586": "xbAETnXiRniIzPGCAzDdORow4mkAAAAAQUIPAAAAAAAwqU5mY1P8fOIFqoxNmC2M",
    "incap_ses_123_3146611": "gv/nfXKYBSDoZ901Z/y0ARD7BWoAAAAAQMZq+0QT129yPpbHUFNTsw==",
    "incap_ses_123_3149172": "6DVZLmWTvAXRaN01Z/y0ARX7BWoAAAAA2R+WRaLBLpKZBLSeCgz2Qg==",
    "incap_ses_123_2512514": "YlYPC8l/tBq+7d01Z/y0AWD8BWoAAAAArp+k6wG9GdWt77Y3diFSYg==",
    "incap_ses_123_2617586": "P4jHDFHAfxqs9d01Z/y0AXX8BWoAAAAAGh7z9YJW9jp9R5QvCHsknQ==",
    "nlbi_2512514":          "bXMdSqg0nRtxNnJi4G4SyQAAAAAVK+MdUGt7bZ5C2rcfMOuu",
    "USER_NAME":             "Invitado",
}

def load_mae_cookies():
    """Lee cookies desde mae_cookies.txt si existe, sino usa las hardcodeadas."""
    if not os.path.exists(MAE_COOKIES_FILE):
        return MAE_COOKIES_DEFAULT
    cookies = {}
    with open(MAE_COOKIES_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                cookies[k.strip()] = v.strip()
    return cookies if cookies else MAE_COOKIES_DEFAULT


def get_holiday_names(cal, start, end):
    m = {}
    for rule in cal.regular_holidays.rules:
        try:
            for d in rule.dates(start, end):
                m[d.date()] = rule.name
        except: pass
    y0, y1 = int(start[:4]), int(end[:4])
    for ts in cal.adhoc_holidays:
        d = ts.date()
        if datetime.date(y0,1,1) <= d <= datetime.date(y1,12,31):
            m.setdefault(d, "Feriado especial")
    return m

def load_holidays(year):
    s, e = f"{year}-01-01", f"{year}-12-31"
    return (get_holiday_names(xcals.get_calendar("XBUE"), s, e),
            get_holiday_names(xcals.get_calendar("XNYS"), s, e))

def fetch_fred(year):
    if not FRED_API_KEY:
        print("  ⚠  Sin clave FRED — se omiten eventos USA.")
        return {}
    evs = defaultdict(list)
    for rid, (name, icon, imp) in FRED_RELEASES.items():
        try:
            r = requests.get("https://api.stlouisfed.org/fred/release/dates",
                params={"release_id": rid, "realtime_start": f"{year}-01-01",
                        "realtime_end": f"{year}-12-31",
                        "include_release_dates_with_no_data":"true",
                        "file_type":"json","api_key":FRED_API_KEY}, timeout=10)
            r.raise_for_status()
            for item in r.json().get("release_dates", []):
                d = datetime.date.fromisoformat(item["date"])
                evs[d].append({"name": name, "icon": icon, "imp": imp, "src": "FRED"})
        except Exception as ex:
            print(f"  FRED {name}: {ex}")
        time.sleep(0.12)
    return dict(evs)

def fetch_indec(year):
    import re
    MES = {"ene":1,"feb":2,"mar":3,"abr":4,"may":5,"jun":6,
           "jul":7,"ago":8,"sep":9,"oct":10,"nov":11,"dic":12,
           "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
           "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12}
    evs = defaultdict(list)
    try:
        r = requests.get("https://www.indec.gob.ar/indec/web/Calendario-Ingreso",
            headers={"User-Agent":"Mozilla/5.0","Accept-Language":"es-AR"},
            timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for row in soup.select("table tr"):
            cells = row.find_all(["td","th"])
            if len(cells) < 2: continue
            tf = cells[0].get_text(strip=True).lower()
            pub = cells[1].get_text(strip=True)
            if not pub: continue
            fecha = None
            m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", tf)
            if m:
                try: fecha = datetime.date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
                except: pass
            if not fecha:
                m2 = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", tf)
                if m2 and m2.group(2).lower()[:3] in MES:
                    try: fecha = datetime.date(int(m2.group(3)),MES[m2.group(2).lower()[:3]],int(m2.group(1)))
                    except: pass
            if fecha and fecha.year == year:
                evs[fecha].append({"name": pub[:60], "icon":"📋","imp":"mid","src":"INDEC"})
    except Exception as ex:
        print(f"  INDEC: {ex}")
    return dict(evs)

def fetch_tradingview(year):
    evs = defaultdict(list)
    FLAG = {"US":"🇺🇸","AR":"🇦🇷"}
    IMP  = {1:"low",2:"mid",3:"high"}
    for month in range(1, 13):
        s = datetime.date(year, month, 1)
        e = (datetime.date(year, month+1, 1) - datetime.timedelta(1)) if month < 12 else datetime.date(year,12,31)
        try:
            r = requests.get("https://economic-calendar.tradingview.com/events",
                params={"from":s.strftime("%Y-%m-%dT00:00:00.000Z"),
                        "to":  e.strftime("%Y-%m-%dT23:59:59.000Z"),
                        "countries":"US,AR","importance":"3"},
                headers={"User-Agent":"Mozilla/5.0",
                         "Origin":"https://www.tradingview.com",
                         "Referer":"https://www.tradingview.com/"},
                timeout=12)
            r.raise_for_status()
            for item in r.json().get("result",[]):
                d = datetime.date.fromisoformat(item["date"][:10])
                if d.year != year: continue
                country = item.get("country","")
                name    = item.get("title", item.get("event",""))[:55]
                imp_n   = item.get("importance",1)
                evs[d].append({"name":name,"icon":FLAG.get(country,"🌐"),
                               "imp":IMP.get(imp_n,"mid"),"src":"TradingView",
                               "country":country})
        except Exception as ex:
            if month == 1: print(f"  TradingView: {ex}")
        time.sleep(0.08)
    return dict(evs)

# ── Armar estructura de datos ────────────────────────────────────────────────

# ── Licitaciones MAE ─────────────────────────────────────────────────────────

def fetch_mae_licitaciones(year):
    """
    Llama a la API interna de MAE y devuelve {fecha: [{title, start, end, id}]}
    Usa cookies de sesión del browser (se leen de mae_cookies.txt o las hardcodeadas).
    """
    evs = defaultdict(list)
    cookies = load_mae_cookies()
    headers = {
        "accept":        "application/json",
        "content-type":  "application/json",
        "origin":        "https://marketdata.mae.com.ar",
        "referer":       "https://marketdata.mae.com.ar/",
        "user-agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        r = requests.get(
            "https://api.marketdata.mae.com.ar/api/mercado/licitaciones",
            headers=headers,
            cookies=cookies,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        for ev in data.get("events", []):
            try:
                # Parsear fecha de inicio (viene en UTC, convertir a fecha ARG = UTC-3)
                start_utc = datetime.datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
                start_arg = start_utc - datetime.timedelta(hours=3)
                d = start_arg.date()
                if d.year != year:
                    continue

                end_utc = datetime.datetime.fromisoformat(ev["end"].replace("Z", "+00:00"))
                end_arg = end_utc - datetime.timedelta(hours=3)

                evs[d].append({
                    "id":    ev.get("id"),
                    "title": ev.get("title", ""),
                    "start": start_arg.strftime("%H:%M"),
                    "end":   end_arg.strftime("%H:%M"),
                    "src":   "MAE",
                })
            except Exception:
                pass

        total = sum(len(v) for v in evs.values())
        print(f"  MAE: {total} licitaciones encontradas para {year}")

    except Exception as ex:
        print(f"  MAE licitaciones: {ex}")
        print("  → Actualizá mae_cookies.txt con cookies frescas del browser")

    return dict(evs)


# ── Resultados / Earnings — yfinance ────────────────────────────────────────────────

def fetch_earnings(year):
    """
    Descarga fechas de resultados trimestrales para las empresas
    en WATCHLIST_USA y WATCHLIST_ARG via Yahoo Finance (yfinance).
    """
    evs = defaultdict(list)
    all_tickers = [(t, n, "USA") for t, n in WATCHLIST_USA.items()] + \
                  [(t, n, "ARG") for t, n in WATCHLIST_ARG.items()]

    for ticker, name, country in all_tickers:
        try:
            tkr = yf.Ticker(ticker)
            ed  = tkr.earnings_dates
            if ed is None or (hasattr(ed, "empty") and ed.empty):
                print(f"  {ticker}: sin datos")
                continue

            for idx in ed.index:
                d = idx.date() if hasattr(idx, "date") else datetime.date.fromisoformat(str(idx)[:10])
                if d.year != year:
                    continue

                def safe(col):
                    try:
                        v = ed.loc[idx, col]
                        return round(float(v), 2) if v == v else None
                    except: return None

                evs[d].append({
                    "ticker":   ticker,
                    "name":     name,
                    "country":  country,
                    "eps_est":  safe("EPS Estimate"),
                    "eps_rep":  safe("Reported EPS"),
                    "surprise": safe("Surprise(%)"),
                    "src":      "Yahoo Finance",
                })
            time.sleep(0.4)
        except Exception as ex:
            print(f"  yfinance {ticker}: {ex}")

    return dict(evs)


def build_data(year):
    print(f"Cargando calendarios bursátiles {year}...")
    arg_hols, usa_hols = load_holidays(year)

    print("Descargando FRED...")
    fred = fetch_fred(year)

    print("Scrapeando INDEC...")
    indec = fetch_indec(year)

    print("Descargando TradingView...")
    tv = fetch_tradingview(year)

    print("Descargando licitaciones MAE...")
    mae = fetch_mae_licitaciones(year)

    print("Descargando earnings (yfinance)...")
    earnings = fetch_earnings(year)

    # Serializar para JSON (keys como strings)
    def date_to_str(d): return d.strftime("%Y-%m-%d")

    calendar = {}
    all_dates = sorted(set(arg_hols)|set(usa_hols)|set(fred)|set(indec)|set(tv)|set(earnings)|set(mae))

    for d in all_dates:
        eco_arg = list(indec.get(d, []))
        eco_usa = list(fred.get(d, []))
        for ev in tv.get(d, []):
            if ev.get("country") == "AR":
                eco_arg.append(ev)
            elif ev.get("country") == "US":
                eco_usa.append(ev)

        calendar[date_to_str(d)] = {
            "arg_hol":  arg_hols.get(d),
            "usa_hol":  usa_hols.get(d),
            "eco_arg":  eco_arg,
            "eco_usa":  eco_usa,
            "earnings": earnings.get(d, []),
            "mae":      mae.get(d, []),
        }

    return calendar

# ── Plantilla HTML ───────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Calendario Económico {year}</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:      #080d1a;
    --surface: #0f1628;
    --card:    #141e35;
    --border:  #1e2d4a;
    --border2: #263554;
    --text:    #e2e8f4;
    --muted:   #5a6a8a;
    --dim:     #2a3a5a;
    --arg:     #38bdf8;
    --arg-bg:  rgba(56,189,248,0.10);
    --arg-bd:  rgba(56,189,248,0.25);
    --usa:     #fb7185;
    --usa-bg:  rgba(251,113,133,0.10);
    --usa-bd:  rgba(251,113,133,0.25);
    --both:    #fbbf24;
    --both-bg: rgba(251,191,36,0.10);
    --eco-ar:  #67e8f9;
    --eco-us:  #fca5a5;
    --high:    #f87171;
    --mid:     #94a3b8;
    --earn:    #a78bfa;
    --earn-bg: rgba(167,139,250,0.10);
    --earn-bd: rgba(167,139,250,0.28);
    --mae:     #34d399;
    --mae-bg:  rgba(52,211,153,0.10);
    --mae-bd:  rgba(52,211,153,0.25);
    --panel-w: 380px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Syne', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* ── Layout ── */
  .app { display: flex; height: 100vh; overflow: hidden; }

  .main {
    flex: 1;
    overflow-y: auto;
    padding: 2rem 2.5rem;
    transition: padding-right 0.3s ease;
  }
  .main.panel-open { padding-right: calc(var(--panel-w) + 2.5rem); }

  /* ── Header ── */
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 2rem;
  }
  .logo {
    font-size: 0.7rem;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.15em;
    color: var(--muted);
    text-transform: uppercase;
  }
  .logo span { color: var(--arg); }
  .logo span.usa { color: var(--usa); }

  /* ── Nav ── */
  .nav {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 2rem;
  }
  .nav-title {
    font-size: 2rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    min-width: 280px;
  }
  .nav-title .month-name { color: var(--text); }
  .nav-title .year-num   { color: var(--muted); font-weight: 400; margin-left: 0.4em; font-size: 1.4rem; }
  .btn-nav {
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    width: 38px; height: 38px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 1.1rem;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.15s, border-color 0.15s;
  }
  .btn-nav:hover { background: var(--border); border-color: var(--border2); }

  .year-selector {
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    padding: 0.4rem 0.7rem;
    border-radius: 8px;
    cursor: pointer;
    margin-left: auto;
  }

  /* ── Stats bar ── */
  .stats {
    display: flex;
    gap: 1rem;
    margin-bottom: 2rem;
    flex-wrap: wrap;
  }
  .stat {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.75rem 1.25rem;
    display: flex; flex-direction: column; gap: 2px;
  }
  .stat-label { font-size: 0.65rem; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); font-family: 'JetBrains Mono', monospace; }
  .stat-val   { font-size: 1.4rem; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
  .stat-val.arg  { color: var(--arg); }
  .stat-val.usa  { color: var(--usa); }
  .stat-val.both { color: var(--both); }

  /* ── Calendar grid ── */
  .cal-header {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 4px;
    margin-bottom: 4px;
  }
  .cal-header-cell {
    text-align: center;
    font-size: 0.65rem;
    letter-spacing: 0.1em;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
    text-transform: uppercase;
    padding: 0.4rem 0;
  }
  .cal-grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 4px;
  }
  .day {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    min-height: 90px;
    padding: 0.5rem;
    cursor: default;
    transition: border-color 0.15s, background 0.15s, transform 0.1s;
    position: relative;
    overflow: hidden;
  }
  .day.has-event { cursor: pointer; }
  .day.has-event:hover {
    border-color: var(--border2);
    background: var(--card);
    transform: translateY(-1px);
  }
  .day.selected {
    border-color: var(--arg) !important;
    background: var(--card);
  }
  .day.other-month { opacity: 0.3; }
  .day.today .day-num { color: var(--arg); }
  .day.weekend .day-num { color: var(--muted); }

  /* Feriado bg */
  .day.hol-arg  { background: var(--arg-bg); border-color: var(--arg-bd); }
  .day.hol-usa  { background: var(--usa-bg); border-color: var(--usa-bd); }
  .day.hol-both { background: var(--both-bg); border-color: rgba(251,191,36,0.3); }

  .day-num {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 4px;
  }
  .day-dots {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
    margin-top: 4px;
  }
  .dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .dot.arg      { background: var(--arg); }
  .dot.usa      { background: var(--usa); }
  .dot.eco-arg  { background: var(--eco-ar); }
  .dot.eco-usa  { background: var(--eco-us); }
  .dot.both     { background: var(--both); }
  .dot.earn     { background: var(--earn); }
  .dot.mae      { background: var(--mae); }

  .day-badge {
    font-size: 0.55rem;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.05em;
    line-height: 1.2;
    color: var(--muted);
    margin-top: 4px;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .day-badge.arg-label  { color: var(--arg); }
  .day-badge.usa-label  { color: var(--usa); }
  .day-badge.both-label { color: var(--both); }

  /* ── Side panel ── */
  .panel {
    position: fixed;
    top: 0; right: 0;
    width: var(--panel-w);
    height: 100vh;
    background: var(--surface);
    border-left: 1px solid var(--border);
    overflow-y: auto;
    transform: translateX(100%);
    transition: transform 0.3s cubic-bezier(0.4,0,0.2,1);
    z-index: 100;
    padding: 1.5rem;
  }
  .panel.open { transform: translateX(0); }

  .panel-date {
    font-family: 'JetBrains Mono', monospace;
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 0.25rem;
  }
  .panel-weekday {
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 1.5rem;
  }
  .panel-close {
    position: absolute;
    top: 1.25rem; right: 1.25rem;
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--muted);
    width: 30px; height: 30px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 1rem;
    display: flex; align-items: center; justify-content: center;
  }
  .panel-close:hover { color: var(--text); border-color: var(--border2); }

  .section-title {
    font-size: 0.6rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 0.6rem;
    padding-bottom: 0.4rem;
    border-bottom: 1px solid var(--border);
  }

  .holiday-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0.4rem 0.8rem;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-bottom: 1.2rem;
  }
  .holiday-chip.arg  { background: var(--arg-bg); color: var(--arg); border: 1px solid var(--arg-bd); }
  .holiday-chip.usa  { background: var(--usa-bg); color: var(--usa); border: 1px solid var(--usa-bd); }
  .holiday-chip.both { background: var(--both-bg); color: var(--both); border: 1px solid rgba(251,191,36,0.3); }

  .event-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 1.5rem; }
  .event-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.6rem 0.8rem;
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }
  .event-icon { font-size: 1rem; flex-shrink: 0; margin-top: 1px; }
  .event-name { font-size: 0.82rem; line-height: 1.4; }
  .event-src  { font-size: 0.6rem; color: var(--muted); font-family: 'JetBrains Mono', monospace; margin-top: 2px; }
  .event-imp-high { border-left: 2px solid var(--high); }
  .event-imp-mid  { border-left: 2px solid var(--dim); }
  .earn-card { background: var(--earn-bg); border: 1px solid var(--earn-bd); border-radius: 8px; padding: 0.6rem 0.9rem; margin-bottom: 8px; }
  .earn-ticker { font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; font-weight: 700; color: var(--earn); }
  .earn-cname  { font-size: 0.75rem; color: var(--muted); margin-bottom: 6px; }
  .earn-row    { display: flex; gap: 1rem; flex-wrap: wrap; }
  .earn-metric { display: flex; flex-direction: column; gap: 1px; }
  .earn-metric-label { font-size: 0.55rem; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); font-family: 'JetBrains Mono', monospace; }
  .earn-metric-val   { font-size: 0.85rem; font-weight: 600; font-family: 'JetBrains Mono', monospace; color: var(--text); }
  .earn-metric-val.pos { color: #4ade80; }
  .earn-metric-val.neg { color: var(--high); }
  .mae-card { background: var(--mae-bg); border: 1px solid var(--mae-bd); border-radius: 8px; padding: 0.6rem 0.9rem; margin-bottom: 8px; }
  .mae-title { font-size: 0.78rem; font-weight: 600; color: var(--mae); line-height: 1.4; margin-bottom: 4px; }
  .mae-time  { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; color: var(--muted); }

  /* ── Legend ── */
  .legend {
    display: flex;
    gap: 1.2rem;
    flex-wrap: wrap;
    margin-bottom: 1.5rem;
    align-items: center;
  }
  .legend-item {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 0.65rem;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
  }
  .legend-dot { width: 8px; height: 8px; border-radius: 50%; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--dim); border-radius: 3px; }
</style>
</head>
<body>
<div class="app">
  <div class="main" id="main">

    <header>
      <div class="logo">
        Bolsa <span>ARG</span> · <span class="usa">USA</span>
        &nbsp;·&nbsp; Calendario Económico
      </div>
    </header>

    <div class="nav">
      <div class="nav-title">
        <span class="month-name" id="month-name"></span>
        <span class="year-num" id="year-num"></span>
      </div>
      <button class="btn-nav" id="btn-prev" title="Mes anterior">&#8592;</button>
      <button class="btn-nav" id="btn-next" title="Mes siguiente">&#8594;</button>
      <select class="year-selector" id="year-sel"></select>
    </div>

    <div class="stats" id="stats"></div>

    <div class="legend">
      <div class="legend-item"><div class="legend-dot" style="background:var(--arg)"></div>Feriado ARG</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--usa)"></div>Feriado USA</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--both)"></div>Ambos</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--eco-ar)"></div>Dato Eco. ARG</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--eco-us)"></div>Dato Eco. USA</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--earn)"></div>Resultados empresa</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--mae)"></div>Licitación MAE</div>
    </div>

    <div class="cal-header">
      <div class="cal-header-cell">LUN</div>
      <div class="cal-header-cell">MAR</div>
      <div class="cal-header-cell">MIÉ</div>
      <div class="cal-header-cell">JUE</div>
      <div class="cal-header-cell">VIE</div>
      <div class="cal-header-cell">SÁB</div>
      <div class="cal-header-cell">DOM</div>
    </div>
    <div class="cal-grid" id="cal-grid"></div>
  </div>

  <!-- Panel lateral -->
  <div class="panel" id="panel">
    <button class="panel-close" id="panel-close">✕</button>
    <div class="panel-date" id="panel-date"></div>
    <div class="panel-weekday" id="panel-weekday"></div>
    <div id="panel-body"></div>
  </div>
</div>

<script>
const DATA = {DATA_PLACEHOLDER};
const YEAR = {YEAR_PLACEHOLDER};

const MESES = ["","Enero","Febrero","Marzo","Abril","Mayo","Junio",
               "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"];
const DIAS  = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"];
const DIAS_SHORT = ["LUN","MAR","MIÉ","JUE","VIE","SÁB","DOM"];

let curMonth = new Date().getMonth() + 1;
let curYear  = YEAR;
let selectedDate = null;

const today = new Date();
const todayStr = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;

// ── Year selector ─────────────────────────────────────────────────────────
const yearSel = document.getElementById('year-sel');
for (let y = YEAR - 2; y <= YEAR + 2; y++) {
  const opt = document.createElement('option');
  opt.value = y;
  opt.textContent = y;
  if (y === YEAR) opt.selected = true;
  yearSel.appendChild(opt);
}
yearSel.addEventListener('change', e => {
  curYear = parseInt(e.target.value);
  render();
});

// ── Stats ─────────────────────────────────────────────────────────────────
function calcStats(month) {
  let argH=0, usaH=0, both=0, ecoAr=0, ecoUs=0, earnCount=0, maeCount=0;
  for (const [ds, d] of Object.entries(DATA)) {
    const dt = new Date(ds + 'T12:00:00');
    if (dt.getFullYear() !== curYear) continue;
    if (month && dt.getMonth()+1 !== month) continue;
    if (d.arg_hol && d.usa_hol) both++;
    else if (d.arg_hol) argH++;
    else if (d.usa_hol) usaH++;
    ecoAr += (d.eco_arg||[]).length;
    ecoUs += (d.eco_usa||[]).length;
    earnCount += (d.earnings||[]).length;
    maeCount  += (d.mae||[]).length;
  }
  return {argH, usaH, both, ecoAr, ecoUs, earnCount, maeCount};
}

function renderStats(month) {
  const s = calcStats(month);
  const label = month ? MESES[month] : String(curYear);
  document.getElementById('stats').innerHTML = `
    <div class="stat"><div class="stat-label">🇦🇷 Feriados ARG</div><div class="stat-val arg">${s.argH + s.both}</div></div>
    <div class="stat"><div class="stat-label">🇺🇸 Feriados USA</div><div class="stat-val usa">${s.usaH + s.both}</div></div>
    <div class="stat"><div class="stat-label">⚡ Ambas cerradas</div><div class="stat-val both">${s.both}</div></div>
    <div class="stat"><div class="stat-label">📋 Datos Eco. ARG</div><div class="stat-val" style="color:var(--eco-ar)">${s.ecoAr}</div></div>
    <div class="stat"><div class="stat-label">📊 Datos Eco. USA</div><div class="stat-val" style="color:var(--eco-us)">${s.ecoUs}</div></div>
    <div class="stat"><div class="stat-label">💜 Resultados</div><div class="stat-val" style="color:var(--earn)">${s.earnCount}</div></div>
    <div class="stat"><div class="stat-label">🟢 Licitaciones MAE</div><div class="stat-val" style="color:var(--mae)">${s.maeCount}</div></div>
  `;
}

// ── Calendar render ───────────────────────────────────────────────────────
function render() {
  document.getElementById('month-name').textContent = MESES[curMonth];
  document.getElementById('year-num').textContent   = curYear;
  renderStats(curMonth);
  renderGrid();
}

function renderGrid() {
  const grid = document.getElementById('cal-grid');
  grid.innerHTML = '';

  const first = new Date(curYear, curMonth-1, 1);
  // weekday 0=Sun → adjust to Mon-based
  let startDow = first.getDay() === 0 ? 6 : first.getDay() - 1;
  const daysInMonth = new Date(curYear, curMonth, 0).getDate();
  const prevMonth   = curMonth === 1 ? 12 : curMonth - 1;
  const prevYear    = curMonth === 1 ? curYear - 1 : curYear;
  const daysInPrev  = new Date(prevYear, prevMonth, 0).getDate();

  // Células previas
  for (let i = startDow - 1; i >= 0; i--) {
    const d = daysInPrev - i;
    const ds = `${prevYear}-${String(prevMonth).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    grid.appendChild(makeCell(d, ds, true));
  }

  // Días del mes
  for (let d = 1; d <= daysInMonth; d++) {
    const ds = `${curYear}-${String(curMonth).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    grid.appendChild(makeCell(d, ds, false));
  }

  // Rellenar hasta completar 6 filas (42 cells)
  const total = startDow + daysInMonth;
  const remaining = 42 - total;
  const nextMonth = curMonth === 12 ? 1 : curMonth + 1;
  const nextYear  = curMonth === 12 ? curYear + 1 : curYear;
  for (let d = 1; d <= remaining; d++) {
    const ds = `${nextYear}-${String(nextMonth).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    grid.appendChild(makeCell(d, ds, true));
  }
}

function makeCell(dayNum, dateStr, otherMonth) {
  const data = DATA[dateStr] || {};
  const argHol  = data.arg_hol;
  const usaHol  = data.usa_hol;
  const ecoArg  = data.eco_arg  || [];
  const ecoUsa  = data.eco_usa  || [];
  const earn    = data.earnings || [];
  const mae     = data.mae      || [];
  const hasAny  = argHol || usaHol || ecoArg.length || ecoUsa.length || earn.length || mae.length;

  const dt  = new Date(dateStr + 'T12:00:00');
  const dow = dt.getDay(); // 0=Sun,6=Sat

  const div = document.createElement('div');
  div.className = 'day';
  if (otherMonth) div.classList.add('other-month');
  if (dow === 0 || dow === 6) div.classList.add('weekend');
  if (dateStr === todayStr) div.classList.add('today');
  if (hasAny) div.classList.add('has-event');
  if (argHol && usaHol) div.classList.add('hol-both');
  else if (argHol)      div.classList.add('hol-arg');
  else if (usaHol)      div.classList.add('hol-usa');
  if (dateStr === selectedDate) div.classList.add('selected');

  // Número
  const numEl = document.createElement('div');
  numEl.className = 'day-num';
  numEl.textContent = dayNum;
  div.appendChild(numEl);

  // Dots
  if (hasAny) {
    const dots = document.createElement('div');
    dots.className = 'day-dots';
    if (argHol && usaHol) { dots.innerHTML += '<div class="dot both"></div>'; }
    else {
      if (argHol) dots.innerHTML += '<div class="dot arg"></div>';
      if (usaHol) dots.innerHTML += '<div class="dot usa"></div>';
    }
    ecoArg.forEach(() => dots.innerHTML += '<div class="dot eco-arg"></div>');
    ecoUsa.forEach(() => dots.innerHTML += '<div class="dot eco-usa"></div>');
    earn.forEach(() => dots.innerHTML += '<div class="dot earn"></div>');
    mae.forEach(() =>  dots.innerHTML += '<div class="dot mae"></div>');
    div.appendChild(dots);

    // Badge texto (primera línea)
    const badge = document.createElement('div');
    const label = argHol || usaHol
      ? (argHol && usaHol ? (argHol === usaHol ? argHol : argHol) : (argHol || usaHol))
      : (earn[0] ? earn[0].ticker : (ecoArg[0]?.name || ecoUsa[0]?.name || ''));
    badge.className = 'day-badge ' + (argHol && usaHol ? 'both-label' : argHol ? 'arg-label' : usaHol ? 'usa-label' : '');
    badge.textContent = label;
    div.appendChild(badge);
  }

  // Click
  if (hasAny && !otherMonth) {
    div.addEventListener('click', () => openPanel(dateStr));
  }

  return div;
}

// ── Side panel ────────────────────────────────────────────────────────────
function openPanel(dateStr) {
  selectedDate = dateStr;
  const panel = document.getElementById('panel');
  const main  = document.getElementById('main');

  const dt   = new Date(dateStr + 'T12:00:00');
  const day  = dt.getDate();
  const mon  = dt.getMonth() + 1;
  const yr   = dt.getFullYear();
  const dow  = dt.getDay() === 0 ? 6 : dt.getDay() - 1;

  document.getElementById('panel-date').textContent = `${String(day).padStart(2,'0')} ${MESES[mon]}`;
  document.getElementById('panel-weekday').textContent = `${DIAS[dow]} · ${yr}`;

  const data   = DATA[dateStr] || {};
  const argHol = data.arg_hol;
  const usaHol = data.usa_hol;
  const ecoArg = data.eco_arg  || [];
  const ecoUsa = data.eco_usa  || [];
  const earn   = data.earnings || [];
  const mae    = data.mae      || [];

  let html = '';

  // Feriados
  if (argHol || usaHol) {
    html += `<div class="section-title">Feriados Bursátiles</div>`;
    if (argHol) html += `<div class="holiday-chip ${argHol === usaHol ? 'both' : 'arg'}">🇦🇷 ${argHol}</div>`;
    if (usaHol && usaHol !== argHol) html += `<div class="holiday-chip usa" style="display:block;margin-top:6px">🇺🇸 ${usaHol}</div>`;
    if (argHol && usaHol && argHol !== usaHol) {
    } else if (argHol && usaHol) {
      // misma fecha ambos — ya mostrado
    }
  }

  // Eventos ARG
  if (ecoArg.length) {
    html += `<div class="section-title" style="margin-top:1rem">Datos Económicos 🇦🇷</div>`;
    html += `<div class="event-list">`;
    ecoArg.forEach(ev => {
      html += `<div class="event-card event-imp-${ev.imp||'mid'}">
        <div class="event-icon">${ev.icon||'📋'}</div>
        <div><div class="event-name">${ev.name}</div><div class="event-src">${ev.src||'INDEC'}</div></div>
      </div>`;
    });
    html += `</div>`;
  }

  // Eventos USA
  if (ecoUsa.length) {
    html += `<div class="section-title" style="margin-top:${ecoArg.length?'0':'1rem'}rem">Datos Económicos 🇺🇸</div>`;
    html += `<div class="event-list">`;
    ecoUsa.forEach(ev => {
      html += `<div class="event-card event-imp-${ev.imp||'mid'}">
        <div class="event-icon">${ev.icon||'📊'}</div>
        <div><div class="event-name">${ev.name}</div><div class="event-src">${ev.src||'FRED'}</div></div>
      </div>`;
    });
    html += `</div>`;
  }

  // Earnings section
  if (earn.length) {
    html += `<div class="section-title" style="margin-top:1rem">Resultados Empresariales</div>`;
    earn.forEach(ev => {
      const surpClass = ev.surprise > 0 ? 'pos' : ev.surprise < 0 ? 'neg' : '';
      const surpSign  = ev.surprise > 0 ? '+' : '';
      html += `<div class="earn-card">
        <div class="earn-ticker">${ev.ticker} <span style="color:var(--muted);font-size:0.7rem;font-weight:400">${ev.country}</span></div>
        <div class="earn-cname">${ev.name}</div>
        <div class="earn-row">
          ${ev.eps_est  != null ? `<div class="earn-metric"><div class="earn-metric-label">EPS Est.</div><div class="earn-metric-val">$${ev.eps_est}</div></div>` : ''}
          ${ev.eps_rep  != null ? `<div class="earn-metric"><div class="earn-metric-label">EPS Real</div><div class="earn-metric-val">$${ev.eps_rep}</div></div>` : ''}
          ${ev.surprise != null ? `<div class="earn-metric"><div class="earn-metric-label">Sorpresa</div><div class="earn-metric-val ${surpClass}">${surpSign}${ev.surprise}%</div></div>` : ''}
        </div>
      </div>`;
    });
  }

  // MAE licitaciones
  if (mae.length) {
    html += `<div class="section-title" style="margin-top:1rem">Licitaciones MAE 🇦🇷</div>`;
    mae.forEach(ev => {
      html += `<div class="mae-card">
        <div class="mae-title">${ev.title}</div>
        <div class="mae-time">⏰ ${ev.start} – ${ev.end} (ARG)</div>
      </div>`;
    });
  }

  if (!html) html = `<p style="color:var(--muted);font-size:0.8rem">Sin eventos registrados.</p>`;

  document.getElementById('panel-body').innerHTML = html;
  panel.classList.add('open');
  main.classList.add('panel-open');
  renderGrid(); // re-render para selección
}

function closePanel() {
  selectedDate = null;
  document.getElementById('panel').classList.remove('open');
  document.getElementById('main').classList.remove('panel-open');
  renderGrid();
}

document.getElementById('panel-close').addEventListener('click', closePanel);
document.getElementById('btn-prev').addEventListener('click', () => {
  if (curMonth === 1) { curMonth = 12; curYear--; }
  else curMonth--;
  render();
});
document.getElementById('btn-next').addEventListener('click', () => {
  if (curMonth === 12) { curMonth = 1; curYear++; }
  else curMonth++;
  render();
});

// Init
render();
</script>
</body>
</html>
"""

# ── Generar archivo ──────────────────────────────────────────────────────────

def generate(year):
    data = build_data(year)
    html = HTML_TEMPLATE.replace("{DATA_PLACEHOLDER}", json.dumps(data, ensure_ascii=False))
    html = html.replace("{YEAR_PLACEHOLDER}", str(year))
    fname = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"calendar_{year}.html")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ Generado: {fname}")
    print(f"   Abrilo en tu browser: file:///{os.path.abspath(fname)}")

if __name__ == "__main__":
    year = datetime.date.today().year
    for arg in sys.argv[1:]:
        if arg.isdigit() and len(arg) == 4:
            year = int(arg)
    generate(year)
