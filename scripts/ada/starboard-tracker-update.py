#!/usr/bin/env python3
"""starboard-tracker-update.py — project tracker -> CMS `starboard-catalogs`.

Renders the managed <!-- starboard:auto --> block from:
  - the kanban card docs/ssot/kanban/cards/starboard-windsurf-catalogs.yml
    (column, note, comms tail, pipeline stages)
  - the findings manifest reports/starboard-catalogs/catalogs.yml
    (the collect work writes rows: {year, title, range, lang, url,
    sha256, archived})

Publishes en+th to ada-cms-pages, updates the ada-cms-automation
registry doc. Stdlib only — same contract as market-report-update.py.

Env:
    MDDB_BASE_URL   default http://100.102.134.91:11023/v1
    REPO            default = this checkout root

Usage:
    starboard-tracker-update.py            # gated by registry interval
    starboard-tracker-update.py --force    # run regardless
    starboard-tracker-update.py --dry-run  # render + print, write nothing
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(os.environ.get("REPO") or
            Path(__file__).resolve().parents[2])
CARD = REPO / "docs/ssot/kanban/cards/starboard-windsurf-catalogs.yml"
MANIFEST = REPO / "reports/starboard-catalogs/catalogs.yml"
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"
PAGE = "starboard-catalogs"
BLOCK_BEGIN = "<!-- starboard:auto -->"
BLOCK_END = "<!-- /starboard:auto -->"
ICT = timezone(timedelta(hours=7))
SOURCES = ["kanban card starboard-windsurf-catalogs",
           "reports/starboard-catalogs/catalogs.yml"]

_STAGE_ORDER = ["plan", "audit", "collect", "archive", "verify", "done"]


# ---------- MDDB ----------

def _post(path, payload, timeout=60):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


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


# ---------- sources ----------

def load_card():
    try:
        return yaml.safe_load(CARD.read_text()) or {}
    except Exception as e:
        print(f"warn: card unreadable ({e})", file=sys.stderr)
        return {}


def load_manifest():
    try:
        doc = yaml.safe_load(MANIFEST.read_text()) or {}
        return doc.get("catalogs") or []
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"warn: manifest unreadable ({e})", file=sys.stderr)
        return []


# ---------- render ----------

def _comms_tail(card, n=5):
    comms = card.get("comms") or []
    out = []
    for c in comms[-n:]:
        who = c.get("from") or c.get("by") or "?"
        text = str(c.get("text") or c.get("body") or "").strip()
        ts = str(c.get("at") or c.get("ts") or "")[:16]
        out.append((ts, who, text))
    return out


def _pipeline_lines(card, en=True):
    pipe = card.get("pipeline") or {}
    stages = pipe.get("stages") or {}
    if not stages:
        return []
    out = []
    for st in _STAGE_ORDER:
        s = stages.get(st)
        if not s:
            continue
        mark = {"pass": "✅", "fail": "❌", "running": "⏳"}.get(
            str(s.get("status")), "·")
        out.append(f"- {mark} **{st}** — {s.get('status')}"
                   + (f" — {s['detail']}" if s.get("detail") else ""))
    return out


def render_block(now, en=True):
    card = load_card()
    catalogs = load_manifest()
    column = card.get("column") or "?"
    updated = card.get("updated") or "?"
    note = str(card.get("note") or "").strip()

    archived = [c for c in catalogs if c.get("archived")]
    years = sorted({str(c.get("year")) for c in catalogs if c.get("year")})

    L = []
    if en:
        L.append(f"{BLOCK_BEGIN}")
        L.append(f"_Updated {now.strftime('%Y-%m-%d %H:%M ICT')} · "
                 f"card `{card.get('id', 'starboard-windsurf-catalogs')}` "
                 f"in **{column}** (updated {updated})_\n")
        L.append(f"## Progress\n")
        L.append(f"- **{len(catalogs)}** catalogs found · "
                 f"**{len(archived)}** archived"
                 + (f" · years {years[0]}–{years[-1]}" if years else ""))
        pipe = _pipeline_lines(card)
        if pipe:
            L.append("\n### Pipeline\n")
            L += pipe
        if catalogs:
            L.append("\n### Catalogs found\n")
            L.append("| Year | Title | Range | Lang | Archived |")
            L.append("|---|---|---|---|---|")
            for c in catalogs:
                L.append(
                    f"| {c.get('year','?')} | {c.get('title','?')} "
                    f"| {c.get('range','—')} | {c.get('lang','en')} "
                    f"| {'✅' if c.get('archived') else '—'} |")
        else:
            L.append("\n_No catalogs collected yet — manifest "
                     "reports/starboard-catalogs/catalogs.yml is empty._")
        comms = _comms_tail(card)
        if comms:
            L.append("\n### Latest activity\n")
            for ts, who, text in comms:
                L.append(f"- `{ts}` **{who}**: {text[:200]}")
        if note:
            L.append(f"\n### Goal\n\n{note[:800]}")
    else:
        L.append(f"{BLOCK_BEGIN}")
        L.append(f"_อัปเดต {now.strftime('%Y-%m-%d %H:%M ICT')} · "
                 f"การ์ดอยู่ในคอลัมน์ **{column}**_\n")
        L.append(f"## ความคืบหน้า\n")
        L.append(f"- พบแคตตาล็อก **{len(catalogs)}** ฉบับ · "
                 f"เก็บเข้าคลังแล้ว **{len(archived)}** ฉบับ"
                 + (f" · ปี {years[0]}–{years[-1]}" if years else ""))
        if not catalogs:
            L.append("\n_ยังไม่ได้เก็บแคตตาล็อก — "
                     "รอการทำงานของโปรเจกต์_")
        comms = _comms_tail(card, 3)
        if comms:
            L.append("\n### กิจกรรมล่าสุด\n")
            for ts, who, text in comms:
                L.append(f"- `{ts}` **{who}**: {text[:200]}")
    L.append(BLOCK_END)
    summary = {"catalogs": len(catalogs), "archived": len(archived),
               "column": column}
    return "\n".join(L) + "\n", summary


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
        "generated_by": ["starboard-tracker-update.py"],
        "sources": SOURCES,
        "title": ["Starboard Catalogs" if lang == "en"
                  else "แคตตาล็อก Starboard"],
        "written_by": ["starboard-tracker-update"],
    })
    _post("add", {"collection": COLLECTION, "key": PAGE, "lang": lang,
                  "contentMd": body, "meta": meta}, timeout=120)


def save_registry(cfg, now):
    meta = {"kind": ["automation-config"], "bank": ["cms"],
            "scope": ["tony"], "status": ["active"], "source": ["api"],
            "written_by": ["starboard-tracker-update"], "subject": [PAGE],
            "attribute": ["automation"], "slug": [PAGE],
            "title": [f"CMS automation: {PAGE}"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    _post("add", {"collection": REGISTRY, "key": PAGE, "lang": "en",
                  "contentMd": json.dumps(cfg, ensure_ascii=False,
                                          indent=2),
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
        print(f"starboard-tracker: skipped ({why})")
        return 0

    status, error = "ok", None
    try:
        en_block, summary = render_block(now, en=True)
        th_block, _ = render_block(now, en=False)

        en_body = apply_block((get_page("en") or {}).get("contentMd") or
                              "# Starboard Catalogs\n", en_block)
        th_body = apply_block((get_page("th") or {}).get("contentMd") or
                              "# แคตตาล็อก Starboard\n", th_block)

        if args.dry_run:
            print(en_block)
            print("---")
            print(th_block)
            print(json.dumps(summary, ensure_ascii=False))
            return 0

        publish("en", en_body, now_utc)
        publish("th", th_body, now_utc)
        print(f"published {PAGE} en+th — {summary['catalogs']} catalogs "
              f"({summary['archived']} archived), card={summary['column']}")

        if reg_up:
            st = dict(cfg)
            st.update({"run_now": False,
                       "last_run": now_utc.isoformat(timespec="seconds"),
                       "last_status": status,
                       "generated_by": "starboard-tracker-update.py",
                       "pages": [PAGE], "owner": "starboard-tracker-update.py",
                       "schedule": "every 30m (chaba-starboard-tracker.timer)"})
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
