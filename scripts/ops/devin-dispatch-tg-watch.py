#!/usr/bin/env python3
"""devin-dispatch-tg-watch — TG notify on Devin dispatch ledger events.

Reads the shared dispatch job ledger — job/<id> and answer/<id> docs in
the MDDB ada-ha-bank-devin-handoff collection, written by
devin-dispatch / devin-dispatch-watch / job-run on every runner host —
and pushes one TG message per new job state (started / done / FAILED /
needs input / answered) through board_notify's tg channel (ada-ha
group — same wiring as nest-queue-watch and kanban-notify).

Why a poller instead of a hook inside devin-dispatch-watch: the TG
relay /send is loopback on idc03 (:8911), so only an idc03-side reader
can reach it; the MDDB ledger is the one channel every host already
writes, so one watcher covers the whole fleet.

Intended as a dispatcher job (every: 5m) on idc03 — home of both the
MDDB leader and the relay.

Kill switch: touch ~/.config/devin-dispatch-tg-watch.off — every tick
exits silently while it exists; rm to resume. Or
DEVIN_DISPATCH_TG_WATCH=off in the job env.

First tick primes silently (records current ledger state, sends
nothing) so install doesn't replay history; set
DEVIN_TG_WATCH_CATCHUP_MIN=<n> to also notify docs touched in the last
n minutes on that first tick.

Env:
  DEVIN_DISPATCH_TG_WATCH    off disables (default on)
  DEVIN_TG_WATCH_STATE       state file, default
                             ~/.local/state/devin-dispatch-tg-watch.json
  DEVIN_TG_WATCH_OFF_FILE    kill-switch path, default
                             ~/.config/devin-dispatch-tg-watch.off
  DEVIN_TG_WATCH_MDDB        MDDB base (default $MDDB_URL /
                             $MDDB_BASE_URL /
                             http://100.102.134.91:11023/v1 — idc03 leader)
  DEVIN_TG_WATCH_COLLECTION  ledger collection (default
                             ada-ha-bank-devin-handoff)
  DEVIN_TG_WATCH_CATCHUP_MIN first-tick catch-up window in minutes
                             (default 0 = prime silently)
  DEVIN_TG_WATCH_STATUSES    comma list of job statuses to report
                             (default all: running,done,failed,
                             awaiting-user,...)
  BOARD_NOTIFY_CHANNEL       board_notify channel (job sets tg)
  BOARD_NOTIFY_TG_CHAT_ID    ada-ha group when set (else Tony DM)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
STATE = Path(os.environ.get(
    "DEVIN_TG_WATCH_STATE",
    HOME / ".local/state/devin-dispatch-tg-watch.json"))
OFF_FILE = Path(os.environ.get(
    "DEVIN_TG_WATCH_OFF_FILE",
    HOME / ".config/devin-dispatch-tg-watch.off"))
MDDB = (os.environ.get("DEVIN_TG_WATCH_MDDB")
        or os.environ.get("MDDB_URL")
        or os.environ.get("MDDB_BASE_URL")
        or "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = os.environ.get(
    "DEVIN_TG_WATCH_COLLECTION", "ada-ha-bank-devin-handoff")
CATCHUP_MIN = float(os.environ.get("DEVIN_TG_WATCH_CATCHUP_MIN", "0"))
STATUS_FILTER = {s.strip() for s in os.environ.get(
    "DEVIN_TG_WATCH_STATUSES", "").split(",") if s.strip()}
MAX_PER_TICK = 5    # don't burst-notify a dispatch backlog
MAX_STATE = 5000    # bound the seen-signature map
PAGE = 1000         # /search caps a page at 1000; ledger is ~1.5k and
                    # unordered, so a single page can silently miss
                    # recent docs — paginate like lib/cms_index.list_docs
MAX_PAGES = 10      # ~10k ledger docs is years of runway

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "board"))
import board_notify  # noqa: E402

LABELS = {
    "running": "started",
    "done": "done",
    "failed": "FAILED",
    "awaiting-user": "needs input",
}


def _meta1(meta: dict, name: str) -> str:
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v) if v is not None else ""


def mddb_job_docs() -> list[dict] | None:
    """job/* + answer/* ledger docs; None on fetch failure (state stays
    untouched so the next tick retries the same diff)."""
    docs: list[dict] = []
    for page in range(MAX_PAGES):
        payload = json.dumps({
            "collection": COLLECTION,
            "filterMeta": {"kind": ["job", "answer"]},
            "limit": PAGE, "offset": page * PAGE,
        }).encode()
        req = urllib.request.Request(
            f"{MDDB}/search", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                batch = json.loads(r.read())
        except Exception as e:
            print(f"devin-dispatch-tg-watch: mddb search failed: {e}",
                  file=sys.stderr)
            return None
        if isinstance(batch, dict):
            batch = batch.get("documents") or batch.get("docs") or []
        if not isinstance(batch, list):
            batch = []
        docs += batch
        if len(batch) < PAGE:
            break
    return docs


def _parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone() if dt.tzinfo else dt.replace(
        tzinfo=timezone.utc)


def _sig(key: str, status: str, content: str) -> str:
    """Content signature — a watch retry that rewrites an identical doc
    produces the same sig and stays silent; a follow-up completion with
    a new outcome text produces a new sig and re-reports."""
    return hashlib.sha1(
        f"{key}\n{status}\n{content}".encode()).hexdigest()[:16]


def _summary_text(content: str) -> str:
    """contentMd minus the 'Job <id> on <host>: <st>.' header line and
    the 'Needs input:' line (carried in meta.question) — one-line
    excerpt for the TG body."""
    lines = [l for l in (content or "").splitlines() if l.strip()]
    if lines and lines[0].startswith("Job "):
        lines = lines[1:]
    lines = [l for l in lines
             if not l.strip().startswith("Needs input:")]
    return " ".join(" ".join(lines).split())[:220]


def events_from_docs(docs: list[dict]) -> list[dict]:
    """Ledger docs -> candidate notify events, oldest first."""
    out = []
    for d in docs:
        key = d.get("key") or ""
        if key.startswith("job/"):
            kind = "job"
        elif key.startswith("answer/"):
            kind = "answer"
        else:
            continue
        meta = d.get("meta") or {}
        content = d.get("contentMd") or ""
        status = _meta1(meta, "status") or ("answered" if kind == "answer"
                                           else "?")
        if STATUS_FILTER and kind == "job" and status not in STATUS_FILTER:
            continue
        jid = (_meta1(meta, "job_id") or key.split("/", 1)[-1])
        ts = _parse_ts(_meta1(meta, "ts"))
        out.append({
            "key": key, "kind": kind, "jid": jid, "status": status,
            "host": _meta1(meta, "host"),
            "question": _meta1(meta, "question"),
            "excerpt": _summary_text(content),
            "sig": _sig(key, status, content),
            "ts": ts or datetime.fromtimestamp(0, timezone.utc),
        })
    out.sort(key=lambda e: e["ts"])
    return out


def fmt_event(e: dict) -> tuple[str, str]:
    """-> (title, body) for board_notify.send."""
    jid = e["jid"]
    if e["kind"] == "answer":
        title = f"[devin] {jid} answered"
        body = e["excerpt"] or "answer recorded on the job ledger"
        return title, body
    label = LABELS.get(e["status"], e["status"] or "updated")
    if label == "?":
        label = "updated"
    title = f"[devin] {jid} {label}"
    if e["status"] == "awaiting-user":
        body = e["question"] or e["excerpt"] or "needs input"
    else:
        bits = [b for b in (e["host"], e["excerpt"]) if b]
        body = " — ".join(bits)
    return title, body


def load_state() -> dict:
    try:
        st = json.loads(STATE.read_text())
        if isinstance(st.get("jobs"), dict):
            return st
    except Exception:
        pass
    return {"primed": False, "jobs": {}}


def save_state(st: dict) -> None:
    try:
        jobs = st.get("jobs") or {}
        if len(jobs) > MAX_STATE:
            # keep the newest MAX_STATE by ledger ts
            items = sorted(
                jobs.items(),
                key=lambda kv: (kv[1] or {}).get("ts", ""))
            st["jobs"] = dict(items[-MAX_STATE:])
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_name(STATE.name + ".tmp")
        with tmp.open("w") as f:
            f.write(json.dumps(st))
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(STATE)
    except OSError as e:
        print(f"devin-dispatch-tg-watch: state write failed: {e}",
              file=sys.stderr)


def main() -> int:
    if os.environ.get("DEVIN_DISPATCH_TG_WATCH") == "off" \
            or OFF_FILE.exists():
        return 0
    docs = mddb_job_docs()
    if docs is None:
        return 0
    events = events_from_docs(docs)
    st = load_state()
    seen = st["jobs"]

    def unseen(e: dict) -> bool:
        return seen.get(e["key"], {}).get("sig") != e["sig"]

    if not st.get("primed"):
        # First tick: record the ledger position silently so install
        # doesn't replay history. CATCHUP_MIN re-admits docs touched in
        # the window so a fresh install can be verified live.
        st["primed"] = True
        cutoff = (datetime.now(timezone.utc).timestamp()
                  - CATCHUP_MIN * 60)
        fresh = []
        for e in events:
            if CATCHUP_MIN > 0 and unseen(e) \
                    and e["ts"].timestamp() >= cutoff:
                fresh.append(e)
            else:
                seen[e["key"]] = {"sig": e["sig"],
                                  "ts": e["ts"].isoformat()}
    else:
        fresh = [e for e in events if unseen(e)]

    sent = 0
    for e in fresh[:MAX_PER_TICK]:
        title, body = fmt_event(e)
        if not board_notify.send(title, body, url=""):
            print(f"devin-dispatch-tg-watch: notify failed for "
                  f"{e['key']} — retained for retry", file=sys.stderr)
            break
        seen[e["key"]] = {"sig": e["sig"], "ts": e["ts"].isoformat()}
        sent += 1
    save_state(st)
    if sent:
        print(f"sent: {sent} dispatch event(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
