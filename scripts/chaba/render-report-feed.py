#!/usr/bin/env python3
"""render-report-feed.py — compose Chaba/Ada state into a hierarchical
JSON report feed for the chaba-home Report tab.

Reads local files only (no network, no LLM):
  docs/ssot/ssot.focus.current.active.yml     chaba focus sections
  docs/ssot/ssot.focus.current.backlog.yml    ready-safe / hand-off / quick wins
  docs/ssot/focus-inbox/*.yml                 unprocessed inbox
  ~/.local/share/ada-review/focus-digest.md   '## focus: <tag>' rollup blocks
  ~/.local/share/ada-review/session-ops.jsonl per-session ops metrics
  ~/.local/share/ada-review/host-ops.jsonl    per-host health sweep
  ~/.local/share/ada-review/events.md         ada events rolling log
  ~/.local/share/ada-review/session-memory.md per-session digests (last N)
  ~/.local/share/chaba/recent-events.yml      chaba hot-tier events

Output node shape (children recurse):
  {id, title, icon, badge, summary, body, meta{status,priority,tags}, children[]}

Usage:
  render-report-feed.py --output chaba-report.json
  render-report-feed.py --output /tmp/r.json --host tony-dell   # also scp to HA www
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FOCUS_ACTIVE = REPO / "docs/ssot/ssot.focus.current.active.yml"
FOCUS_BACKLOG = REPO / "docs/ssot/ssot.focus.current.backlog.yml"
FOCUS_INBOX = REPO / "docs/ssot/focus-inbox"
ADA_REVIEW = Path("~/.local/share/ada-review").expanduser()
CHABA_DATA = Path("~/.local/share/chaba").expanduser()
REMOTE_WWW = "~/.config/home-assistant/www/chaba-report.json"

ICON_MAP = {
    "Active Shared Focus": "mdi:account-star",
    "Active Branch Focus": "mdi:source-branch",
    "Quick Wins": "mdi:lightning-bolt-outline",
    "Hand-Off Queue": "mdi:hand-back-right-outline",
    "Hand-off Queue": "mdi:hand-back-right-outline",
    "Ready (Safe)": "mdi:check-decagram-outline",
    "Ready-Safe Queue": "mdi:check-decagram-outline",
}


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def md_blocks(path: Path, min_chars: int = 20) -> list[dict]:
    """Split a rolling-log markdown file into {heading, body} on '## ' lines."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    out = []
    for block in re.split(r"\n(?=## )", text):
        block = block.strip()
        if not block.startswith("## ") or len(block) < min_chars:
            continue
        head, _, body = block.partition("\n")
        out.append({"heading": head[3:].strip(), "body": body.strip()})
    return out


def first_line(text: str, n: int = 140) -> str:
    s = " ".join((text or "").split())
    return s[: n - 1] + "…" if len(s) > n else s


def slugify(text: str, n: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:n] or "x"


def node(id_: str, title: str, **kw) -> dict:
    n = {"id": id_, "title": title, "children": kw.get("children") or []}
    for k in ("icon", "badge", "summary", "body", "meta"):
        if kw.get(k) is not None:
            n[k] = kw[k]
    return n


# ---------- L1: chaba focus ----------

def focus_item_node(item: dict, sec_icon: str) -> dict:
    status = item.get("status", "")
    subtasks = item.get("subtasks") or []
    kids = [
        node(f"sub-{i}", st.get("label", "?"), badge=st.get("status", ""))
        for i, st in enumerate(subtasks)
        if isinstance(st, dict)
    ]
    meta = {k: item[k] for k in ("status", "priority", "started", "branch")
            if item.get(k)}
    if item.get("tags"):
        meta["tags"] = item["tags"]
    return node(
        "focus-" + slugify(item.get("label", "?")),
        item.get("label", "(untitled)"),
        icon=sec_icon,
        badge=status,
        summary=first_line(item.get("text", "")),
        body=item.get("text", ""),
        meta=meta or None,
        children=kids,
    )


def build_focus() -> dict:
    layer = node("chaba-focus", "Chaba Focus", icon="mdi:target")
    total = 0
    for path in (FOCUS_ACTIVE, FOCUS_BACKLOG):
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            continue
        for sec in doc.get("sections") or []:
            items = [i for i in (sec.get("items") or []) if isinstance(i, dict)]
            if not items:
                continue
            title = sec.get("title", "Section")
            kids = [focus_item_node(i, ICON_MAP.get(title, "mdi:target"))
                    for i in items]
            layer["children"].append(node(
                "sec-" + slugify(title), title,
                icon=ICON_MAP.get(title, "mdi:target"),
                badge=str(len(items)),
                summary=f"{len(items)} item(s)",
                children=kids))
            total += len(items)

    if FOCUS_INBOX.is_dir():
        inbox_kids = []
        for p in sorted(FOCUS_INBOX.glob("*.yml")):
            if p.name.startswith("TEMPLATE"):
                continue
            doc = load_yaml(p)
            if not isinstance(doc, dict):
                continue
            f = doc.get("focus") or {}
            if not f.get("label"):
                continue
            inbox_kids.append(node(
                "inbox-" + p.stem, f["label"],
                icon="mdi:inbox-outline",
                badge=f.get("status", "draft"),
                summary=first_line(f.get("text", "")),
                body=f.get("text", ""),
                meta={k: f[k] for k in ("priority", "branch") if f.get(k)} or None))
        if inbox_kids:
            layer["children"].append(node(
                "sec-inbox", "Inbox (untriaged)",
                icon="mdi:inbox-outline", badge=str(len(inbox_kids)),
                summary=f"{len(inbox_kids)} unprocessed",
                children=inbox_kids))
            total += len(inbox_kids)

    layer["badge"] = str(total)
    layer["summary"] = (f"{total} tracked item(s) across "
                        f"{len(layer['children'])} group(s)")
    return layer


# ---------- L1: ada pipeline ----------

def build_ada() -> dict:
    layer = node("ada", "Ada Pipeline", icon="mdi:microphone-outline")

    # focus threads
    threads, dormant = [], []
    for b in md_blocks(ADA_REVIEW / "focus-digest.md"):
        h = b["heading"]
        if h.startswith(("ops", "hosts")):
            continue
        if h == "dormant":
            dormant.append(b)
            continue
        tag = h.split(":", 1)[-1].strip() if h.startswith("focus:") else h
        stats = b["body"].split("\n", 1)[0] if b["body"] else ""
        threads.append(node("ada-focus-" + slugify(tag), tag,
                            icon="mdi:tag-outline",
                            summary=stats, body=b["body"]))
    if threads or dormant:
        kids = list(threads)
        if dormant:
            kids.append(node("ada-dormant", "Dormant threads",
                             icon="mdi:sleep",
                             badge=str(len(dormant[0]["body"].splitlines())),
                             body=dormant[0]["body"]))
        layer["children"].append(node(
            "ada-focus-threads", "Focus threads",
            icon="mdi:tag-multiple-outline", badge=str(len(threads)),
            summary=f"{len(threads)} active thread(s)"
                    + (f", {len(dormant[0]['body'].splitlines())} dormant"
                       if dormant else ""),
            children=kids))

    # session ops
    rows = []
    ops_file = ADA_REVIEW / "session-ops.jsonl"
    if ops_file.exists():
        for ln in ops_file.read_text().splitlines():
            if ln.strip():
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    pass
    if rows:
        tc = sum(r.get("tool_calls", 0) for r in rows)
        te = sum(r.get("tool_errors", 0) for r in rows)
        kids = [
            node(
                "ops-" + r.get("session", "?"), r.get("session", "?"),
                icon="mdi:chart-line",
                badge=f"{r.get('tool_errors', 0)} err"
                      if r.get("tool_errors") else "ok",
                summary=(f"{r.get('tool_calls', 0)} calls, "
                         f"{r.get('responses', 0)} responses, "
                         f"{r.get('unit', '')}"),
                body=json.dumps(r, indent=1, ensure_ascii=False))
            for r in rows[-15:]
        ]
        layer["children"].append(node(
            "ada-ops", "Session operations",
            icon="mdi:cog-outline", badge=f"{te} err" if te else "ok",
            summary=(f"{len(rows)} session(s), {tc} tool calls, "
                     f"{te} errors"),
            children=kids))

    # hosts
    hosts = []
    host_file = ADA_REVIEW / "host-ops.jsonl"
    if host_file.exists():
        for ln in host_file.read_text().splitlines():
            if not ln.strip():
                continue
            try:
                hosts.append(json.loads(ln))
            except ValueError:
                pass
    if hosts:
        kids, flags = [], 0
        for r in hosts:
            bad = bool(r.get("oom_kills") or r.get("failed_units")
                       or r.get("unit_failures"))
            flags += bad
            kids.append(node(
                "host-" + r.get("host", "?"), r.get("host", "?"),
                icon="mdi:server",
                badge="issues" if bad else "ok",
                summary=(f"restarts {r.get('restart_total', 0)}, "
                         f"err {r.get('error_lines', 0)}, "
                         f"disk {r.get('disk_use') or '?'}"),
                body=json.dumps(r, indent=1, ensure_ascii=False)))
        layer["children"].append(node(
            "ada-hosts", "Host health",
            icon="mdi:server-network",
            badge=f"{flags} flagged" if flags else "ok",
            summary=f"{len(kids)} host(s) swept",
            children=kids))

    # ops events — tool storms, actuation caps, confirm strips, blocked
    # writes. Emitted by ada-pi into the ada-ha-events MDDB collection;
    # read back here so containment shows on the Report tab. Optional:
    # any failure just omits the section.
    ops = _mddb_ops_events()
    if ops:
        kids = []
        flagged = 0
        for d in ops:
            meta = d.get("meta") or {}
            ev_type = (meta.get("type") or ["?"])[0]
            ts = (meta.get("ts") or [""])[0][:16].replace("T", " ")
            tool = (meta.get("tool") or [""])[0]
            sev = ev_type in ("tool_storm", "actuation_cap", "confirm_strip")
            flagged += sev
            kids.append(node(
                "opsev-" + slugify(ts + ev_type), f"{ts} — {ev_type}",
                icon="mdi:shield-alert-outline",
                badge=ev_type,
                summary=(f"{tool}: " if tool else "")
                        + first_line(d.get("contentMd", "")),
                body=d.get("contentMd", ""),
                meta={"type": ev_type, "tool": tool} if tool
                     else {"type": ev_type}))
        layer["children"].append(node(
            "ada-ops-events", "Ops events",
            icon="mdi:shield-outline",
            badge=f"{flagged} flagged" if flagged else str(len(kids)),
            summary=f"{len(kids)} containment event(s) in 24h",
            children=kids))

    # recent session summaries
    smem = md_blocks(ADA_REVIEW / "session-memory.md", min_chars=60)
    if smem:
        kids = [node("sess-" + slugify(b["heading"], 50), b["heading"],
                     icon="mdi:text-box-outline",
                     summary=first_line(b["body"]), body=b["body"])
                for b in smem[-10:]]
        layer["children"].append(node(
            "ada-sessions", "Recent sessions",
            icon="mdi:history", badge=str(len(kids)),
            summary=f"last {len(kids)} session summaries",
            children=kids))

    layer["badge"] = str(len(layer["children"]))
    layer["summary"] = ("; ".join(c["summary"] for c in layer["children"])
                        or "no ada-review data")
    return layer


MDDB_URL = os.environ.get("MDDB_BASE_URL",
                          "http://100.74.146.0:11023/v1").rstrip("/")
OPS_COLLECTION = os.environ.get("ADA_OPS_COLLECTION",
                                "ada-ha-events-tony")
OPS_WINDOW_H = 24
JOBS_COLLECTION = os.environ.get("DISPATCH_JOBS_COLLECTION",
                                 "ada-ha-bank-devin-handoff")
LEDGER_DIR = REPO / "reports/dispatch"


# ---------- L1: dispatch (job ledger) ----------

def _mddb_jobs() -> list[dict]:
    """job/<id> + answer/<id> docs from the devin-handoff collection —
    the shared ledger written by devin-dispatch(-watch) and job-run.sh.
    Fails soft to [] so the feed renders offline."""
    try:
        payload = json.dumps({
            "collection": JOBS_COLLECTION,
            "filterMeta": {"kind": ["job"]},
            "limit": 100,
        }).encode()
        req = urllib.request.Request(
            f"{MDDB_URL}/search", data=payload,
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            docs = json.loads(resp.read())
    except Exception:
        return []
    return docs if isinstance(docs, list) else []


def _ledger_entries() -> dict[str, dict]:
    """reports/dispatch/*.jsonl — console-session dispatches. Latest line
    per job id wins."""
    out: dict[str, dict] = {}
    if not LEDGER_DIR.is_dir():
        return out
    for p in sorted(LEDGER_DIR.glob("*.jsonl")):
        try:
            for ln in p.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                if e.get("id"):
                    out[e["id"]] = e
        except OSError:
            continue
    return out


def build_dispatch() -> dict | None:
    layer = node("dispatch", "Dispatch", icon="mdi:rocket-launch-outline")
    jobs = _mddb_jobs()
    jobs.sort(key=lambda d: ((d.get("meta") or {}).get("ts") or [""])[0],
              reverse=True)
    awaiting = []
    for d in jobs[:25]:
        meta = d.get("meta") or {}
        jid = ((meta.get("job_id") or [""])[0]
               or (d.get("key") or "").split("/", 1)[-1])
        st = ((meta.get("status") or ["?"])[0])
        q = ((meta.get("question") or [""])[0])
        ts = ((meta.get("ts") or [""])[0])[:16].replace("T", " ")
        src = ((meta.get("source") or [""])[0])
        if st == "awaiting-user":
            awaiting.append(jid)
        layer["children"].append(node(
            "job-" + slugify(jid), f"{jid}",
            icon="mdi:rocket-launch-outline",
            badge=st,
            summary=(f"{ts} {src} — {q}" if q else
                     f"{ts} {src} — " + first_line(d.get("contentMd", ""))),
            body=d.get("contentMd", ""),
            meta={k: v for k, v in {
                "status": st, "host": (meta.get("host") or [""])[0],
                "question": q, "job_id": jid}.items() if v}))
    for e in sorted(_ledger_entries().values(),
                    key=lambda e: e.get("dispatched_at", ""),
                    reverse=True)[:15]:
        lid = e.get("id", "?")
        if any(f"job/{lid}" == (d.get("key") or "")
               or ((d.get("meta") or {}).get("job_id") or [""])[0] == lid
               for d in jobs):
            continue  # already represented by its MDDB doc
        layer["children"].append(node(
            "led-" + slugify(lid), lid,
            icon="mdi:clipboard-list-outline",
            badge=e.get("status", "?"),
            summary=first_line(e.get("task") or e.get("desc") or ""),
            body=json.dumps(e, indent=1, ensure_ascii=False)))
    if not layer["children"]:
        return None
    layer["badge"] = (f"{len(awaiting)} need you" if awaiting
                      else str(len(layer["children"])))
    layer["summary"] = (
        (f"awaiting answer: {', '.join(awaiting[:5])}. " if awaiting else "")
        + f"{len(layer['children'])} job(s)")
    return layer


def build_feed() -> dict:
    layers = [build_events(), build_dispatch(), build_focus(), build_ada()]
    layers = [l for l in layers if l is not None]
    return {
        "generated_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "title": "Chaba system report",
        "summary": " — ".join(f"{l['title']}: {l['badge']}" for l in layers),
        "layers": layers,
    }


def _mddb_ops_events() -> list[dict]:
    """Recent ops/containment events emitted by ada-pi (kind=ops-event).
    Network read with a hard timeout — failure returns [] so the feed
    still renders offline."""
    try:
        payload = json.dumps({
            "collection": OPS_COLLECTION,
            "filterMeta": {"kind": ["ops-event"]},
            "limit": 50,
        }).encode()
        req = urllib.request.Request(
            f"{MDDB_URL}/search", data=payload,
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            docs = json.loads(resp.read())
    except Exception:
        return []
    if not isinstance(docs, list):
        return []
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=OPS_WINDOW_H))
    out = []
    for d in docs:
        ts = ((d.get("meta") or {}).get("ts") or [""])[0]
        try:
            dt = datetime.datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            if dt < cutoff:
                continue
        except ValueError:
            pass
        out.append(d)
    out.sort(key=lambda d: ((d.get("meta") or {}).get("ts") or [""])[0],
             reverse=True)
    return out[:20]


# ---------- L1: events ----------

def build_events() -> dict:
    layer = node("events", "Recent Events", icon="mdi:bell-outline")
    kids = []

    ev = load_yaml(CHABA_DATA / "recent-events.yml") or {}
    for e in (ev.get("entries") or [])[:15]:
        if isinstance(e, dict) and e.get("text"):
            ts = str(e.get("ts", ""))[:16]
            body = e["text"] + (f"\n→ {e['ref']}" if e.get("ref") else "")
            kids.append(node("ev-" + slugify(ts), ts,
                             icon="mdi:lightning-bolt",
                             summary=first_line(e["text"]), body=body))

    for b in md_blocks(ADA_REVIEW / "events.md")[-10:]:
        kids.append(node("aev-" + slugify(b["heading"], 50), b["heading"],
                         icon="mdi:microphone-outline",
                         summary=first_line(b["body"]), body=b["body"]))

    layer["children"] = kids
    layer["badge"] = str(len(kids))
    layer["summary"] = f"{len(kids)} recent event(s)"
    return layer


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", type=Path,
                    default=Path("/tmp/chaba-report.json"))
    ap.add_argument("--host",
                    help="scp the feed to <host>:" + REMOTE_WWW)
    args = ap.parse_args()

    feed = build_feed()
    text = json.dumps(feed, indent=1, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"rendered -> {args.output} "
          f"({len(feed['layers'])} layers, {len(text)} bytes)")

    if args.host:
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as f:
            f.write(text)
            tmp = f.name
        subprocess.run(["scp", "-q", tmp,
                        f"{args.host}:{REMOTE_WWW}"], check=True)
        Path(tmp).unlink()
        print(f"deployed -> {args.host}:{REMOTE_WWW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
