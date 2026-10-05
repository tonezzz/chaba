#!/usr/bin/env python3
"""report-daily-brief.py — L2 'daily-brief' node, morning + evening editions.

Morning (~07:05, after the overnight producers + 06:45 system report):
overnight results — dispatches completed/failed since 19:00, new cards
filed, red health flags, top open requests.

Evening (~19:05): the day's completions plus "what still needs you
before tomorrow" — unanswered board requests, the stale review queue,
failed dispatches.

Writes (per docs/ssot/infrastructure/ssot.reports.yml):
  reports/daily-brief/DAILY-BRIEF-<yyyymmdd>-<edition>.md   dated artifact
  reports/meta.daily-brief.yml                            node meta
  ~/var/chaba/reports/timeline.jsonl                      one appended event
  stacks/web/public/apps/system-report/data/DAILY-BRIEF.md  latest copy
  ada-cms-pages/daily-brief                               CMS page (kind:report)

Usage:
  report-daily-brief.py                     # edition auto (hour<12=morning)
  report-daily-brief.py --edition evening
  report-daily-brief.py --print             # render only, write nothing

Data sources (all best-effort — a missing source degrades a section,
never kills the brief):
  cards       GET $BOARD_API/cards (default http://127.0.0.1:8787), or
              --cards-dir to scan docs/ssot/kanban/cards/*.yml directly
  dispatches  $DISPATCH_DIR/tasks/*/meta.json
              (default ~/.local/share/devin-dispatch)
  health      reports/system-report.yml node states +
              ~/var/chaba/health/meta.yml + tony-dell-mcp-health.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import yaml  # noqa: E402

from lib.report import append_timeline, now_iso, write_meta  # noqa: E402

NODE = "daily-brief"
LAYER = "L2-domain"
OUT_DIR = REPO / "reports" / "daily-brief"
META = REPO / "reports" / "meta.daily-brief.yml"
WEB_DATA = Path("stacks/web/public/apps/system-report/data")
SERVED_ROOT = Path("/home/tony/CascadeProjects/chaba-tony-dell")
SYSTEM_REPORT_YML = REPO / "reports" / "system-report.yml"
FOCUS_DIR = REPO / "docs" / "ssot" / "focus-inbox"
HEALTH_DIR = Path("~/var/chaba/health").expanduser()
DISPATCH_DIR = Path(
    os.environ.get("DISPATCH_DIR", "~/.local/share/devin-dispatch")
).expanduser() / "tasks"
BOARD_API = os.environ.get("BOARD_API", "http://127.0.0.1:8787").rstrip("/")
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.74.146.0:11023/v1").rstrip("/")
CMS_SLUG = "daily-brief"
REVIEW_STALE_H = 24  # same bar as the board's Needs You strip
MAX_LIST = 8

_LOCAL = datetime.datetime.now().astimezone().tzinfo


def _parse_iso(s) -> datetime.datetime | None:
    if not s:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt.astimezone() if dt.tzinfo
            else dt.replace(tzinfo=_LOCAL))


def _parse_card_ts(s) -> datetime.datetime | None:
    """Card timestamps are naive local: 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD'."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).replace(tzinfo=_LOCAL)
        except ValueError:
            continue
    return _parse_iso(s)


def _fmt(dt: datetime.datetime | None) -> str:
    return dt.strftime("%m-%d %H:%M") if dt else "-"


def _age(dt: datetime.datetime | None) -> str:
    if not dt:
        return "?"
    secs = max(0, int((datetime.datetime.now(_LOCAL) - dt).total_seconds()))
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


# ---------------------------------------------------------------- sources

def _cards_from_api() -> list[dict]:
    req = urllib.request.Request(f"{BOARD_API}/cards")
    with urllib.request.urlopen(req, timeout=10) as r:
        payload = json.loads(r.read())
    cards = payload.get("cards", payload) if isinstance(
        payload, dict) else payload
    return cards if isinstance(cards, list) else []


def load_cards(cards_dir: Path | None) -> list[dict]:
    """Card state: --cards-dir (live served checkout preferred — its git
    log is the 'filed' signal) or the board API, with mutual fallback."""
    if cards_dir is None or not Path(cards_dir).is_dir():
        if cards_dir is not None:
            print(f"warn: cards dir {cards_dir} missing; using board-api",
                  file=sys.stderr)
        try:
            return _cards_from_api()
        except Exception as e:
            print(f"warn: board-api unreachable ({e}); "
                  "falling back to card dir", file=sys.stderr)
            cards_dir = REPO / "docs" / "ssot" / "kanban" / "cards"
    cards = []
    for p in sorted(Path(cards_dir).glob("*.yml")):
        try:
            c = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        c.setdefault("id", p.stem)
        cards.append(c)
    return cards


def load_dispatches() -> list[dict]:
    """devin-dispatch task ledger — the ground truth for task results."""
    out = []
    if not DISPATCH_DIR.is_dir():
        return out
    for d in DISPATCH_DIR.iterdir():
        meta_p = d / "meta.json"
        if not meta_p.is_file():
            continue
        try:
            m = json.loads(meta_p.read_text())
        except Exception:
            continue
        rec = {
            "id": d.name,
            "repo": m.get("repo"),
            "result": m.get("result"),
            "started_at": _parse_iso(m.get("started_at")),
            "finished_at": _parse_iso(m.get("finished_at")),
            "worktree": m.get("worktree"),
        }
        ec = d / "exit_code"
        try:
            code = int(ec.read_text().strip())
            if code != 0 and rec["result"] == "success":
                rec["result"] = "exit-code"
        except Exception:
            pass
        out.append(rec)
    return out


def dispatch_outcome(rec: dict) -> str:
    """First prose line of the task's dispatch-outcome*.md, if it survives
    (sessions write per-id files — dispatch-outcome-<task_id>.md)."""
    wt = rec.get("worktree")
    if not wt:
        return ""
    for p in sorted(Path(wt).glob("dispatch-outcome*.md")):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line[:140]
        except Exception:
            pass
    return ""


def health_flags() -> list[str]:
    """Red flags: bad node states from the last system report +
    health-monitor unhealthy count + critical/high MCP recommendations."""
    flags = []
    try:
        doc = yaml.safe_load(SYSTEM_REPORT_YML.read_text()) or {}
        for n in doc.get("nodes") or []:
            if n.get("status") in ("missing", "stale", "error"):
                flags.append(f"report node {n.get('id')}={n.get('status')}")
    except Exception:
        pass
    try:
        meta = yaml.safe_load((HEALTH_DIR / "meta.yml").read_text()) or {}
        bad = (meta.get("extra") or {}).get("unhealthy") or 0
        if meta.get("status") not in ("ok", None) or bad:
            flags.append(f"health-monitor: {meta.get('summary', 'unhealthy')}")
    except Exception:
        pass
    try:
        mcp = json.loads((HEALTH_DIR / "tony-dell-mcp-health.json").read_text())
        for r in mcp.get("recommendations") or []:
            if r.get("severity") in ("critical", "high"):
                flags.append(f"{r.get('service')}: {r.get('message', '')[:80]}")
    except Exception:
        pass
    return flags


def focus_inbox_count() -> int:
    try:
        return sum(1 for p in FOCUS_DIR.iterdir()
                   if p.is_file() and p.suffix in (".yml", ".yaml")
                   and not p.name.startswith("TEMPLATE"))
    except OSError:
        return 0


# ------------------------------------------------------------ derivations

def window(edition: str, now: datetime.datetime) -> tuple[datetime.datetime,
                                                         datetime.datetime]:
    if edition == "morning":
        start = (now - datetime.timedelta(days=1)).replace(
            hour=19, minute=0, second=0, microsecond=0)
        if start > now:  # running before 19:00 next day edge
            start -= datetime.timedelta(days=1)
        return start, now
    return now.replace(hour=0, minute=0, second=0, microsecond=0), now


def dispatches_in(disp: list[dict], start, end) -> dict:
    done, failed, running = [], [], []
    for r in disp:
        fin = r["finished_at"]
        if fin and start <= fin <= end:
            (done if r["result"] == "success" else failed).append(r)
        elif not fin and r["started_at"] and r["started_at"] <= end:
            running.append(r)
    done.sort(key=lambda r: r["finished_at"], reverse=True)
    failed.sort(key=lambda r: r["finished_at"], reverse=True)
    return {"done": done, "failed": failed, "running": running}


def _git_added_cards(cards_dir: Path, start) -> dict[str, datetime.datetime]:
    """Card ids first committed since `start` — the truthful 'filed'
    signal (kanban-commit pushes the served checkout's cards every 15min).
    Empty dict when the dir isn't a git checkout."""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "-C", str(cards_dir), "log", "--diff-filter=A",
             f"--since={start.isoformat()}", "--format=%ct", "--name-only",
             "--", "."],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return {}
    if r.returncode != 0:
        return {}
    out: dict[str, datetime.datetime] = {}
    ts = None
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.isdigit():
            ts = datetime.datetime.fromtimestamp(int(line), tz=_LOCAL)
        elif line.endswith((".yml", ".yaml")) and ts:
            cid = Path(line).stem
            out.setdefault(cid, ts)  # newest-first log — first wins
    return out


def new_cards(cards: list[dict], start, end,
              cards_dir: Path | None) -> tuple[list[dict], str]:
    """Cards filed in window. Preferred source: git --diff-filter=A on the
    cards dir. Fallback (non-git dir): earliest comms entry / `updated`."""
    d = cards_dir or (REPO / "docs" / "ssot" / "kanban" / "cards")
    added = _git_added_cards(d, start)
    if added:
        by_id = {c.get("id"): c for c in cards}
        out = [{"id": cid, "title": (by_id.get(cid) or {}).get("title"),
                "at": ts}
               for cid, ts in added.items() if start <= ts <= end]
        out.sort(key=lambda c: c["at"], reverse=True)
        return out, "git"
    out = []
    for c in cards:
        stamps = [_parse_card_ts(e.get("at")) for e in c.get("comms") or []]
        stamps = [s for s in stamps if s]
        first = min(stamps) if stamps else _parse_card_ts(c.get("updated"))
        if first and start <= first <= end:
            out.append({"id": c.get("id"), "title": c.get("title"),
                        "at": first})
    out.sort(key=lambda c: c["at"], reverse=True)
    return out, "comms-heuristic"


def open_requests(cards: list[dict]) -> list[dict]:
    out = []
    for c in cards:
        for r in c.get("requests") or []:
            if r.get("status") == "open":
                out.append({"card": c.get("id"), "ask": r.get("ask", ""),
                            "card_updated": _parse_card_ts(c.get("updated"))})
    out.sort(key=lambda r: r["card_updated"]
             or datetime.datetime.min.replace(tzinfo=_LOCAL), reverse=True)
    return out


def review_queue(cards: list[dict]) -> list[dict]:
    out = []
    now = datetime.datetime.now(_LOCAL)
    for c in cards:
        if c.get("column") != "review":
            continue
        upd = _parse_card_ts(c.get("updated"))
        age_h = ((now - upd).total_seconds() / 3600) if upd else None
        out.append({"id": c.get("id"), "title": c.get("title"),
                    "updated": upd, "age_h": age_h,
                    "stale": age_h is None or age_h > REVIEW_STALE_H})
    out.sort(key=lambda c: -(c["age_h"] or 9999))
    return out


def failed_cards(cards: list[dict]) -> list[dict]:
    return [{"id": c.get("id"), "title": c.get("title"),
             "result": (c.get("action") or {}).get("result", "")}
            for c in cards
            if (c.get("action") or {}).get("status") == "failed"]


# ----------------------------------------------------------------- render

def needs_you_line(reqs, review, failed_cards_, failed_disp) -> str:
    parts = []
    if reqs:
        parts.append(f"{len(reqs)} open request(s): " + "; ".join(
            f"{r['card']}: {r['ask'][:60]}" for r in reqs[:3]))
    stale = [r for r in review if r["stale"]]
    if review:
        parts.append(f"{len(review)} card(s) in review"
                     + (f" ({len(stale)} stale >{REVIEW_STALE_H}h)"
                        if stale else ""))
    if failed_cards_:
        parts.append("failed card action(s): " + ", ".join(
            c["id"] for c in failed_cards_[:3]))
    if failed_disp:
        parts.append("failed dispatch(es): " + ", ".join(
            r["id"][:20] for r in failed_disp[:3]))
    return " | ".join(parts) if parts else "nothing pending"


def _dispatch_table(rows: list[dict], card_by_task: dict) -> list[str]:
    if not rows:
        return ["_None._", ""]
    lines = ["| Task | Card | Result | Finished | Outcome |",
             "|------|------|--------|----------|---------|"]
    for r in rows[:MAX_LIST]:
        card = card_by_task.get(r["id"], "-")
        oc = dispatch_outcome(r) or "-"
        lines.append(f"| `{r['id'][:30]}` | `{card}` | {r['result'] or '?'} | "
                     f"{_fmt(r['finished_at'])} | {oc} |")
    if len(rows) > MAX_LIST:
        lines.append(f"| … | | | | {len(rows) - MAX_LIST} more |")
    return lines + [""]


def render(edition: str, start, end, disp, cards, flags,
           cards_dir: Path | None) -> tuple[str, str]:
    now = datetime.datetime.now(_LOCAL)
    reqs = open_requests(cards)
    review = review_queue(cards)
    fcards = failed_cards(cards)
    card_by_task = {(c.get("action") or {}).get("task_id"): c.get("id")
                    for c in cards if (c.get("action") or {}).get("task_id")}
    d = dispatches_in(disp, start, end)
    title = f"Daily Brief — {'Morning' if edition == 'morning' else 'Evening'} Edition"
    needs = needs_you_line(reqs, review, fcards, d["failed"])
    zombies = [r for r in d["running"]
               if r["started_at"]
               and (now - r["started_at"]).total_seconds() > 86400]
    if zombies:
        needs += (f" | {len(zombies)} stale-running dispatch(es): "
                  + ", ".join(r["id"][:20] for r in zombies[:3]))

    lines = [
        f"# {title}",
        "",
        f"- Generated: {now_iso()} by `scripts/report-daily-brief.py`",
        f"- Window: {_fmt(start)} -> {_fmt(end)}",
        f"- **Needs Tony:** {needs}",
        "",
    ]

    if edition == "morning":
        lines += [
            f"## Overnight dispatches ({len(d['done'])} ok, "
            f"{len(d['failed'])} failed, {len(d['running'])} running)",
            "",
        ] + _dispatch_table(d["done"] + d["failed"], card_by_task)
        if d["running"]:
            now_ = datetime.datetime.now(_LOCAL)
            lines += ["Running now: " + ", ".join(
                f"`{r['id'][:30]}`" + (
                    " *(stale — no finished_at)*"
                    if r["started_at"]
                    and (now_ - r["started_at"]).total_seconds() > 86400
                    else "")
                for r in d["running"][:5]), ""]
        nc, nc_src = new_cards(cards, start, end, cards_dir)
        lines += [f"## New cards filed ({len(nc)})", ""]
        if nc_src == "comms-heuristic":
            lines += ["_approx — via earliest comms/`updated` "
                      "(no git history available)_", ""]
        lines += [f"- {_fmt(c['at'])} `{c['id']}` — {c['title'] or ''}"
                  for c in nc[:MAX_LIST]] or []
        if not nc:
            lines.append("_None._")
        lines.append("")
        lines += ["## Red flags", ""]
        lines += [f"- {f}" for f in flags] or ["_None._"]
        lines.append("")
        lines += [f"## Open requests ({len(reqs)} unanswered)", ""]
        for r in reqs[:MAX_LIST]:
            lines.append(f"- `{r['card']}` — {r['ask']}")
        if not reqs:
            lines.append("_None._")
        lines.append("")
    else:
        lines += [
            f"## Today's completions ({len(d['done'])} dispatches finished, "
            f"{len(d['failed'])} failed)",
            "",
        ] + _dispatch_table(d["done"] + d["failed"], card_by_task)
        moved = [c for c in cards
                 if c.get("column") == "done"
                 and _parse_card_ts(c.get("updated"))
                 and start <= _parse_card_ts(c.get("updated")) <= end]
        lines += [f"## Cards closed today ({len(moved)})", ""]
        lines += [f"- `{c['id']}` — {c.get('title') or ''}"
                  for c in moved[:MAX_LIST]] or []
        if not moved:
            lines.append("_None._")
        lines.append("")
        lines += ["## What still needs you before tomorrow", ""]
        lines += [f"### Open requests ({len(reqs)} unanswered)", ""]
        for r in reqs[:MAX_LIST]:
            lines.append(f"- `{r['card']}` — {r['ask']}")
        if not reqs:
            lines.append("_None._")
        lines.append("")
        stale = [r for r in review if r["stale"]]
        lines += [f"### Review queue ({len(review)} waiting, "
                  f"{len(stale)} stale >{REVIEW_STALE_H}h)", ""]
        for r in review[:MAX_LIST]:
            mark = " **stale**" if r["stale"] else ""
            lines.append(f"- `{r['id']}` — {r['title'] or ''} "
                         f"(age {_age(r['updated'])}){mark}")
        if not review:
            lines.append("_Queue clear._")
        lines.append("")
        all_failed = fcards + [{"id": r["id"],
                                "result": r["result"] or "?"}
                               for r in d["failed"]]
        lines += [f"### Failed dispatches/actions ({len(all_failed)})", ""]
        for f in all_failed[:MAX_LIST]:
            lines.append(f"- `{f['id']}` — {f.get('result', '')[:100]}")
        if not all_failed:
            lines.append("_None._")
        lines.append("")
        if zombies:
            lines += ["### Stale running dispatches (no finished_at >24h)",
                      ""]
            for r in zombies[:MAX_LIST]:
                lines.append(f"- `{r['id'][:40]}` — started "
                             f"{_fmt(r['started_at'])}")
            lines.append("")

    lines += [
        "## Context",
        "",
        f"- Focus inbox: {focus_inbox_count()} open item(s)",
        f"- Board: {len(cards)} cards; "
        f"{sum(1 for c in cards if c.get('column') == 'review')} in review, "
        f"{sum(1 for c in cards if c.get('column') == 'doing')} doing",
        "",
        "_Generated file — do not hand-edit._",
        "",
    ]
    return "\n".join(lines), needs


# --------------------------------------------------------------- outputs

def _mddb_post(path: str, payload: dict, timeout: int = 30):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def publish_cms(md: str, edition: str, summary: str) -> bool:
    """Upsert ada-cms-pages/daily-brief — kind:report, full meta_contract
    (summary/domain/fresh_for/confidence/timeline/links/updated). Caller
    re-renders reports-index after this so Ada sees it immediately."""
    now = now_iso()
    existing = {}
    try:
        existing = _mddb_post("get", {"collection": "ada-cms-pages",
                                      "key": CMS_SLUG, "lang": "en"}) or {}
    except Exception:
        pass
    meta = {k: (v if isinstance(v, list) else [v])
            for k, v in (existing.get("meta") or {}).items()}
    meta.setdefault("bank", ["cms"])
    meta.setdefault("scope", ["tony"])
    meta.setdefault("status", ["active"])
    meta.setdefault("source", ["api"])
    meta.setdefault("subject", [CMS_SLUG])
    meta.setdefault("attribute", ["page"])
    meta.update({
        "kind": ["report"], "slug": [CMS_SLUG],
        "title": [f"Daily Brief — {edition.title()} {now[:10]}"],
        "format": ["markdown"], "lang": ["en"],
        "updated": [now], "last_verified": [now[:10]],
        "domain": ["ops"], "summary": [summary[:240]],
        "fresh_for": ["12h"], "confidence": ["high"],
        "links": ["system-report"], "written_by": ["report-daily-brief.py"],
    })
    tl = [x for x in meta.get("timeline", []) if isinstance(x, str)]
    tl.append(f"{now[:16]} {edition} edition published")
    meta["timeline"] = tl[-40:]
    _mddb_post("add", {"collection": "ada-cms-pages", "key": CMS_SLUG,
                       "lang": "en", "contentMd": md, "meta": meta},
               timeout=60)
    return True


def regen_reports_index() -> bool:
    """Refresh ada-cms-pages/reports-index after publishing.

    The canonical regen (ada-pi tool_runner._cms_reports_index) only fires
    on Ada's own cms tool writes — raw /v1/add never triggers it, and the
    whole point of the brief is that the index is fresh at 07:05 after a
    quiet night. Same table format; written_by stays honest."""
    docs = _mddb_post("search", {"collection": "ada-cms-pages",
                                 "limit": 200})
    if isinstance(docs, dict):
        docs = docs.get("documents") or docs.get("docs") or []
    now = datetime.datetime.now(datetime.timezone.utc)

    def stale(meta: dict) -> bool:
        ff = (meta.get("fresh_for") or [""])[0]
        upd = (meta.get("updated") or [""])[0]
        if not ff or not upd:
            return False
        try:
            secs = int(float(ff[:-1]) * {"h": 3600, "d": 86400,
                                         "m": 60}[ff[-1]])
            dt = datetime.datetime.fromisoformat(
                upd.replace("Z", "+00:00"))
            return (now - dt).total_seconds() > secs
        except Exception:
            return False

    rows = []
    for d in docs:
        meta = d.get("meta") or {}
        kind = (meta.get("kind") or [""])[0]
        if kind not in ("report", "page"):
            continue
        slug = (meta.get("slug") or [d.get("key") or "?"])[0]
        if slug == "reports-index":
            continue
        rows.append({
            "slug": slug,
            "title": (meta.get("title") or [slug])[0],
            "domain": (meta.get("domain") or ["-"])[0],
            "summary": (meta.get("summary") or [""])[0],
            "updated": (meta.get("updated") or ["-"])[0][:16],
            "fresh": (meta.get("fresh_for") or ["-"])[0],
            "stale": stale(meta),
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    lines = [f"# Reports index — {now:%Y-%m-%d %H:%M}Z\n",
             "Brief summaries of every report page — read the linked page",
             "only when the summary isn't enough.\n",
             "| slug | domain | updated | fresh | summary |",
             "|---|---|---|---|---|"]
    for r in rows[:60]:
        flag = " ⚠STALE" if r["stale"] else ""
        summ = (r["summary"] or r["title"])[:80]
        lines.append(f"| {r['slug']} | {r['domain']} | {r['updated']}"
                     f"{flag} | {r['fresh']} | {summ} |")
    _mddb_post("add", {
        "collection": "ada-cms-pages", "key": "reports-index", "lang": "en",
        "contentMd": "\n".join(lines),
        "meta": {
            "kind": ["page"], "slug": ["reports-index"],
            "title": [f"Reports index — {now:%Y-%m-%d %H:%M}Z"],
            "format": ["markdown"], "domain": ["meta"],
            "summary": ["Auto-generated index of report pages — "
                        "slug, domain, staleness, one-line brief."],
            "fresh_for": ["6h"],
            "updated": [now.isoformat(timespec="seconds")],
            "written_by": ["report-daily-brief.py"],
        }}, timeout=60)
    return True


def mirror_web(md: str) -> list[str]:
    """Latest-edition copy at .../system-report/data/DAILY-BRIEF.md —
    dual-root (repo + served chaba-tony-dell checkout) like
    report-system.py."""
    written = []
    for root in (REPO, SERVED_ROOT):
        data = root / WEB_DATA
        try:
            if not data.parent.parent.exists():
                continue
            data.mkdir(parents=True, exist_ok=True)
            (data / "DAILY-BRIEF.md").write_text(md, encoding="utf-8")
            written.append(str(data / "DAILY-BRIEF.md"))
        except OSError as e:
            print(f"warn: mirror {data} failed ({e})", file=sys.stderr)
    return written


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--edition", choices=["auto", "morning", "evening"],
                   default="auto")
    p.add_argument("--cards-dir", type=Path, default=None,
                   help="scan card YAML dir instead of the board API")
    p.add_argument("--meta", type=Path, default=META)
    p.add_argument("--output-dir", type=Path, default=OUT_DIR)
    p.add_argument("--no-cms", action="store_true")
    p.add_argument("--print", dest="print_only", action="store_true")
    args = p.parse_args()

    now = datetime.datetime.now(_LOCAL)
    edition = args.edition
    if edition == "auto":
        edition = "morning" if now.hour < 12 else "evening"
    start, end = window(edition, now)

    cards = load_cards(args.cards_dir)
    disp = load_dispatches()
    flags = health_flags()
    md, needs = render(edition, start, end, disp, cards, flags,
                       args.cards_dir)

    d = dispatches_in(disp, start, end)
    review = review_queue(cards)
    reqs = open_requests(cards)
    n_stale = sum(1 for r in review if r["stale"])
    findings = len(d["failed"]) + len(flags) + len(reqs) + n_stale
    status = "delta" if findings else "ok"
    summary = (f"{edition} brief: {len(d['done'])} dispatches ok/"
               f"{len(d['failed'])} failed; {len(flags)} red flag(s); "
               f"needs-Tony: {len(reqs)} open request(s), "
               f"{len(review)} review ({n_stale} stale)")[:240]

    if args.print_only:
        print(md)
        print(f"---\nstatus={status} summary={summary}")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifact = (args.output_dir /
                f"DAILY-BRIEF-{now.strftime('%Y%m%d')}-{edition}.md")
    artifact.write_text(md, encoding="utf-8")
    web = mirror_web(md)

    write_meta(args.meta, node=NODE, layer=LAYER,
               generated_by="python3 scripts/report-daily-brief.py "
                            f"--edition {edition}",
               purpose=("Twice-daily rollup for Tony — overnight results "
                        "(morning) / day completions + what still needs "
                        "him (evening)"),
               status=status, summary=summary,
               sources=[str(artifact), str(SYSTEM_REPORT_YML),
                        str(HEALTH_DIR / "meta.yml"),
                        f"{BOARD_API}/cards", str(DISPATCH_DIR)],
               children=["health-monitor", "focus-inbox"],
               extra={
                   "edition": edition,
                   "window": [start.isoformat(), end.isoformat()],
                   "dispatches_ok": len(d["done"]),
                   "dispatches_failed": len(d["failed"]),
                   "dispatches_running": len(d["running"]),
                   "open_requests": len(reqs),
                   "review_waiting": len(review),
                   "review_stale": n_stale,
                   "red_flags": len(flags),
                   "new_cards": (len(new_cards(cards, start, end,
                                               args.cards_dir)[0])
                                 if edition == "morning" else None),
                   "needs_you": needs,
               })
    append_timeline(NODE, "L2", status, summary, ref=artifact)

    cms_ok = False
    if not args.no_cms:
        try:
            cms_ok = publish_cms(md, edition, summary)
        except Exception as e:
            # MDDB /v1/add occasionally drops the response AFTER the write
            # lands — treat as warn; the page is verified via get below.
            print(f"warn: CMS publish response lost ({e})", file=sys.stderr)
        try:
            # regen runs even when the publish response was lost: the write
            # usually landed anyway, and the index render is read-only on
            # our page (it lists whatever meta is stored).
            regen_reports_index()
        except Exception as e:
            print(f"warn: reports-index regen failed ({e})",
                  file=sys.stderr)
        try:
            doc = _mddb_post("get", {"collection": "ada-cms-pages",
                                     "key": CMS_SLUG, "lang": "en"})
            upd = ((doc or {}).get("meta") or {}).get("updated") or ["?"]
            print(f"CMS page verified: {CMS_SLUG} (updated {upd[0]})")
        except Exception as e:
            print(f"warn: CMS page verify failed ({e})", file=sys.stderr)

    print(f"edition={edition} status={status}")
    print(f"Wrote {artifact}")
    for w in web:
        print(f"Wrote {w}")
    print(f"Wrote {args.meta}")
    if cms_ok:
        print(f"Published CMS page: {CMS_SLUG}")
    print(f"Summary: {summary}")
    print(f"Needs Tony: {needs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
