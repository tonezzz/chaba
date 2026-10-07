#!/usr/bin/env python3
"""market-report-update.py — daily market snapshot -> CMS `market-report`.

Fetches FX / DXY / commodities from the local trade API and a small SET
watchlist from Yahoo, renders the managed <!-- market:auto --> block,
publishes en+th pages to ada-cms-pages, updates the ada-cms-automation
registry doc, and writes reports/market-summary.json for
report-daily-brief.py (morning edition picks up the one-liner).

Stdlib only — same contract as flood-news-update.py. The trade API is
read via HTTP (dogfoods the service; no DB creds in this script).

Env:
    TRADE_API       default http://127.0.0.1:9002
    MDDB_BASE_URL   default http://100.102.134.91:11023/v1
    YAHOO_RANGE     default 2mo (lookback for stock deltas)

Usage:
    market-report-update.py            # gated by registry interval
    market-report-update.py --force    # run regardless
    market-report-update.py --dry-run  # render + print, write nothing
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

TRADE = os.environ.get("TRADE_API", "http://127.0.0.1:9002").rstrip("/")
MDDB = os.environ.get("MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
YAHOO_RANGE = os.environ.get("YAHOO_RANGE", "2mo")
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"
PAGE = "market-report"
BLOCK_BEGIN = "<!-- market:auto -->"
BLOCK_END = "<!-- /market:auto -->"
ICT = timezone(timedelta(hours=7))
STALE_DAYS = 3
SUMMARY_JSON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "reports", "market-summary.json")

FX_MAJORS = ["THB", "EUR", "JPY", "CNY", "GBP"]
WATCHLIST = [("^SET.BK", "SET"), ("PTT.BK", "PTT"), ("AOT.BK", "AOT"),
             ("KBANK.BK", "KBANK"), ("DELTA.BK", "DELTA")]
SOURCES = ["trade-api (exchange_rates/dollar_index/commodity_prices)",
           "yahoo-finance chart api"]
SUMMARY = ("Daily market snapshot — USD/THB, gold, DXY, SET watchlist "
           "(^SET, PTT, AOT, KBANK, DELTA). Morning briefing reads the "
           "one-liner from here.")


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "chaba-market-report/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _post(path, payload, timeout=60):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


# ---------- series ----------

def _delta(series, days):
    """series: [(date_str, value)] oldest->newest. Nearest point >= days back."""
    if len(series) < 2:
        return None
    latest_d, latest_v = series[-1]
    cutoff = datetime.fromisoformat(latest_d) - timedelta(days=days)
    for d, v in reversed(series[:-1]):
        if datetime.fromisoformat(d) <= cutoff:
            return (latest_v - v) / v * 100
    return None


def _stale(date_str, now):
    return (now.date() - datetime.fromisoformat(date_str).date()).days > STALE_DAYS


def fetch_fx(ccy):
    """-> [(date, rate)] or None. 3m window so the m/m delta resolves."""
    try:
        d = _get(f"{TRADE}/api/exchange_rates/{ccy}?period=3m&limit=200")
        return [(r["date"], r["rate"]) for r in d.get("data") or []]
    except Exception as e:
        print(f"warn: fx {ccy}: {e}", file=sys.stderr)
        return None


def fetch_dxy():
    try:
        d = _get(f"{TRADE}/api/dollar_index?period=3m&limit=200")
        return [(r["date"], r["value"]) for r in d.get("data") or []]
    except Exception as e:
        print(f"warn: dxy: {e}", file=sys.stderr)
        return None


def fetch_commodity(commodity, symbol):
    """commodity_prices mixes symbols — filter client-side."""
    try:
        d = _get(f"{TRADE}/api/commodity_prices/{commodity}?period=3m&limit=1000")
        rows = [(r["date"], r["price"]) for r in d.get("data") or []
                if (r.get("symbol") or "").upper() == symbol.upper()]
        return rows or None
    except Exception as e:
        print(f"warn: {commodity}/{symbol}: {e}", file=sys.stderr)
        return None


def fetch_stock(ticker):
    """-> (label-free series) [(date, close)] via Yahoo chart API."""
    try:
        d = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                 f"?interval=1d&range={YAHOO_RANGE}", timeout=15)
        res = (d.get("chart") or {}).get("result") or []
        if not res:
            return None
        ts = res[0].get("timestamp") or []
        closes = (res[0].get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        out = [(datetime.fromtimestamp(t, ICT).date().isoformat(), c)
               for t, c in zip(ts, closes) if c is not None]
        return out or None
    except Exception as e:
        print(f"warn: yahoo {ticker}: {e}", file=sys.stderr)
        return None


# ---------- render ----------

def _fmt(v, dec=2):
    return f"{v:,.{dec}f}"


def _pct(d):
    return "—" if d is None else f"{d:+.2f}%"


def _sane(d, bound):
    """None/None-safe delta sanity: abs(delta) > bound% is a data bug
    (e.g. an inverted-pair import) — surface it, don't print the lie."""
    return d is not None and abs(d) > bound


def _line(name, series, unit, dec, stale, now, suspect_bound=None):
    """'USD/THB 33.60 (+0.1% w/w)' or stale/unavailable marker."""
    if not series:
        return f"{name} — unavailable"
    d, v = series[-1]
    w, m = _delta(series, 7), _delta(series, 30)
    s = f"{name} {_fmt(v, dec)}{unit} ({_pct(w)} w/w, {_pct(m)} m/m)"
    if suspect_bound and (_sane(w, suspect_bound) or _sane(m, suspect_bound)):
        s += "  ⚠ suspect delta — data bug (e.g. inverted pair)"
    if _stale(d, now):
        s += f"  ⚠ data as of {d}"
    return s


def render_block(now, en=True):
    """Returns (block_md, summary_dict). en=False -> Thai labels."""
    fx = {c: fetch_fx(c) for c in FX_MAJORS}
    thb = fx["THB"]
    rows_fx = [_line(f"USD/{c}", s, "", 2, True, now, suspect_bound=15)
               for c, s in fx.items()]
    dxy = fetch_dxy()
    gold_spot = fetch_commodity("GOLD", "GOLD")
    gold_thb = fetch_commodity("GOLD", "XAU-THB")
    oil = fetch_commodity("OIL", "USOIL") or fetch_commodity("OIL", "WTI") \
        or fetch_commodity("OIL", "OIL")
    stocks = {label: fetch_stock(t) for t, label in WATCHLIST}

    stamp = now.strftime("%Y-%m-%d %H:%M")
    L = []
    if en:
        L += [BLOCK_BEGIN,
              f"## Market snapshot — {stamp} ICT", ""]
        L += ["### FX (per USD)"] + [f"- {r}" for r in rows_fx]
        L += ["", "### Dollar index",
              f"- {_line('DXY', dxy, '', 2, True, now)}"]
        L += ["", "### Gold",
              f"- {_line('Thai gold bar (฿/baht-weight)', gold_thb, ' ฿', 0, True, now)}",
              f"- {_line('Spot XAU/USD', gold_spot, ' $', 2, True, now)}"]
        L += ["", "### Energy",
              f"- {_line('WTI crude', oil, ' $', 2, True, now)}"]
        L += ["", "### SET watchlist"]
    else:
        L += [BLOCK_BEGIN,
              f"## ภาพรวมตลาด — {stamp} น.", ""]
        L += ["### อัตราแลกเปลี่ยน (ต่อ 1 USD)"] + [f"- {r}" for r in rows_fx]
        L += ["", "### ดัชนีดอลลาร์",
              f"- {_line('DXY', dxy, '', 2, True, now)}"]
        L += ["", "### ทองคำ",
              f"- {_line('ทองแท่ง (บาท/บาททองคำ)', gold_thb, ' ฿', 0, True, now)}",
              f"- {_line('ทองคำโลก XAU/USD', gold_spot, ' $', 2, True, now)}"]
        L += ["", "### พลังงาน",
              f"- {_line('น้ำมัน WTI', oil, ' $', 2, True, now)}"]
        L += ["", "### หุ้น SET เฝ้าดู"]

    missing_stocks = []
    for label, series in stocks.items():
        if series:
            # ^SET.BK serves spot only on Yahoo — single-point history.
            if len(series) < 2:
                L.append(f"- {label} {_fmt(series[-1][1])} THB (spot only)")
                continue
            w, m = _delta(series, 7), _delta(series, 30)
            extra = ""
            if _stale(series[-1][0], now):
                extra = f"  ⚠ data as of {series[-1][0]}"
            L.append(f"- {label} {_fmt(series[-1][1])} THB "
                     f"({_pct(w)} w/w, {_pct(m)} m/m){extra}")
        else:
            missing_stocks.append(label)
    if missing_stocks:
        L.append("- " + ("unavailable: " if en else "ไม่พร้อมใช้: ")
                 + ", ".join(missing_stocks))

    footer = (f"Generated by scripts/ada/market-report-update.py · "
              f"sources: trade-api, yahoo-finance")
    L += ["", f"*{footer}*", BLOCK_END]

    # Compact one-liner for daily-brief consumption.
    summary = {
        "generated": now.isoformat(timespec="seconds"),
        "usd_thb": round(thb[-1][1], 2) if thb else None,
        "usd_thb_d": _pct(_delta(thb, 7)) if thb else None,
        "gold_bar_thb": round(gold_thb[-1][1]) if gold_thb else None,
        "gold_bar_d": _pct(_delta(gold_thb, 7)) if gold_thb else None,
        "xauusd": round(gold_spot[-1][1], 2) if gold_spot else None,
        "dxy": round(dxy[-1][1], 2) if dxy else None,
        "wti": round(oil[-1][1], 2) if oil else None,
        "set": round(stocks["SET"][-1][1], 2) if stocks.get("SET") else None,
        "stale": any(_stale(s[-1][0], now) for s in
                     [thb, gold_thb, gold_spot, dxy, oil] if s),
    }
    return "\n".join(L), summary


# ---------- MDDB ----------

def _search_all(collection, page_size=500):
    docs, offset = [], 0
    while True:
        page = _post("search", {"collection": collection, "query": "",
                                "limit": page_size, "offset": offset})
        docs += page
        if len(page) < page_size:
            return docs
        offset += page_size


def get_page(lang):
    docs = _search_all(COLLECTION)
    return next((d for d in docs
                 if d.get("key") == PAGE and d.get("lang") == lang), None)


BLOCK_RE = re.compile(
    re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), re.S)


def apply_block(body, block):
    if BLOCK_RE.search(body or ""):
        return BLOCK_RE.sub(lambda m: block, body, count=1)
    m = re.search(r"^## ", body or "", re.M)
    if m:
        return body[:m.start()] + block + "\n\n" + body[m.start():]
    return (body or "").rstrip() + "\n\n" + block + "\n"


def publish(lang, body, now):
    doc = get_page(lang) or {}
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    meta.update({
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "lang": [lang],
        "kind": ["report"],
        "attribute": ["report"],
        "report_role": ["rollup"],
        "generated_by": ["market-report-update.py"],
        "summary": [SUMMARY],
        "domain": ["finance"],
        "fresh_for": ["1d"],
        "sources": SOURCES,
        "title": ["Market Report" if lang == "en" else "รายงานตลาด"],
        "written_by": ["market-report-update"],
    })
    _post("add", {"collection": COLLECTION, "key": PAGE, "lang": lang,
                  "contentMd": body, "meta": meta}, timeout=120)


def save_registry(cfg, now):
    meta = {"kind": ["automation-config"], "bank": ["cms"], "scope": ["tony"],
            "status": ["active"], "source": ["api"],
            "written_by": ["market-report-update"], "subject": [PAGE],
            "attribute": ["automation"], "slug": [PAGE],
            "title": [f"CMS automation: {PAGE}"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    _post("add", {"collection": REGISTRY, "key": PAGE, "lang": "en",
                  "contentMd": json.dumps(cfg, ensure_ascii=False, indent=2),
                  "meta": meta}, timeout=120)


def load_registry():
    try:
        docs = _search_all(REGISTRY)
    except Exception as e:
        print(f"warn: registry unreachable ({e}) — running anyway",
              file=sys.stderr)
        return {}, False
    for d in docs:
        if d.get("key") == PAGE:
            try:
                return json.loads(d.get("contentMd") or "{}"), True
            except json.JSONDecodeError:
                return {}, True
    return {}, True


def gated(cfg, now, force):
    if not cfg.get("enabled", True):
        return "disabled"
    if force or cfg.get("run_now"):
        return None
    interval = int(cfg.get("interval_min") or 0)
    last = cfg.get("last_run")
    if interval and last:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if now < last_dt + timedelta(minutes=interval, seconds=-30):
                return f"interval (last run {last})"
        except ValueError:
            pass
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now_utc = datetime.now(timezone.utc)
    now = now_utc.astimezone(ICT)
    cfg, reg_up = load_registry()
    why = gated(cfg, now_utc, args.force)
    if why:
        print(f"market-report: skipped ({why})")
        return 0

    status, error = "ok", None
    try:
        en_block, summary = render_block(now, en=True)
        th_block, _ = render_block(now, en=False)

        en_body = apply_block((get_page("en") or {}).get("contentMd") or
                              "# Market Report\n", en_block)
        th_body = apply_block((get_page("th") or {}).get("contentMd") or
                              "# รายงานตลาด\n", th_block)

        if args.dry_run:
            print(en_block)
            print("---")
            print(th_block)
            print(json.dumps(summary, ensure_ascii=False))
            return 0

        publish("en", en_body, now_utc)
        publish("th", th_body, now_utc)
        print(f"published {PAGE} en+th — "
              f"USD/THB {summary['usd_thb']} · gold ฿{summary['gold_bar_thb']}")

        os.makedirs(os.path.dirname(SUMMARY_JSON), exist_ok=True)
        with open(SUMMARY_JSON, "w") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        if reg_up:
            st = dict(cfg)
            st.update({"run_now": False,
                       "last_run": now_utc.isoformat(timespec="seconds"),
                       "last_status": status,
                       "generated_by": "market-report-update.py",
                       "pages": [PAGE], "owner": "market-report-update.py",
                       "schedule": "daily ~06:45 ICT (before daily-brief 07:05)"})
            save_registry(st, now_utc)
    except Exception as e:
        status, error = "error", str(e)
        print(f"error: {e}", file=sys.stderr)
        if reg_up and not args.dry_run:
            try:
                st = dict(cfg)
                st.update({"run_now": False,
                           "last_run": now_utc.isoformat(timespec="seconds"),
                           "last_status": "error",
                           "last_error": str(e)[:500]})
                save_registry(st, now_utc)
            except Exception:
                pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
