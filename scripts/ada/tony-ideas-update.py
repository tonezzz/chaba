#!/usr/bin/env python3
"""tony-ideas-update.py — harvest Tony's direction/decisions -> CMS `tony-ideas`.

Tony-side half of the evidence loop (card tony-ideas-harvest /
nest-evidence-loop): direction-in lands here; evidence-out lands on the
gate pages. Deterministic mining only — no model calls.

Sources mined (per card spec):
  1. kanban card comms from:tony — ops verbs (queued/moved/closed/
     approve acks) filtered, substantive direction kept.
  2. docs/ssot/focus-inbox/*.yml — drafts surface as pending ideas until
     linked/processed; archived items land as superseded; processed/
     counts only (800+ historical items are not re-listed).
  3. docs/ssot/ssot.focus.decisions.yml — intake decision log; bare
     continuation cues ("next?", "continue") dropped.
  4. Ada voice transcripts — DEFERRED (needs transcript mining infra).
  5. Devin session summaries — dispatch-outcome-*.md in the repo root
     land as adopted rows; the ada-ha-bank-devin-tony summary bank is
     counted as coverage only.

Each idea row gains a status: adopted (acted on / linked artifact),
pending (captured, no artifact yet), superseded (archived/replaced).

Page contract: cms-page-standard (status line, Latest, section links,
provenance footer, full meta). The "Standing directions" section is
curated by hand — the live section body is re-extracted and preserved
verbatim on every run; everything inside the two managed blocks is
regenerated. Publishes en only (the mined corpus is English).

Registry gating, managed-block upsert and meta contract mirror
kanban-brief.py.

Env:
    MDDB_BASE_URL        default http://100.102.134.91:11023/v1
    REPO                 default = this checkout root

Usage:
    tony-ideas-update.py            # gated by registry interval
    tony-ideas-update.py --force    # run regardless
    tony-ideas-update.py --dry-run  # render + print, write nothing
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
INBOX_DIR = REPO / "docs/ssot/focus-inbox"
DECISIONS = REPO / "docs/ssot/ssot.focus.decisions.yml"
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"
PAGE = "tony-ideas"
DEVIN_BANK = "ada-ha-bank-devin-tony"
HEAD_BEGIN = "<!-- tony-ideas:head -->"
HEAD_END = "<!-- /tony-ideas:head -->"
TAIL_BEGIN = "<!-- tony-ideas:auto -->"
TAIL_END = "<!-- /tony-ideas:auto -->"
ICT = timezone(timedelta(hours=7))
SOURCES = [
    "docs/ssot/kanban/cards/* comms from:tony",
    "docs/ssot/focus-inbox/*.yml",
    "docs/ssot/ssot.focus.decisions.yml",
    "dispatch-outcome-*.md",
]

MAX_PENDING, MAX_ADOPTED, MAX_SUPERSEDED = 40, 30, 15
LATEST_N = 5

# ---------- ops-noise filters (regex v0; classifier upgrade later) ----------

# Whole-line ops chatter that carries no direction.
OPS_DROP = re.compile(r"^(?:"
                      r"closed\b.*|moved\b.*|queued\s+for\s+processing\.?|"
                      r"retry\s+requested.*|verified\b.*|"
                      r"card\s+captured\s+via\s+board-api.*|"
                      r"filed\s+by\s+devin\b.*|"
                      r"finish\s*&\s*close.*|devin\s+test\b.*|"
                      r"commit\s*&\s*push\.?|commit\.?|"
                      r"merge[,.]?\s*please\.?|merge\.?|please\s+merge\.?|"
                      r"status\?+\s*(?:next\?+)?|next\?+|"
                      r"continue\.?|yes\.?|ok\.?|okay\.?|proceed\.?|"
                      r"approve[ds]?\.?|lgtm\.?|seeded\b.*"
                      r")$", re.I | re.S)

ANSWERED_RE = re.compile(r"^answered\s+([^:]+?):\s*(.*)$", re.I | re.S)
QUEUED_RE = re.compile(r"^queued\s+(?:(\S+):\s*)?(.*)$", re.I | re.S)

# An answer unwrap that is only an ack holds no direction.
ANSWER_ACK = re.compile(r"^(?:yes\.?|no\.?|ok\.?|okay\.?|yes,? please|"
                        r"approve\.?|approved\.?|proceed\.?|continue\.?|"
                        r"close[d]?\.?|status\?|suggestion\?|lgtm\.?|"
                        r"test-probe.*|[a-e])\.?$", re.I)

# Bare continuation cues in the decisions log requests.
CUE_RE = re.compile(r"^(?:next\??|continue\.?|status\??|ok\.?|yes\.?|"
                    r"what\s+is\s+next\??|what'?s\s+next\??)$", re.I)

# Watcher-generated inbox families are ops alerts, not Tony ideas —
# counted as a bucket instead of listed as rows.
WATCHER_LABEL = re.compile(r"^(?:Fix CI:|Report watch:|HA auth failure|"
                           r"Goal rot:|mddb-binlog|Review ARP|"
                           r"SSOT optimize:)", re.I)
WATCHER_FILE = re.compile(r"^(?:gh-run-|report-watch-|ha-auth-|"
                          r"arp-inventory-|mddb-binlog-)", re.I)

OUTCOME_RE = re.compile(r"^dispatch-outcome-(\d{8})-(\d{6})-(.+)\.md$")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _is_ops(text: str) -> bool:
    return bool(OPS_DROP.match(_clean(text)))


def mine_comms(cards: list[dict]) -> tuple[list[dict], int]:
    """from:tony comms -> idea rows. Returns (rows, dropped_ops_count)."""
    col_status = {"done": "adopted", "review": "adopted"}
    rows, dropped = [], 0
    for c in cards:
        cid = c.get("id") or c.get("_file", "")[:-4]
        status = col_status.get(c.get("column"), "pending")
        for cm in c.get("comms") or []:
            if (cm.get("from") or "").lower() != "tony":
                continue
            text = _clean(cm.get("text"))
            if not text:
                dropped += 1
                continue
            if _is_ops(text):
                dropped += 1
                continue
            m = ANSWERED_RE.match(text)
            if m:
                slug, answer = _clean(m.group(1)), _clean(m.group(2))
                if not answer or ANSWER_ACK.match(answer):
                    dropped += 1
                    continue
                text = f"re {slug}: {answer}"
            else:
                q = QUEUED_RE.match(text)
                if q and not _clean(q.group(2)):
                    dropped += 1
                    continue
            rows.append({"date": _parse_date(cm.get("at")),
                         "source": "comms", "ref": f"`{cid}`",
                         "status": status, "text": text})
    return rows, dropped


def mine_inbox() -> tuple[list[dict], dict]:
    rows = []
    counts = {"draft": 0, "watcher": 0, "processed_dir": 0, "archived": 0}
    status_map = {"draft": "pending", "pending": "pending",
                  "processed": "adopted", "linked": "adopted"}
    for f in sorted(INBOX_DIR.glob("*.yml")):
        if f.name == "TEMPLATE.yml":
            continue
        try:
            d = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        fo = d.get("focus") or {}
        label = _clean(fo.get("label")) or f.stem
        if WATCHER_LABEL.match(label) or WATCHER_FILE.match(f.name):
            counts["watcher"] += 1
            continue
        st = status_map.get(fo.get("status"), "pending")
        if st == "pending":
            counts["draft"] += 1
        text = _clean(fo.get("text"))
        sub = [s for s in (fo.get("subtasks") or [])
               if isinstance(s, dict) and s.get("status") == "completed"]
        fm = re.search(r"(20\d\d-\d\d-\d\d)", f.name)
        date = ((fm and _parse_date(fm.group(1)))
                or _parse_date((d.get("source") or {}).get("date"))
                or datetime.fromtimestamp(f.stat().st_mtime, ICT))
        rows.append({"date": date,
                     "source": "inbox", "ref": f"`{f.stem}`",
                     "status": st,
                     "text": f"**{label}** — {text}" if text else label,
                     "_done_sub": len(sub)})
    counts["processed_dir"] = len(list(
        (INBOX_DIR / "processed").glob("*.yml"))) \
        if (INBOX_DIR / "processed").is_dir() else 0
    arch = INBOX_DIR / "archived"
    if arch.is_dir():
        for f in sorted(arch.glob("*.yml")):
            try:
                d = yaml.safe_load(f.read_text()) or {}
            except Exception:
                d = {}
            fo = d.get("focus") or {}
            rows.append({"date": _parse_date(f.name[:10]),
                         "source": "inbox", "ref": f"`{f.stem}`",
                         "status": "superseded",
                         "text": _clean(fo.get("label")) or f.stem})
            counts["archived"] += 1
    return rows, counts


def mine_decisions() -> list[dict]:
    rows = []
    if not DECISIONS.exists():
        return rows
    try:
        d = yaml.safe_load(DECISIONS.read_text()) or {}
    except Exception:
        return rows
    for sec in d.get("sections") or []:
        for it in sec.get("items") or []:
            req = _clean(it.get("request"))
            if not req or CUE_RE.match(req):
                continue
            action = it.get("action") or ""
            if action == "continue":
                continue
            status = "adopted" if action == "active" else "pending"
            target = _clean(it.get("target"))
            text = req + (f" -> {target}" if target else "")
            rows.append({"date": _parse_date(it.get("date")),
                         "source": "decisions", "ref": action,
                         "status": status, "text": text})
    return rows


def mine_outcomes() -> list[dict]:
    rows = []
    for f in REPO.glob("dispatch-outcome-*.md"):
        m = OUTCOME_RE.match(f.name)
        if not m:
            continue
        slug = m.group(3).replace("-", " ")
        rows.append({"date": _parse_date(m.group(1)),
                     "source": "session", "ref": f"`{f.stem}`",
                     "status": "adopted",
                     "text": f"dispatch: {slug}"})
    return rows


def probe_devin_bank() -> bool:
    """Reachability check only — the bank is ~2000 docs, far too heavy to
    list every run."""
    try:
        return bool(_post("search", {"collection": DEVIN_BANK,
                                     "query": "", "limit": 1}))
    except Exception:
        return False


# ---------- dates ----------

def _parse_date(v) -> datetime | None:
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:16] if "H" in fmt else s[:10],
                                     fmt).replace(tzinfo=ICT)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=ICT)
    except ValueError:
        return None


def _d(dt) -> str:
    return dt.strftime("%Y-%m-%d") if dt else "?"


# ---------- MDDB ----------

def _post(path, payload, timeout=60, retries=3):
    import time
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{MDDB}/{path}", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    raise last


def _search_all(collection, page_size=500):
    docs, offset = [], 0
    while True:
        page = _post("search", {"collection": collection, "query": "",
                                "limit": page_size, "offset": offset})
        docs += page
        if len(page) < page_size:
            return docs
        offset += page_size


def get_page(lang="en"):
    docs = _search_all(COLLECTION)
    return next((d for d in docs
                 if d.get("key") == PAGE and d.get("lang") == lang), None)


# ---------- render ----------

def _esc(text: str) -> str:
    return text.replace("|", "\\|")


def _row(it, n=140):
    return (f"| {_d(it['date'])} | {it['source']} | {it['ref']} "
            f"| {_esc(it['text'])[:n]} |")


def _table(items, cap):
    lines = ["| date | src | ref | idea / direction |",
             "|---|---|---|---|"]
    for it in items[:cap]:
        lines.append(_row(it))
    if len(items) > cap:
        lines.append(f"| … | | | _{len(items) - cap} older rows elided_ |")
    if not items:
        lines.append("| — | | | _none_ |")
    return lines


def render(now: datetime, items: list[dict], stats: dict) -> tuple[str, str]:
    """Return (head_block, tail_block)."""
    pending = [i for i in items if i["status"] == "pending"]
    adopted = [i for i in items if i["status"] == "adopted"]
    superseded = [i for i in items if i["status"] == "superseded"]
    newest = sorted((i for i in items if i["date"]),
                    key=lambda i: i["date"], reverse=True)
    by_date = lambda lst: sorted(lst, key=lambda i: i["date"]
                                 or datetime.min.replace(tzinfo=ICT),
                                 reverse=True)

    status_line = (
        f"**Status: {len(items)} mined direction lines — "
        f"{len(adopted)} adopted · {len(pending)} pending · "
        f"{len(superseded)} superseded "
        f"({stats['comms_kept']} comms / {stats['inbox']} inbox / "
        f"{stats['decisions']} decisions / {stats['outcomes']} sessions). "
        "Auto-refreshed every 30 min; standing directions below are "
        "hand-curated.**")

    head = [HEAD_BEGIN, "", status_line, "", "## Latest", ""]
    for it in newest[:LATEST_N]:
        head.append(f"- **{_d(it['date'])}** — [{it['source']} "
                    f"{it['ref']}] {it['text'][:150]}")
    head += ["",
             "Sections: [Standing directions](#standing-directions) · "
             "[Pending ideas](#pending-ideas) · "
             "[Adopted direction](#adopted-direction) · "
             "[Superseded](#superseded) · [Sources & gaps](#sources--gaps)",
             "", HEAD_END]

    tail = [TAIL_BEGIN, "",
            f"## Pending ideas ({len(pending)})", ""]
    tail += _table(by_date(pending), MAX_PENDING)
    tail += ["", f"## Adopted direction ({len(adopted)})", ""]
    tail += _table(by_date(adopted), MAX_ADOPTED)
    tail += ["", f"## Superseded ({len(superseded)})", ""]
    tail += _table(by_date(superseded), MAX_SUPERSEDED)
    tail += ["", "## Sources & gaps", "",
             f"- Card comms `from: tony`: {stats['comms_total']} total → "
             f"{stats['comms_kept']} substantive "
             f"({stats['comms_dropped']} ops lines filtered).",
             f"- Focus-inbox: {stats['inbox']} items listed; "
             f"{stats['watcher']} watcher captures (CI/auth/report-watch/"
             f"SSOT-optimize/ARP) collapsed; {stats['processed_dir']} "
             f"historical items under `processed/` not re-listed.",
             f"- Decisions log: {stats['decisions']} routed requests "
             f"(continuation cues dropped).",
             f"- Devin sessions: {stats['outcomes']} dispatch outcomes "
             f"mined; summary bank `{DEVIN_BANK}` "
             f"{'reachable' if stats['devin_bank'] else 'unreachable'} "
             "(full-text idea mining deferred — needs "
             "transcript/summary mining infra).",
             "- Ada voice transcripts: deferred — needs transcript "
             "mining infra.",
             "- Statuses: `adopted` = card done/review or linked/"
             "processed artifact; `pending` = captured, no artifact yet; "
             "`superseded` = archived. Ops-filter is regex v0 — "
             "classifier upgrade is a follow-up.",
             "",
             f"*Generated by tony-ideas-update.py · "
             f"{now:%Y-%m-%d %H:%M}Z · sources: {len(SOURCES)}*",
             "", TAIL_END]
    return "\n".join(head), "\n".join(tail)


STANDING_RE = re.compile(r"^## [^\n]*standing[^\n]*\n.*?(?=^## |\Z)",
                         re.I | re.S | re.M)


MARKER_RE = re.compile(r"<!--\s*/?tony-ideas:(?:auto|head)\s*-->\n?")


def page_body(head: str, tail: str) -> str:
    """Rebuild the page: H1 + head block + curated standing section +
    tail block. The standing section is re-extracted from the live doc
    verbatim — it is the hand-curated part."""
    doc = get_page("en")
    live = (doc or {}).get("contentMd") or ""
    m = STANDING_RE.search(live)
    if m:
        # the capture may bleed a managed-block marker — strip it
        standing = MARKER_RE.sub("", m.group(0)).rstrip()
    else:
        standing = ("## Standing directions (recurring principles Tony "
                    "has set)\n\n_(curated by hand — rows added as "
                    "standing principles emerge)_")
    title = "Tony ideas — direction lines, decisions, standing principles"
    return (f"# {title}\n\n{head}\n\n{standing}\n\n{tail}\n")


def publish(body: str, now: datetime, stats: dict):
    doc = get_page("en") or {}
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    meta.update({
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "lang": ["en"], "kind": ["page"], "slug": [PAGE],
        "format": ["markdown"], "bank": ["chaba"], "scope": ["project"],
        "status": ["active"], "source": ["kanban card comms"],
        "sources": SOURCES,
        "written_by": ["tony-ideas-update"],
        "subject": ["tony", "ideas", "direction"],
        "attribute": ["report"], "report_role": ["rollup"],
        "domain": ["direction"],
        "title": ["Tony ideas — direction lines, decisions, "
                  "standing principles"],
        "summary": [f"{stats['total']} mined direction lines — "
                    f"{stats['adopted']} adopted / {stats['pending']} "
                    f"pending / {stats['superseded']} superseded"],
        "fresh_for": ["1h"], "confidence": ["medium"],
        "timeline": [f"{now.isoformat(timespec='minutes')}: harvest run"],
    })
    meta.setdefault("valid_from", [now.date().isoformat()])
    _post("add", {"collection": COLLECTION, "key": PAGE, "lang": "en",
                  "contentMd": body, "meta": meta}, timeout=120)


# ---------- registry (same contract as kanban-brief) ----------

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


def save_registry(cfg, now):
    meta = {"kind": ["automation-config"], "bank": ["cms"],
            "scope": ["tony"], "status": ["active"], "source": ["api"],
            "written_by": ["tony-ideas-update"], "subject": [PAGE],
            "attribute": ["automation"], "slug": [PAGE],
            "title": [f"CMS automation: {PAGE}"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    _post("add", {"collection": REGISTRY, "key": PAGE, "lang": "en",
                  "contentMd": json.dumps(cfg, ensure_ascii=False,
                                          indent=2), "meta": meta},
          timeout=120)


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
            print(f"tony-ideas: skipped ({why})")
            return 0

    cards = load_cards()
    comm_rows, dropped = mine_comms(cards)
    inbox_rows, inbox_counts = mine_inbox()
    dec_rows = mine_decisions()
    out_rows = mine_outcomes()
    items = comm_rows + inbox_rows + dec_rows + out_rows

    comm_total = sum(1 for c in cards for cm in (c.get("comms") or [])
                     if (cm.get("from") or "").lower() == "tony")
    stats = {
        "comms_total": comm_total, "comms_dropped": dropped,
        "comms_kept": len(comm_rows),
        "inbox": len(inbox_rows),
        "watcher": inbox_counts.get("watcher", 0),
        "processed_dir": inbox_counts.get("processed_dir", 0),
        "decisions": len(dec_rows), "outcomes": len(out_rows),
        "devin_bank": probe_devin_bank(),
        "total": len(items),
        "pending": sum(1 for i in items if i["status"] == "pending"),
        "adopted": sum(1 for i in items if i["status"] == "adopted"),
        "superseded": sum(1 for i in items if i["status"] == "superseded"),
    }

    head, tail = render(now, items, stats)
    if args.dry_run:
        try:
            print(page_body(head, tail))
        except Exception as e:
            print(f"(live page fetch failed: {e} — blocks only)\n")
            print(head + "\n\n" + tail)
        print(f"\nstats: {json.dumps(stats, indent=1)}")
        return 0

    body = page_body(head, tail)
    publish(body, now, stats)
    cfg = dict(cfg)
    cfg.update({"last_run": now.isoformat(timespec="seconds"),
                "run_now": False, "last_items": len(items)})
    save_registry(cfg, now)
    print(f"tony-ideas: published ({stats['adopted']} adopted / "
          f"{stats['pending']} pending / {stats['superseded']} superseded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
