#!/usr/bin/env python3
"""standard-drift-digest.py — drift signals -> CMS `standard-drift`.

The feedback layer of the report-first flywheel (card
standard-drift-digest): one page collecting every signal that a
standard is slipping — stale generated reports, board drift, and
tool-surface debt — so Tony reviews ONE digest instead of scattered
fires. Deterministic collectors only; no model call.

Collectors:
  stale_reports   ada-cms-pages docs with generated_by whose
                  updated + meta.fresh_for has lapsed
  board_drift     doing cards stale >STALE_DOING_DAYS, cards with open
                  requests, review pile size
  tool_debt       ada-pi scripts/tool-lint.py --json violations by rule

Publishes en+th to ada-cms-pages, same contract as kanban-brief.py
(ada-cms-automation registry gating, managed block, meta contract —
ssot.apps.cms-reports.yml).

Env:
    MDDB_BASE_URL     default http://100.102.134.91:11023/v1
    REPO              default = this checkout root
    ADA_PI            default ~/CascadeProjects/ada-pi (lint source)

Usage:
    standard-drift-digest.py            # gated by registry interval
    standard-drift-digest.py --force    # run regardless
    standard-drift-digest.py --dry-run  # render + print, write nothing
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
CARDS_DIR = REPO / "docs/ssot/kanban/cards"
ADA_PI = Path(os.environ.get("ADA_PI", Path.home() / "CascadeProjects"
                            / "ada-pi"))
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"
PAGE = "standard-drift"
BLOCK_BEGIN = "<!-- standard-drift:auto -->"
BLOCK_END = "<!-- /standard-drift:auto -->"
BLOCK_RE = re.compile(re.escape(BLOCK_BEGIN) + r".*?" +
                      re.escape(BLOCK_END), re.S)
SOURCES = ["ada-cms-pages", "docs/ssot/kanban/cards", "ada-pi tool-lint"]
ICT = timezone(timedelta(hours=7))
STALE_DOING_DAYS = 3
MAX_ROWS = 15

# ---------- mddb ----------


def _post(path, payload, timeout=60):
    req = urllib.request.Request(
        f"{MDDB}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or "{}")


def _search_all(collection, page_size=500):
    docs, skip = [], 0
    while True:
        out = _post("/search", {"collection": collection,
                                "limit": page_size, "offset": skip})
        batch = out if isinstance(out, list) else out.get("results", [])
        docs += batch
        if len(batch) < page_size:
            return docs
        skip += page_size


def get_page(lang):
    docs = _search_all(COLLECTION)
    return next((d for d in docs
                 if d.get("key") == PAGE and d.get("lang") == lang), None)


# ---------- collectors ----------

_FRESH_RE = re.compile(r"(\d+)\s*([hdwm])")
_FRESH_UNIT = {"h": 1 / 24, "d": 1, "w": 7, "m": 30}


def _fresh_days(v: str) -> float | None:
    m = _FRESH_RE.match(str(v or "").strip().lower())
    if not m:
        return None
    return int(m.group(1)) * _FRESH_UNIT[m.group(2)]


def _upd_dt(v, naive_tz=timezone.utc) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=naive_tz)
    except (ValueError, TypeError):
        return None


def stale_reports(now: datetime) -> list[dict]:
    """Generated pages past their own fresh_for — the quality_loop input:
    Ada refreshes by tool, structural failures escalate to Devin."""
    out = []
    dead = {"superseded", "archived", "retracted", "expired"}
    for d in _search_all(COLLECTION):
        meta = d.get("meta") or {}
        if not meta.get("generated_by"):
            continue
        status = meta.get("status")
        if isinstance(status, list):
            status = status[0] if status else None
        if status in dead:
            continue
        fresh = meta.get("fresh_for")
        if isinstance(fresh, list):
            fresh = fresh[0] if fresh else None
        days = _fresh_days(fresh)
        if days is None:
            continue
        upd = meta.get("updated") or meta.get("addedAt")
        if isinstance(upd, list):
            upd = upd[0] if upd else None
        dt = _upd_dt(upd)
        if dt is None:
            continue
        age = (now - dt).total_seconds() / 86400
        if age > days:
            out.append({"slug": d.get("key", "?"),
                        "age_d": round(age, 1), "fresh_for": fresh,
                        "by": str(meta.get("generated_by") or "")[:60]})
    # lang variants of one slug share the key — keep the staler of them
    dedup: dict[str, dict] = {}
    for r in out:
        if r["age_d"] > dedup.get(r["slug"], {}).get("age_d", -1):
            dedup[r["slug"]] = r
    return sorted(dedup.values(), key=lambda r: -r["age_d"])


def board_drift(cards: list[dict], now: datetime) -> dict:
    """Cards waiting on someone — stale doing, open asks, review pile."""
    stale_doing, open_asks, review = [], [], 0
    for c in cards:
        col = c.get("column") or "backlog"
        if col == "done":
            continue
        cid = c.get("id") or c["_file"][:-4]
        # card `updated` stamps are naive local time (ICT)
        upd = _upd_dt(c.get("updated"), naive_tz=ICT)
        age_d = round((now - upd).total_seconds() / 86400, 1) if upd else None
        if col == "review":
            review += 1
        if col == "doing" and age_d is not None and age_d > STALE_DOING_DAYS:
            stale_doing.append({"id": cid, "age_d": age_d,
                                "title": (c.get("title") or "")[:60]})
        open_reqs = [r for r in (c.get("requests") or [])
                     if isinstance(r, dict) and r.get("status") != "answered"]
        if open_reqs:
            open_asks.append({"id": cid, "n": len(open_reqs),
                              "age_d": age_d,
                              "title": (c.get("title") or "")[:60]})
    stale_doing.sort(key=lambda r: -(r["age_d"] or 0))
    open_asks.sort(key=lambda r: -(r["age_d"] or 0))
    return {"stale_doing": stale_doing, "open_asks": open_asks,
            "review": review}


def tool_debt() -> dict:
    """ada-pi tool-lint violations by rule — the surface-debt signal."""
    py = ADA_PI / ".venv" / "bin" / "python"
    if not py.exists():
        py = "python3"
    try:
        proc = subprocess.run(
            [str(py), "scripts/tool-lint.py", "--json"],
            cwd=ADA_PI, capture_output=True, text=True, timeout=120)
        rep = json.loads(proc.stdout or "{}")
    except Exception as exc:
        return {"error": f"lint run failed: {exc}"}
    # tool-lint --json emits {ok, errors: [str], warnings: [str]} —
    # error strings are "rule: detail" shaped
    fails = rep.get("errors") or []
    by_rule: dict[str, int] = {}
    for f in fails:
        rule = str(f).split(":", 1)[0].strip() or "?"
        by_rule[rule] = by_rule.get(rule, 0) + 1
    return {"ok": rep.get("ok"), "by_rule": by_rule,
            "total": len(fails),
            "samples": [str(f)[:90] for f in fails[:MAX_ROWS]]}


# ---------- render ----------

def _load_cards():
    out = []
    for f in sorted(CARDS_DIR.glob("*.yml")):
        try:
            c = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        c["_file"] = f.name
        out.append(c)
    return out


def render(sig: dict, now: datetime, lang: str) -> str:
    th = lang == "th"
    L = [BLOCK_BEGIN, "",
         f"_updated {now.astimezone(ICT):%Y-%m-%d %H:%M ICT}_", ""]
    st = sig["stale_reports"]
    L += [f"### {'รายงานเกินกำหนด' if th else 'Stale generated reports'}"
          f" ({len(st)})", ""]
    if st:
        for r in st[:MAX_ROWS]:
            L.append(f"- **{r['slug']}** — {r['age_d']}d old, fresh_for "
                     f"{r['fresh_for']} — `{r['by']}`")
    else:
        L.append("- —")
    d = sig["board_drift"]
    L += ["", f"### {'บอร์ดล้าด' if th else 'Board drift'}", ""]
    L.append(f"- review pile: **{d['review']}** cards")
    for r in d["stale_doing"][:8]:
        L.append(f"- stale doing {r['age_d']}d: **{r['id']}** {r['title']}")
    for r in d["open_asks"][:8]:
        L.append(f"- open ask x{r['n']} ({r['age_d']}d): **{r['id']}** "
                 f"{r['title']}")
    t = sig["tool_debt"]
    L += ["", f"### {'หนี้ tool surface' if th else 'Tool-surface debt'}", ""]
    if t.get("error"):
        L.append(f"- {t['error']}")
    elif not t.get("total"):
        L.append("- clean — 0 lint violations")
    else:
        rules = ", ".join(f"{k}×{v}" for k, v in t["by_rule"].items())
        L.append(f"- {t['total']} violations — {rules}")
        for s in t.get("samples") or []:
            L.append(f"  - {s}")
    L += ["", BLOCK_END]
    return "\n".join(L)


def upsert_block(body: str, block: str) -> str:
    if BLOCK_RE.search(body or ""):
        return BLOCK_RE.sub(lambda m: block, body, count=1)
    m = re.search(r"^## ", body or "", re.M)
    if m:
        return body[:m.start()] + block + "\n\n" + body[m.start():]
    return (body or "").rstrip() + "\n\n" + block + "\n"


def page_body(lang, block):
    doc = get_page(lang)
    if doc and doc.get("contentMd"):
        return upsert_block(doc["contentMd"], block)
    title = ("Standard Drift — สัญญาณที่มาตรฐานหลุด" if lang == "th"
             else "Standard Drift — where the standard is slipping")
    lead = ("หน้านี้อัปเดตอัตโนมัติโดย chaba — รวมสัญญาณ drift ไว้ที่เดียว "
            "(รายงานเกินกำหนด / บอร์ดค้าง / หนี้ tool surface) "
            "ตาม report_first_protocol quality_loop"
            if lang == "th" else
            "Auto-updated by chaba — every signal that a standard is "
            "slipping, in one page (stale reports / stuck board / "
            "tool-surface debt), per report_first_protocol#quality_loop.")
    return f"# {title}\n\n{lead}\n\n{block}\n"


def publish(lang, body, now):
    doc = get_page(lang) or {}
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    meta.update({
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "lang": [lang], "kind": ["report"], "attribute": ["report"],
        "report_role": ["rollup"], "domain": ["monitoring"],
        "generated_by": ["standard-drift-digest.py"], "sources": SOURCES,
        "title": ["Standard Drift" if lang == "en"
                  else "สัญญาณมาตรฐานหลุด"],
        "summary": ["One page of drift signals: stale generated reports, "
                    "stuck kanban items, tool-lint violations — the "
                    "feedback input for tightening standards hands-off."],
        "fresh_for": ["6h"], "confidence": ["high"],
        "timeline": [f"{now.isoformat(timespec='minutes')}: digest run"],
        "written_by": ["standard-drift-digest"],
    })
    _post("/add", {"collection": COLLECTION, "key": PAGE, "lang": lang,
                  "contentMd": body, "meta": meta}, timeout=120)


def save_registry(cfg, now):
    meta = {"kind": ["automation-config"], "bank": ["cms"],
            "scope": ["tony"], "status": ["active"], "source": ["api"],
            "written_by": ["standard-drift-digest"], "subject": [PAGE],
            "attribute": ["automation"], "slug": [PAGE],
            "title": [f"CMS automation: {PAGE}"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    _post("/add", {"collection": REGISTRY, "key": PAGE, "lang": "en",
                  "contentMd": json.dumps(cfg, ensure_ascii=False,
                                          indent=2), "meta": meta},
          timeout=120)


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
    args = set(sys.argv[1:])
    now = datetime.now(timezone.utc)
    cfg, _ = load_registry()
    if not cfg:
        cfg = {"enabled": True, "interval_min": 360}
    reason = gated(cfg, now, "--force" in args)
    if reason:
        print(f"standard-drift: skipped ({reason})")
        return 0
    sig = {"stale_reports": stale_reports(now),
           "board_drift": board_drift(_load_cards(), now),
           "tool_debt": tool_debt()}
    if "--dry-run" in args:
        print(render(sig, now, "en"))
        return 0
    publish("en", page_body("en", render(sig, now, "en")), now)
    publish("th", page_body("th", render(sig, now, "th")), now)
    cfg["last_run"] = now.isoformat(timespec="seconds")
    cfg["last_duration_s"] = round(
        (datetime.now(timezone.utc) - now).total_seconds(), 1)
    save_registry(cfg, now)
    print(f"standard-drift: published ({len(sig['stale_reports'])} stale "
          f"reports, {sig['board_drift']['review']} review, "
          f"{sig['tool_debt'].get('total', '?')} lint violations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
