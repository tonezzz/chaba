#!/usr/bin/env python3
"""Incremental overnight Kanban dispatch wave.

Gated top-up: runs every 15 min from a user timer, queues at most WAVE_SIZE
new cards only when the queue is shallow and every health gate is clear.
Never re-dispatches a card it has already sent (durable JSON ledger + board
comms). Persistence goes through kanban-commit.sh, never a raw git push.
"""
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "http://127.0.0.1:8787"
REPO = Path("/home/tony/CascadeProjects/chaba-tony-dell")
STATE = Path.home() / ".local" / "state" / "auto-dispatch"
LEDGER = STATE / "ledger.json"
LOG = STATE / "waves.log"
STOP = STATE / "STOP"
LOCK = Path("/tmp/auto-dispatch.lock")

WAVE_SIZE = 10
QUEUED_TRIGGER = 15          # only top up when queue is this shallow
MAX_INFLIGHT = 50            # queued + claimed ceiling
VERIFY_REVIEW_MAX = 10       # review triage is the bottleneck
HEARTBEAT_MAX_S = 900
MIN_HEALTHY_HOSTS = 3       # a sleeping Mac must not block the whole fleet
COOLDOWN_MIN = 14
ALERT_CARD = "ops-kanban-commit-guard"

# Cards dispatched by the three manual batches tonight, plus gated ones.
SEED = set("""
adobe-stock-inpaint-defect-repair audit-miss-cms-page-devin-session-audit-2026-10-17
consultant-fixture-grow-20-cases fix-devin-desktop-startup-after-3-12-upgrade
kk-mac-live-memory-guard litellm-key-bench-dead-shadows-chaba
mddb-cms-embed-quota-write-timeout-stall mddb-leader-bge-m3-migration-11023
runner-per-executor-caps idc03-disk-cleanup-20261124 ada-wiki-extension-confirm-flag
ada-capabilities-verb-wiring ada-capability-verb-wiring ada-ha-dashboard-live-view-drift
ada-opencode-repair-menu-card ada-opencode-v2-upgrade ada-scenario-quadlets-exit-contract
ada-scenario-smoke-timeout-truncation ada-smoke-regressions-20261107
ada-sweep-menu-regression-20261108 board-diagram-lanes-view
ada-voice-host-status-drop-19-pr adobe-stock-illustration-pivot-test ada-voice-fleet-jobs-verb
ada-lanes-run-on-deleted-ada-pi-venv-res-df9c81 ada-ocb-skills-edu-postmerge-recheck
app-retirement-sweep apps-yml-host-url-still-tony-dell-x42 audit-auto-macbook
audit-miss-ada-voice-job-records audit-miss-remote-eval-results-not-landed
audit-miss-uncommitted-worktree-job-artifacts audit-oc-artifact-not-durable-qgxpgcc5
audit-oc-denied-tool-muijr5b4 audit-oc-mutating-command-0b3n5bce
audit-oc-mutating-command-1bbtyha8 audit-oc-mutating-command-aahmnvt5
auto-route-bounded-card-classes-to-execu-257c7a bge-production-serving-architecture-rera-e6ba35
board-cli-request-ask-field board-gantt-timeline-view board-tests-control-pane-lane-failures
board-weight-cards-json-still-6-2mb-at-7-894827 boards-502-residuals-dns-h3-access
ada-voice-map-embed-pr22-merge-deploy answer-sweep-auto-compose-spec
audit-miss-unlanded-oct06-dispatch-artifacts board-api-date-serialization-outage
ops-1025-remote-read-smoke-idc03 camwall-retire-to-wiki cf-ssl-strict-migrate-idc02-edge-origin-3fa959
cms-auto-health-stop-carding-powered-off-e11c7a cms-plane-bge-golden-set-eval-measure-re-cad4f4
command-polish-before-ai-dispatch consultant-brain-confirmation-bench devin-usage-reduction
devnest-upstream-skills-review dispatch-worktree-merged-triage done-card-runner-defer-spam
""".split())


def now_str():
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


def log(msg):
    STATE.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"{now_str()} {msg}\n")


def get(path):
    for a in range(8):
        try:
            with urllib.request.urlopen(API + path, timeout=60) as r:
                return json.load(r)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            if a == 7:
                raise
            time.sleep(2 + a)


def post(path, body):
    data = json.dumps(body).encode()
    for a in range(12):
        req = urllib.request.Request(API + path, data=data,
              headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if 500 <= e.code < 600:
                try:
                    detail = json.loads(e.read())
                except Exception:
                    detail = {}
                wait = float(detail.get("retry_after_s") or 0) or (2 + a)
                if a < 11:
                    time.sleep(wait)
                    continue
            raise
        except urllib.error.URLError:
            if a == 11:
                raise
            time.sleep(3 + a)


def load_ledger():
    if LEDGER.exists():
        try:
            d = json.loads(LEDGER.read_text())
            d.setdefault("dispatched", {})
            d.setdefault("known_failures", ["ops-1025-remote-read-smoke-idc03"])
            return d
        except Exception:
            pass
    return {"dispatched": {cid: {"wave": 0, "at": "seed"} for cid in sorted(SEED)},
            "known_failures": ["ops-1025-remote-read-smoke-idc03"],
            "last_wave": None, "wave": 0, "skips": 0, "last_skip": None, "alerted": None}


def save_ledger(d):
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, sort_keys=True))
    os.replace(tmp, LEDGER)


def skip(d, reason, alertable=True, alert_key=None):
    log("SKIP: " + reason)
    if not alertable:
        # Full queue / in-flight ceiling is normal backpressure, not a fault.
        return 0
    key = alert_key or reason
    d["skips"] = d.get("skips", 0) + 1
    d["last_skip"] = reason
    save_ledger(d)
    # One alert per distinct fault until a wave succeeds — benign skips must
    # never clear the dedupe key (that caused 10 duplicate alerts overnight).
    if d["skips"] >= 3 and d.get("alerted") != key:
        try:
            post("/comment", {"id": ALERT_CARD, "from": "chaba",
                  "text": f"[auto-dispatch] paused after 3 consecutive waves: {reason}"})
            d["alerted"] = key
            save_ledger(d)
            log("alert posted on " + ALERT_CARD)
        except Exception as e:
            log(f"alert failed: {e}")
    return 0


def git_ok():
    try:
        p = subprocess.run(["git", "-C", str(REPO), "cat-file", "-t", "HEAD"],
                           capture_output=True, text=True, timeout=30)
        return p.returncode == 0 and p.stdout.strip() == "commit"
    except Exception:
        return False


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    if STOP.exists():
        log("STOP file present — paused by operator")
        return 0
    try:
        flock = LOCK.open("w")
        fcntl.flock(flock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another wave running — exiting")
        return 0

    d = load_ledger()
    last = d.get("last_wave")
    if last:
        try:
            t = datetime.fromisoformat(last)
            if datetime.now(timezone.utc) - t < timedelta(minutes=COOLDOWN_MIN):
                return 0
        except Exception:
            pass

    # Gate 1: queue depth and in-flight ceiling.
    try:
        q = get("/queue")
        counts = q.get("counts") or {}
        queued, claimed = counts.get("queued", 0), counts.get("claimed", 0)
    except Exception as e:
        return skip(d, f"queue API unavailable: {e}")
    if queued > QUEUED_TRIGGER:
        return skip(d, f"queue depth {queued} > {QUEUED_TRIGGER}", alertable=False)
    if queued + claimed > MAX_INFLIGHT:
        return skip(d, f"in flight {queued + claimed} > {MAX_INFLIGHT}", alertable=False)
    hosts = q.get("hosts") or {}
    stale = [h for h, v in hosts.items()
             if isinstance(v, dict) and (v.get("stale") or v.get("age_s", 0) > HEARTBEAT_MAX_S)]
    healthy = len(hosts) - len(stale)
    if healthy < MIN_HEALTHY_HOSTS:
        return skip(d, f"only {healthy} healthy hosts; stale: {', '.join(stale)}",
                    alert_key="stale-hosts")

    # Gate 2: card-level health and review backlog.
    try:
        cs = get("/cards?limit=5000&fields=id,column,action_status,updated,priority,ref,"
                 "awaiting_action,spec,brief,action,review_kind")["cards"]
    except Exception as e:
        return skip(d, f"cards API unavailable: {e}")
    known = set(d.get("known_failures") or [])
    failed = [c["id"] for c in cs if c.get("action_status") == "failed" and c["id"] not in known]
    if failed:
        return skip(d, "new failed cards: " + ", ".join(failed[:5]), alert_key="new-failures")
    verify = [c for c in cs if c.get("column") == "review" and c.get("review_kind") == "verify"]
    if len(verify) >= VERIFY_REVIEW_MAX:
        return skip(d, f"verify review backlog {len(verify)} >= {VERIFY_REVIEW_MAX}")
    if not git_ok():
        return skip(d, "served checkout HEAD object missing")

    # Selection: priority desc, oldest first, everything dispatchable excluded.
    dispatched = set(d["dispatched"])
    cand = []
    for c in cs:
        cid = c.get("id") or ""
        if c.get("column") != "backlog" or c.get("action_status") not in (None, "idle"):
            continue
        if cid.startswith("timer-alert-") or cid in dispatched or c.get("awaiting_action"):
            continue
        if not (c.get("spec") or c.get("brief")):
            continue
        act = c.get("action") or {}
        if act.get("type") == "manual" or act.get("lane") == "manual":
            continue
        if act.get("executor") == "manual":
            continue
        cand.append(c)
    pv = {"high": 3, "medium": 2, "low": 1, None: 0}
    cand.sort(key=lambda c: (-pv.get(c.get("priority"), 0), c.get("updated") or ""))

    wave = d.get("wave", 0) + 1
    sent = []
    for c in cand:
        if len(sent) >= WAVE_SIZE:
            break
        cid = c["id"]
        try:
            r = post("/action", {"id": cid, "do": "queue", "from": "chaba"})
            msg = r.get("message") or ""
        except Exception as e:
            log(f"queue POST failed for {cid}: {e}")
            continue
        if "queued" in msg and "not queued" not in msg:
            sent.append(cid)
            d["dispatched"][cid] = {"wave": wave, "at": now_str()}
            time.sleep(0.6)
        else:
            d["dispatched"][cid] = {"wave": wave, "at": "gated: " + msg[:80]}

    if not sent:
        save_ledger(d)
        return skip(d, "no dispatchable cards accepted this wave")

    for cid in sent:
        try:
            post("/comment", {"id": cid, "from": "chaba",
                  "text": f"[auto-dispatch] wave {wave} ({now_str()}): queued by the "
                          "overnight incremental dispatcher; all gates clear."})
        except Exception as e:
            log(f"comm failed for {cid}: {e}")

    d["wave"] = wave
    d["last_wave"] = datetime.now(timezone.utc).isoformat()
    d["skips"] = 0
    d["alerted"] = None
    save_ledger(d)
    log(f"wave {wave}: queued {len(sent)}: " + ", ".join(sent))

    try:
        p = subprocess.run(["bash", str(REPO / "scripts/board/kanban-commit.sh")],
                           capture_output=True, text=True, timeout=300, cwd=str(REPO))
        log(f"kanban-commit rc={p.returncode}: {(p.stdout + p.stderr)[-300:]}")
    except Exception as e:
        log(f"kanban-commit failed: {e}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("FATAL: " + repr(e))
        sys.exit(1)
