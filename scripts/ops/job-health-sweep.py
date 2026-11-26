#!/usr/bin/env python3
"""job-health-sweep — declared-job failure sweep -> board-api card.

card job-health-sweep-consecutive-failure-alerts (OPS-1015, 2026-11-26):
three con01 jobs sat dead for up to a month — missing node_modules, a
disabled timer, a spend-capped API key — and no dashboard watched any of
them. The alerting gap is systemic: any declared job on any host can die
silently. This is the job-level complement to runner-fleet-health (which
covers host-level silence — a dead sweep can't report itself).

Runs per-host from the rendered systemd user timer job-health-sweep.timer
(declared in ssot.jobs.yml for the jobs hosts). Each tick:

  1. enumerates this host's jobs — ssot.jobs.yml host: match,
     dispatch: systemd, enabled != false — plus a drift pass over
     ~/.config/systemd/user/*.service for rendered 'job:<id>'
     Description tags whose id is NOT declared here (stale units
     surviving a host move — the duplicate-unit pitfall);
  2. per declared job checks the installed <id>.service/.timer pair:
     missing unit files, timer disabled/masked, timer inactive (the
     never-fires case), then counts consecutive failed activations in
     the user journal since the last Finished/Deactivated-success;
  3. alerts through board-api: one auto card job-auto-health-<host>
     (review/triage), comments on state change only — new failure,
     still-failing daily summary, recovered — auto-close when green.

Thresholds (card spec): >=3 consecutive failed activations, or >=1
attempt with zero successes inside the journal window. Journal
retention can be <30d on small hosts — counting simply covers whatever
the journal retains (degrades to failed-since-boot; the report notes
coverage). OPS-0581 exit contract: findings ride the board, so exit 0
when the sweep completes; exit 1 only when the sweep itself cannot run
(manifest unreadable, user systemd unreachable) — that failure is the
unit's own journal signal for the next tick.

Env: BOARD_API / RUNNER_API override the board-api base URL,
     JOB_SWEEP_STATE, JOB_SWEEP_WINDOW (default '30 days ago'),
     JOB_SWEEP_NO_ALERT=1 (evaluate + print, no board writes).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - all jobs hosts ship PyYAML
    sys.stderr.write("job-health-sweep: PyYAML required (ssot.jobs.yml)\n")
    sys.exit(2)

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "docs" / "ssot" / "infrastructure" / "ssot.jobs.yml"
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
STATE = Path(os.environ.get(
    "JOB_SWEEP_STATE",
    str(Path.home() / ".local/state/job-health-sweep.json"))).expanduser()
BOARD_API = (os.environ.get("BOARD_API") or os.environ.get("RUNNER_API")
             or "https://idc03.taila0626a.ts.net:10000").rstrip("/")
WINDOW = os.environ.get("JOB_SWEEP_WINDOW", "30 days ago")

CONSEC_MIN = 3
# Some watch jobs (retry-storm-watch, netdata-nodes-watch) deliberately
# exit 1 when they file an alert — that nonzero exit IS their alerting
# contract, not a broken activation. The newest activation ending in one
# of these stdout markers counts as a successful completion for health
# purposes; a failure without a marker still flags normally.
ALERT_EXIT_MARKERS = (
    "alert filed:", "alert muted", "recovered (silent)", "ok — checks=",
)
SUMMARY_EVERY_S = 20 * 3600      # still-failing digest cadence (~daily)
JOURNAL_TIMEOUT = 60
CTL_TIMEOUT = 15
MAX_ERROR_LEN = 160
MAX_COMMENT_JOBS = 6             # beyond this, batch new-failures into one

JOB_TAG_RE = re.compile(r"job:([A-Za-z0-9_-]+)")
DESC_TAG_RE = re.compile(r"^Description=[^\n]*?job:([^\s,\)]+)", re.M)
FWR_RE = re.compile(r"Failed with result '([^']+)'")
BOILER_RE = re.compile(
    r"^(Starting |Started |Finished |Failed to start |Deactivated|"
    r"Consumed |Scheduled |Stopped |Stopping |start operation|"
    r"Condition check|Job for|Listening on|"
    r"[A-Za-z0-9_.@-]+\.service:)")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def detect_host() -> str:
    return socket.gethostname().split(".")[0].replace("-", "_")


def load_jobs(manifest: Path, host: str) -> list[dict]:
    """Declared dispatch:systemd jobs for this host (renderer parity)."""
    man = yaml.safe_load(Path(manifest).read_text())
    jobs = []
    for j in (man or {}).get("jobs", []):
        if j.get("host") != host or j.get("dispatch") != "systemd":
            continue
        if not j.get("enabled", True):
            continue
        jobs.append({"id": str(j["id"]),
                     "name": str(j.get("name") or j["id"]),
                     "expected_alert_exit":
                         bool(j.get("expected_alert_exit", False))})
    return jobs


def sh(args: list[str], timeout: int = CTL_TIMEOUT) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout or "").strip()
    except Exception as e:
        return 127, f"{type(e).__name__}: {e}"


def systemctl_user(*args: str) -> tuple[int, str]:
    return sh(["systemctl", "--user", *args])


def user_manager_ok() -> tuple[bool, str]:
    # is-system-running exits nonzero on 'degraded' too — judge by the
    # state word, not the rc (degraded is normal: some unit is failed).
    _rc, out = systemctl_user("is-system-running")
    state = out.splitlines()[-1].strip() if out else ""
    return state in ("running", "degraded", "starting",
                     "initializing"), state or "no output"


def journal_events(unit: str, since: str) -> tuple[list, str]:
    """(events, err) — events are (ts_us, message) oldest->newest."""
    rc, out = sh(
        ["journalctl", "--user", "-u", unit, "--since", since,
         "-o", "json", "--no-pager", "-q"], timeout=JOURNAL_TIMEOUT)
    if rc != 0:
        return [], out[:200] or f"rc={rc}"
    events = []
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        ts = e.get("__REALTIME_TIMESTAMP")
        msg = e.get("MESSAGE") or ""
        if ts and msg.strip():
            events.append((int(ts), msg.rstrip("\n")))
    return events, ""


def _is_ok(msg: str, unit: str) -> bool:
    return (msg.startswith(f"Finished {unit}")
            or f"{unit}: Deactivated successfully" in msg
            or f"{unit}: Succeeded" in msg)


def _is_informative(msg: str) -> bool:
    s = msg.strip()
    return len(s) >= 4 and not BOILER_RE.match(s)


def alert_exit_ok(unit: str, events: list) -> bool:
    """Newest activation completed via the watcher's alert-exit contract.

    Scans only the tail after the latest Starting/Started marker, so an
    older alert cannot mask a newer crash. Callers gate this on the job's
    `expected_alert_exit` SSOT declaration.
    """
    last_start = -1
    for i, (_ts, msg) in enumerate(events):
        if msg.startswith(f"Starting {unit}") or \
                msg.startswith(f"Started {unit}"):
            last_start = i
    if last_start < 0:
        return False
    tail = [msg for _ts, msg in events[last_start + 1:]]
    return any(marker in line
               for line in tail
               for marker in ALERT_EXIT_MARKERS)


def analyze_unit(unit: str, events: list) -> dict:
    """Consecutive-failure streak + window totals from journal events.

    Streak walk is newest->oldest. Per-activation markers are single:
    'Failed to start <unit>' ends a failed activation, 'Finished <unit>'
    (or Deactivated-successfully/Succeeded) ends a good one — the pair
    '<unit>: Failed with result' always sits just OLDER than its
    'Failed to start', so a skip flag dedupes it. Job stdout lines are
    collected only inside the NEWEST failed activation for last_error.
    """
    consec = 0
    skip_fwr = False
    collecting = False
    error_done = False
    cands: list[str] = []
    reason = ""
    last_fail_ts = 0

    for ts, msg in reversed(events):
        if msg.startswith(f"Starting {unit}") or \
                msg.startswith(f"Started {unit}"):
            if consec:
                error_done = True      # left the newest failed activation
            continue
        if _is_ok(msg, unit):
            break
        if msg.startswith(f"Failed to start {unit}"):
            consec += 1
            collecting = True
            skip_fwr = True
            if not last_fail_ts:
                last_fail_ts = ts
            continue
        if f"{unit}: Failed with result" in msg:
            if skip_fwr:
                skip_fwr = False       # pairs with the Failed to start
            else:
                consec += 1            # orphan failure marker
                if not last_fail_ts:
                    last_fail_ts = ts
            m = FWR_RE.search(msg)
            if m and not reason:
                reason = m.group(1)
            continue
        if collecting and not error_done and _is_informative(msg):
            cands.append(msg)          # newest-first: first hit = latest

    fails = sum(1 for _, m in events
                if m.startswith(f"Failed to start {unit}"))
    finished = sum(1 for _, m in events
                   if m.startswith(f"Finished {unit}"))
    deact = sum(1 for _, m in events
                if f"{unit}: Deactivated successfully" in m
                or f"{unit}: Succeeded" in m)
    successes = finished or deact
    attempts = fails + successes

    last_error = ""
    for c in cands:                   # cands are newest-first
        if re.search(r"error|fail|exception|traceback|denied|timeout|"
                     r"refused|unreachable|missing|no such", c, re.I):
            last_error = c
            break
    if not last_error and cands:
        last_error = cands[0]
    if not last_error and reason:
        last_error = f"Failed with result '{reason}'"

    oldest = events[0][0] if events else 0
    return {
        "consec": consec,
        "fails": fails,
        "successes": successes,
        "attempts": attempts,
        "entries": len(events),
        "oldest_ts": oldest,
        "last_fail_ts": last_fail_ts,
        "last_error": last_error[:MAX_ERROR_LEN],
    }


def timer_problems(jid: str) -> tuple[list[str], dict]:
    """Installed-pair + timer-state problems for one declared job."""
    probs = []
    svc = UNIT_DIR / f"{jid}.service"
    tim = UNIT_DIR / f"{jid}.timer"
    missing = [p.name for p in (svc, tim) if not p.exists()]
    if missing:
        probs.append("units-missing:" + ",".join(missing))
        return probs, {}
    info = {}
    rc, en = systemctl_user("is-enabled", f"{jid}.timer")
    info["timer_enabled"] = en or f"rc={rc}"
    if en != "enabled":
        probs.append(f"timer-not-enabled:{en or 'unknown'}")
    rc, ac = systemctl_user("is-active", f"{jid}.timer")
    info["timer_active"] = ac or f"rc={rc}"
    if ac in ("inactive", "failed") or (rc != 0 and not ac):
        probs.append(f"timer-inactive:{ac or 'unknown'}")
    return probs, info


def undeclared_units(declared: set[str]) -> dict[str, list[str]]:
    """job:<id> tags in installed *.service files absent from `declared` —
    stale units surviving a host move / manifest removal."""
    found: dict[str, list[str]] = {}
    try:
        files = list(UNIT_DIR.glob("*.service"))
    except Exception:
        return found
    for p in files:
        try:
            head = p.read_text(errors="replace")[:4000]
        except Exception:
            continue
        m = DESC_TAG_RE.search(head)
        if m:
            jid = m.group(1)
            if jid not in declared:
                found.setdefault(jid, []).append(p.name)
    return found


def evaluate(jobs: list[dict], since: str,
             workers: int = 8) -> tuple[dict[str, dict], list[str]]:
    """Per-job verdicts. Returns ({key: verdict}, probe_errors)."""
    verdicts: dict[str, dict] = {}
    errors: list[str] = []

    def probe(job: dict) -> tuple[str, dict, str]:
        jid = job["id"]
        v = {"id": jid, "name": job["name"], "reasons": [],
             "unit": f"{jid}.service"}
        probs, _info = timer_problems(jid)
        v["reasons"].extend(probs)
        events, jerr = journal_events(v["unit"], since)
        if jerr:
            return jid, v, f"{jid}: journalctl failed: {jerr}"
        a = analyze_unit(v["unit"], events)
        if job.get("expected_alert_exit") and \
                alert_exit_ok(v["unit"], events):
            # Nonzero exit with the declared alert marker is a completed
            # activation (the job's alert contract), not a failed one.
            # Keep fails/attempts intact for the audit trail, but clear
            # the streak and credit one success so the verdict stays green.
            a["consec"] = 0
            a["successes"] = max(a["successes"], 1)
        v.update(a)
        if a["consec"] >= CONSEC_MIN:
            v["reasons"].append(f"consecutive-failures:{a['consec']}")
        elif a["attempts"] >= 1 and a["successes"] == 0:
            v["reasons"].append(
                f"zero-successes:{a['attempts']} attempt(s), "
                "0 success(es) in journal window")
        return jid, v, ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for jid, v, err in ex.map(probe, jobs):
            verdicts[jid] = v
            if err:
                errors.append(err)
    return verdicts, errors


# ------------------------------------------------------------ board-api
def api(path: str, body: dict | None = None, timeout: int = 30):
    """POST/GET board-api. Returns (status, json|None, err)."""
    url = f"{BOARD_API}{path}"
    try:
        if body is None:
            req = urllib.request.Request(url, headers={
                "User-Agent": "job-health-sweep/1.0"})
        else:
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json",
                         "User-Agent": "job-health-sweep/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            try:
                return r.status, json.loads(r.read() or b"{}"), ""
            except Exception:
                return r.status, {}, ""
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except Exception:
            payload = {}
        return e.code, payload, str(payload.get("error") or e)
    except Exception as e:
        return 0, None, f"{type(e).__name__}: {e}"


def card_exists(card_id: str) -> tuple[str, str]:
    """('missing'|'open'|'done'|'error', detail)."""
    st, payload, err = api(f"/card/{card_id}")
    if st == 404:
        return "missing", ""
    if st != 200 or not isinstance(payload, dict) or "card" not in payload:
        return "error", err or f"http {st}"
    col = (payload.get("card") or {}).get("column") or "backlog"
    return ("done" if col == "done" else "open"), col


def post(path: str, body: dict) -> tuple[bool, str]:
    st, payload, err = api(path, body)
    if st == 200 and isinstance(payload, dict) and payload.get("ok"):
        return True, str(payload.get("message") or "")
    # /card create returns {ok:True,...}; a duplicate-id 400 is loud too
    return False, f"http {st}: {err or payload}"


def comment(card_id: str, text: str, req: str = "") -> bool:
    body = {"id": card_id, "from": "chaba", "text": text[:500]}
    if req:
        body["request_id"] = req
    ok, msg = post("/comment", body)
    if not ok:
        sys.stderr.write(f"job-health-sweep: comment failed: {msg}\n")
    return ok


def fmt_verdict(v: dict, host: str) -> str:
    bits = [f"{v['id']} ({v['name']})"]
    bits.append("; ".join(v["reasons"]))
    if v.get("attempts"):
        bits.append(
            f"journal: {v['attempts']} attempt(s), "
            f"{v['successes']} success(es), consec-fail={v['consec']}")
    if v.get("last_error"):
        bits.append(f"last error: '{v['last_error']}'")
    return " — ".join(bits)


def fmt_verdict_short(v: dict) -> str:
    """~60-char one-liner for flood-batch comments (500-char cap)."""
    kinds = ",".join(r.split(":", 1)[0] for r in v["reasons"])
    extra = f" consec={v['consec']}" if v.get("consec") else ""
    return f"{v['id']}[{kinds}{extra}]"


def ensure_card(card_id: str, host: str, failing: dict[str, dict],
                exists: str) -> bool:
    """Create (or reopen) the per-host auto card. Returns True when the
    card is known-open afterwards."""
    n = len(failing)
    if exists == "missing":
        names = ", ".join(sorted(failing))[:300]
        body = {
            "id": card_id,
            "title": f"Job health sweep — declared-job failures on {host}",
            "column": "review",
            "review_kind": "triage",
            "program": "chaba-ci",
            "priority": "high" if n >= 3 else "medium",
            "tags": ["ops", "jobs", "job-health-sweep", host],
            "brief": ("Automated per-host sweep (scripts/ops/"
                      "job-health-sweep.py, ssot.jobs.yml "
                      "job-health-sweep) found declared jobs that are "
                      "failing, never firing, or running stale units. "
                      "Each comment names the job, the journal/systemd "
                      "evidence, and the consecutive-fail count. Fix on "
                      "the host; the card auto-closes when green."),
            "note": (f"{n} failing job(s) on {host}: {names}. "
                     "Generated by job-health-sweep — do not dispatch."),
            "help": ("Investigate on the host: `journalctl --user -u "
                     "<job>.service -n 100` for the failure tail, "
                     "`systemctl --user list-timers` / `is-enabled "
                     "<job>.timer` for never-fires cases, and "
                     "`systemctl --user cat <job>.service` for unit "
                     "drift. Declared set: docs/ssot/infrastructure/"
                     "ssot.jobs.yml host: " + host + "."),
            "text": "auto-card from job-health-sweep",
            "from": "chaba",
        }
        ok, msg = post("/card", body)
        if ok:
            return True
        # duplicate-id race -> treat as existing and let comments land
        if "already exists" in msg:
            return True
        sys.stderr.write(f"job-health-sweep: card create failed: {msg}\n")
        return False
    if exists == "done":
        ok, msg = post("/action", {"id": card_id, "do": "move",
                                   "column": "review", "from": "chaba"})
        if ok:
            comment(card_id,
                    f"[job-health-sweep] {n} job(s) failing again on "
                    f"{host} — card reopened.")
            return True
        sys.stderr.write(f"job-health-sweep: reopen failed: {msg}\n")
        return False
    return exists == "open"


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"jobs": {}}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_name(STATE.name + ".tmp")
    tmp.write_text(json.dumps(st, indent=1, sort_keys=True))
    tmp.replace(STATE)


def _parse_ts(s: str) -> float:
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def run_sweep(host: str, jobs: list[dict], since: str,
              no_alert: bool = False, workers: int = 8) -> int:
    card_id = f"job-auto-health-{host.replace('_', '-')}"
    verdicts, probe_errors = evaluate(jobs, since, workers=workers)

    # undeclared installed units -> pseudo-verdicts
    declared_ids = {j["id"] for j in jobs}
    for jid, files in undeclared_units(declared_ids).items():
        verdicts[f"unit:{jid}"] = {
            "id": f"unit:{jid}", "name": f"undeclared unit {jid}",
            "unit": ",".join(files),
            "reasons": ["undeclared-job-unit: installed on this host but "
                        "not declared for it in ssot.jobs.yml "
                        "(stale unit / host-move drift)"],
            "consec": 0, "fails": 0, "successes": 0, "attempts": 0,
            "entries": 0, "oldest_ts": 0, "last_fail_ts": 0,
            "last_error": "",
        }

    # journal/systemd probe failures are sweep-level blindness, not a
    # per-job failure claim — one pseudo-verdict keeps them visible on
    # the card without crying wolf on every job at once.
    if probe_errors:
        verdicts["sweep:probes"] = {
            "id": "job-health-sweep", "name": "sweep probe errors",
            "unit": "-",
            "reasons": [f"probe-errors:{len(probe_errors)} unit(s) "
                        "unreadable — sweep blind for them: "
                        + "; ".join(probe_errors[:5])],
            "consec": 0, "fails": 0, "successes": 0, "attempts": 0,
            "entries": 0, "oldest_ts": 0, "last_fail_ts": 0,
            "last_error": "",
        }

    failing = {k: v for k, v in verdicts.items() if v["reasons"]}
    st = load_state()
    st_jobs = st.setdefault("jobs", {})
    # snapshot pre-run states — the daily summary must not double-post
    # in the same run that files brand-new failure comments.
    was_failing = {k for k in failing
                   if st_jobs.get(k, {}).get("state") == "failing"}
    now = time.time()
    today = now_iso()

    # ---- print verdicts
    for k, v in sorted(verdicts.items()):
        tag = "FAIL" if v["reasons"] else "ok  "
        line = f"{tag} {k}: {'; '.join(v['reasons']) or 'green'}"
        if v.get("attempts"):
            line += (f" [attempts={v['attempts']} ok={v['successes']}"
                     f" consec={v['consec']}]")
        print(line)
    for e in probe_errors:
        print(f"WARN {e}", file=sys.stderr)

    if not failing:
        print(f"job-health-sweep: {host} green — {len(verdicts)} job(s) "
              f"checked, 0 failing")
        # recovery handled below via state diff; no card writes needed
        # unless a card is still open.

    if no_alert:
        print("job-health-sweep: --no-alert, board writes skipped")
        return 0

    # ---- board writes
    exists, detail = card_exists(card_id)
    if exists == "error":
        sys.stderr.write(
            f"job-health-sweep: card probe failed ({detail}) — "
            "comments may not land this run\n")

    card_open = ensure_card(card_id, host, failing, exists) \
        if failing else (exists == "open")

    posted = {"new": 0, "summary": 0, "recovered": 0}

    def sync_job_state(key: str, v: dict, state: str) -> None:
        ent = st_jobs.setdefault(key, {})
        ent.update({
            "state": state,
            "reasons": list(v.get("reasons") or []),
            "consec": v.get("consec", 0),
            "attempts": v.get("attempts", 0),
            "successes": v.get("successes", 0),
            "last_error": v.get("last_error", ""),
            "updated": today,
        })
        if state == "failing" and not ent.get("first_seen"):
            ent["first_seen"] = today
        if state == "ok":
            ent.pop("first_seen", None)

    if card_open:
        # --- new failures: per-job comment (batched when a flood)
        # request_id carries the episode counter — stable across a
        # lost-response retry (dedupes) but unique per fail/recover
        # episode (a same-day relapse still comments).
        new_keys = [k for k in failing
                    if st_jobs.get(k, {}).get("state") != "failing"]
        if new_keys:
            req_keys = sorted(new_keys)
            if len(new_keys) <= MAX_COMMENT_JOBS:
                for k in req_keys:
                    v = failing[k]
                    ep = int(st_jobs.get(k, {}).get("episode", 0))
                    rid = f"jhs-{host}-{k}-new-e{ep}"
                    text = (f"[job-health-sweep] NEW failure on {host}: "
                            f"{fmt_verdict(v, host)}")
                    if comment(card_id, text, req=rid):
                        sync_job_state(k, v, "failing")
                        st_jobs[k]["episode"] = ep + 1
                        posted["new"] += 1
            else:
                # flood path: chunk short one-liners under the 500-char
                # comment cap; each chunk syncs only its own keys so a
                # failed chunk retries next run without duplicating
                # the chunks that already landed.
                chunks, cur_keys, cur = [], [], ""
                for k in req_keys:
                    line = f"- {fmt_verdict_short(failing[k])}\n"
                    if cur and len(cur) + len(line) > 400:
                        chunks.append((cur_keys, cur))
                        cur_keys, cur = [], ""
                    cur += line
                    cur_keys.append(k)
                if cur:
                    chunks.append((cur_keys, cur))
                total = len(chunks)
                for i, (keys, body_txt) in enumerate(chunks):
                    rid = (f"jhs-{host}-newbatch-{today[:10]}"
                           f"-{i}")
                    head = (f"[job-health-sweep] {len(new_keys)} NEW "
                            f"failures on {host} ({i + 1}/{total}):\n")
                    if comment(card_id, head + body_txt, req=rid):
                        for k in keys:
                            ep = int(st_jobs.get(k, {}).get(
                                "episode", 0))
                            sync_job_state(k, failing[k], "failing")
                            st_jobs[k]["episode"] = ep + 1
                        posted["new"] += len(keys)

        # --- still-failing daily summary. Anchored on the OLDEST
        # first_seen among currently-failing jobs so the first digest
        # lands ~20h into an episode — not on the run right after the
        # new-failure comments — then repeats every SUMMARY_EVERY_S.
        last_sum = _parse_ts(str(st.get("last_summary") or ""))
        oldest_seen = min(
            (_parse_ts(str(st_jobs.get(k, {}).get("first_seen") or ""))
             for k in failing), default=0.0)
        if failing and was_failing \
                and now - oldest_seen > SUMMARY_EVERY_S \
                and now - last_sum > SUMMARY_EVERY_S:
            lines = []
            for k in sorted(failing):
                v = failing[k]
                ent = st_jobs.get(k, {})
                since_s = ent.get("first_seen") or today[:10]
                lines.append(
                    f"- {v['id']}: {', '.join(v['reasons'])} "
                    f"(consec={v.get('consec', 0)}, "
                    f"failing since {since_s[:10]})")
            rid = f"jhs-{host}-summary-{today[:10]}"
            text = (f"[job-health-sweep] still-failing summary on "
                    f"{host} ({len(failing)} job(s)):\n"
                    + "\n".join(lines[:25]))
            if comment(card_id, text, req=rid):
                st["last_summary"] = today
                posted["summary"] = 1

    # --- recovered (only for jobs/units still being evaluated —
    # a job that left the manifest isn't "recovered", it's gone).
    # The state flip is UNCONDITIONAL: the job is verifiably green this
    # run, and a stale 'failing' flag would suppress the next real
    # alert. The courtesy comment is best-effort (card open + api up).
    live = set(verdicts)
    recovered = [k for k, ent in st_jobs.items()
                 if ent.get("state") == "failing"
                 and k not in failing and k in live]
    for k in sorted(recovered):
        old = st_jobs.get(k, {})
        ep = int(old.get("episode", 0))
        rid = f"jhs-{host}-{k}-rec-e{ep}"
        text = (f"[job-health-sweep] RECOVERED on {host}: {k} — "
                f"was failing ({'; '.join(old.get('reasons') or [])})"
                ", now green.")
        ok = comment(card_id, text, req=rid) if card_open else False
        sync_job_state(k, {"reasons": [], "consec": 0,
                           "attempts": 0, "successes": 0,
                           "last_error": ""}, "ok")
        if ok:
            posted["recovered"] += 1

    # prune state for evaluated-set members that went away entirely
    for k in list(st_jobs):
        if k not in live:
            st_jobs.pop(k, None)

    # ---- all-clear -> close the card
    if not failing and exists == "open":
        ok, msg = post("/action", {"id": card_id, "do": "close",
                                   "from": "chaba"})
        if ok:
            print(f"job-health-sweep: card {card_id} auto-closed")
        else:
            sys.stderr.write(
                f"job-health-sweep: auto-close failed: {msg}\n")

    st["last_run"] = today
    st["host"] = host
    st["window"] = since
    save_state(st)

    print(f"job-health-sweep: {host} — {len(failing)} failing / "
          f"{len(verdicts)} checked; comments new={posted['new']} "
          f"summary={posted['summary']} recovered={posted['recovered']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=detect_host())
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--window", default=WINDOW,
                    help="journalctl --since window (default '30 days ago')")
    ap.add_argument("--no-alert", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    ok, state = user_manager_ok()
    if not ok:
        sys.stderr.write(
            f"job-health-sweep: systemctl --user unavailable "
            f"({state}) — cannot evaluate\n")
        return 1

    try:
        jobs = load_jobs(Path(args.manifest), args.host)
    except Exception as e:
        sys.stderr.write(f"job-health-sweep: manifest read failed: {e}\n")
        return 1
    if not jobs:
        sys.stderr.write(
            f"job-health-sweep: no declared systemd jobs for host "
            f"{args.host!r} in {args.manifest} — nothing to sweep\n")
        return 1

    return run_sweep(args.host, jobs, args.window,
                     no_alert=args.no_alert, workers=args.workers)


if __name__ == "__main__":
    sys.exit(main())
