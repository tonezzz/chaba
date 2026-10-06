#!/usr/bin/env python3
"""kanban-brief.py — Eisenhower card briefing -> CMS `kanban-brief`.

Chaba Nest briefing layer: deterministic scoring decides WHAT to show,
optional micro-model prose decides HOW to say it. Same posture as the
rest of the nest — program ranks, AI narrates, Tony acts.

Scoring (all deterministic, no model call):
  urgent   review column waiting on Tony (verify/decide), blocked_by:
           tony, or a doing card gone stale (>3d without update)
  important priority=high, or N other cards list this id in blocked_by
           (it's a gate)
  quadrants:
    do-first     urgent + important
    schedule     important only
    delegate     urgent only — dispatch candidates (drain unattended)
    park         neither (backlog noise — listed by count only)

Card fields consumed: column, priority, review_kind, blocked_by,
updated, title, note (first line), program, autonomy (T-tier cap —
default T1, cards without autonomy never appear in delegate).

Prose layer (optional): when KANBAN_BRIEF_LLM_URL is set to an
OpenAI-compatible endpoint (e.g. ollama http://host:11434/v1), one
small-model call summarizes each do-first card's "why now". Any failure
falls back to the deterministic one-liner — the page still publishes.

Publishes en+th to ada-cms-pages, same contract as
starboard-tracker-update.py (ada-cms-automation registry gating,
managed block, meta contract).

Env:
    MDDB_BASE_URL        default http://100.102.134.91:11023/v1
    REPO                 default = this checkout root
    KANBAN_BRIEF_LLM_URL e.g. http://tony-omen:11434/v1 (optional)
    KANBAN_BRIEF_LLM_MODEL  default gemma3:4b

Usage:
    kanban-brief.py            # gated by registry interval
    kanban-brief.py --force    # run regardless
    kanban-brief.py --dry-run  # render + print, write nothing
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

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
CARDS_DIR = REPO / "docs/ssot/kanban/cards"
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"
PAGE = "kanban-brief"
BLOCK_BEGIN = "<!-- kanban-brief:auto -->"
BLOCK_END = "<!-- /kanban-brief:auto -->"
BLOCK_RE = re.compile(re.escape(BLOCK_BEGIN) + r".*?" +
                      re.escape(BLOCK_END), re.S)
ICT = timezone(timedelta(hours=7))
SOURCES = ["docs/ssot/kanban/cards/*.yml"]

PRIORITY_W = {"high": 3, "medium": 2, "low": 1}
STALE_DOING_DAYS = 3


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


# ---------- scoring ----------

def load_cards() -> list[dict]:
    out = []
    for f in sorted(CARDS_DIR.glob("*.yml")):
        try:
            c = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        c["_file"] = f.name
        out.append(c)
    return out


def score_cards(cards: list[dict], now: datetime) -> list[dict]:
    blockers_of = {}
    for c in cards:
        for dep in c.get("blocked_by") or []:
            blockers_of[dep] = blockers_of.get(dep, 0) + 1

    scored = []
    for c in cards:
        col = c.get("column") or "backlog"
        if col == "done":
            continue
        cid = c.get("id") or c["_file"][:-4]
        blocked_by = c.get("blocked_by") or []
        review = (c.get("review_kind") or "").strip()

        urgent_reasons = []
        if col == "review" and review in ("verify", "decide", "triage"):
            urgent_reasons.append(f"review:{review}")
        if "tony" in blocked_by:
            urgent_reasons.append("blocked:tony")
        if col == "doing":
            upd = _parse_date(c.get("updated"))
            if upd and (now.date() - upd).days > STALE_DOING_DAYS:
                urgent_reasons.append(
                    f"stale-doing>{STALE_DOING_DAYS}d")
            else:
                urgent_reasons.append("in-flight")

        imp = PRIORITY_W.get(c.get("priority") or "low", 1)
        gates = blockers_of.get(cid, 0)
        important_reasons = []
        if imp >= 3:
            important_reasons.append("priority:high")
        if gates:
            important_reasons.append(f"gates {gates} card{'s' * (gates > 1)}")
        if imp <= 1:
            important_reasons.append("priority:low")

        if urgent_reasons and (imp >= 2 or gates):
            quad = "do-first"
        elif imp >= 2 or gates:
            quad = "schedule"
        elif urgent_reasons:
            quad = "delegate"
        else:
            quad = "park"

        scored.append({
            "id": cid, "title": (c.get("title") or cid)[:80],
            "column": col, "priority": c.get("priority") or "-",
            "program": c.get("program") or "-",
            "autonomy": (c.get("autonomy") or "t1").lower(),
            "quadrant": quad,
            "urgent": urgent_reasons, "important": important_reasons,
            "note1": _first_line(c.get("note") or ""),
        })
    scored.sort(key=lambda s: (
        {"do-first": 0, "delegate": 1, "schedule": 2, "park": 3}[s["quadrant"]],
        -{"high": 3, "medium": 2, "low": 1}.get(s["priority"], 1)))
    return scored


def _parse_date(v):
    try:
        return datetime.fromisoformat(str(v).split("T")[0]).date()
    except (ValueError, TypeError):
        return None


def _first_line(note: str) -> str:
    for ln in str(note).splitlines():
        ln = ln.strip()
        if ln:
            return ln[:140]
    return ""


# ---------- optional prose layer ----------

def llm_why(card: dict) -> str:
    """One-sentence 'why now' from a micro model; None on any failure —
    the deterministic line is always the fallback."""
    url = os.environ.get("KANBAN_BRIEF_LLM_URL", "").rstrip("/")
    if not url:
        return None
    model = os.environ.get("KANBAN_BRIEF_LLM_MODEL", "gemma3:4b")
    prompt = (
        "One sentence, plain, no preamble — why should the operator look "
        "at this kanban card today?\n"
        f"title: {card['title']}\ncolumn: {card['column']}\n"
        f"flags: {', '.join(card['urgent'] + card['important'])}\n"
        f"note: {card['note1'][:300]}")
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            f"{url}/chat/completions",
            data=json.dumps({
                "model": model, "temperature": 0.2, "max_tokens": 60,
                "messages": [{"role": "user", "content": prompt}],
            }).encode(),
            headers={"Content-Type": "application/json"}), timeout=30)
        out = json.load(r)["choices"][0]["message"]["content"].strip()
        return out.splitlines()[0][:200] if out else None
    except Exception:
        return None


# ---------- render ----------

def render(scored: list[dict], now: datetime, lang: str) -> str:
    quads = {"do-first": [], "delegate": [], "schedule": [], "park": []}
    for s in scored:
        quads[s["quadrant"]].append(s)
    th = lang == "th"
    lines = [BLOCK_BEGIN, "",
             f"_updated {now.astimezone(ICT):%Y-%m-%d %H:%M ICT} — "
             f"{len(scored)} open cards_", ""]
    heads = {
        "do-first": "ทำก่อนเลย" if th else "Do first",
        "delegate": "ส่งต่อให้ dispatch ได้" if th else "Delegate-ready (urgent, low-stakes)",
        "schedule": "ไว้ในแผน" if th else "Schedule (important, not urgent)",
        "park": "ที่จอด" if th else "Parked",
    }
    for quad in ("do-first", "delegate", "schedule"):
        items = quads[quad]
        lines += [f"### {heads[quad]} ({len(items)})", ""]
        for s in items[:12]:
            why = llm_why(s) if quad == "do-first" and lang == "en" else None
            flags = ", ".join(s["urgent"] + s["important"])
            lines.append(
                f"- **{s['id']}** [{s['column']}/{s['priority']}"
                f"{'' if s['program'] == '-' else f'/{s['program']}'}] "
                f"{s['title']} — _{flags}_"
                + (f"\n  {why}" if why else ""))
        if not items:
            lines.append("- —")
        lines.append("")
    lines += [f"### {heads['park']} — {len(quads['park'])} cards", ""]
    lines.append(BLOCK_END)
    return "\n".join(lines)


def upsert_block(body: str, block: str) -> str:
    if BLOCK_RE.search(body or ""):
        return BLOCK_RE.sub(lambda m: block, body, count=1)
    m = re.search(r"^## ", body or "", re.M)
    if m:
        return body[:m.start()] + block + "\n\n" + body[m.start():]
    return (body or "").rstrip() + "\n\n" + block + "\n"


def page_body(lang, block, now):
    doc = get_page(lang)
    if doc and doc.get("contentMd"):
        return upsert_block(doc["contentMd"], block)
    title = ("Kanban Brief — การ์ดไหนควรทำวันนี้" if lang == "th"
             else "Kanban Brief — what needs Tony today")
    lead = ("หน้านี้อัปเดตอัตโนมัติโดย chaba — การ์ดจัดลำดับด้วยกติกา "
            "กำหนดตายตัว (urgent = รอ Tony / blocked / stale, "
            "important = priority/blockers)" if lang == "th" else
            "Auto-updated by chaba — cards ranked by deterministic rules "
            "(urgent = waiting on Tony / blocked / stale, "
            "important = priority/blockers). Prose lines may come from a "
            "micro model; the ranking never does.")
    return (f"# {title}\n\n{lead}\n\n{block}\n")


def publish(lang, body, now):
    doc = get_page(lang) or {}
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    meta.update({
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "lang": [lang], "kind": ["report"], "attribute": ["report"],
        "report_role": ["rollup"], "domain": ["bench"],
        "generated_by": ["kanban-brief.py"], "sources": SOURCES,
        "title": ["Kanban Brief" if lang == "en"
                  else "สรุปการ์ดที่ต้องดู"],
        "summary": ["Deterministic Eisenhower ranking of open kanban "
                    "cards — do-first / delegate / schedule / park."],
        "fresh_for": ["1h"], "confidence": ["high"],
        "timeline": [f"{now.isoformat(timespec='minutes')}: brief run"],
        "written_by": ["kanban-brief"],
    })
    _post("add", {"collection": COLLECTION, "key": PAGE, "lang": lang,
                  "contentMd": body, "meta": meta}, timeout=120)


def save_registry(cfg, now):
    meta = {"kind": ["automation-config"], "bank": ["cms"],
            "scope": ["tony"], "status": ["active"], "source": ["api"],
            "written_by": ["kanban-brief"], "subject": [PAGE],
            "attribute": ["automation"], "slug": [PAGE],
            "title": [f"CMS automation: {PAGE}"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    _post("add", {"collection": REGISTRY, "key": PAGE, "lang": "en",
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
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    if not args.dry_run:
        cfg, online = load_registry()
        why = gated(cfg, now, args.force)
        if why:
            print(f"kanban-brief: skipped ({why})")
            return 0
    cards = load_cards()
    scored = score_cards(cards, now)
    block_en = render(scored, now, "en")
    block_th = render(scored, now, "th")
    if args.dry_run:
        print(render(scored, now, "en"))
        return 0
    publish("en", page_body("en", block_en, now), now)
    publish("th", page_body("th", block_th, now), now)
    cfg = dict(cfg)
    cfg.update({"last_run": now.isoformat(timespec="seconds"),
                "run_now": False, "last_cards": len(scored)})
    save_registry(cfg, now)
    print(f"kanban-brief: published ({len(scored)} cards scored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
