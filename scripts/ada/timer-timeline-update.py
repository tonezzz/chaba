#!/usr/bin/env python3
"""timer-timeline-update.py — fleet timer census -> CMS `timer-timeline`.

Collects per-host user-timer state over tailnet ssh (local for the host
the script runs on), appends a JSONL ledger (the durable shared memory),
and renders the CMS pages:

  timer-timeline            rollup — one status row per timer, all hosts
  timer-timeline-<host>     leaf   — 24h event log per host
  timer-timeline-qc         leaf   — coverage/freshness/self-checks/audit

Health:  ok = enabled+armed · late = next-fire already past-due
         failing = service in failed state · off = disabled/missing unit

Env:
    MDDB_BASE_URL   default http://100.102.134.91:11023/v1
    REPO            default = this checkout root
    TT_HOSTS        comma-sep host list override
    TT_STATE_DIR    default ~/.local/share/chaba/timer-timeline

Usage:
    timer-timeline-update.py            # collect + publish
    timer-timeline-update.py --dry-run  # collect + render, write nothing
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

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"
PAGE = "timer-timeline"
STATE_DIR = Path(os.environ.get(
    "TT_STATE_DIR", str(Path.home() / ".local/share/chaba/timer-timeline")))
LEDGER = STATE_DIR / "ledger.jsonl"
STATE = STATE_DIR / "state.json"
ICT = timezone(timedelta(hours=7))
GENERATOR = "timer-timeline-update.py"
VERSION = "1.0.0 2026-10-13"

# household hosts with user timers (idc01 = teardown, excluded)
HOSTS = os.environ.get(
    "TT_HOSTS", "tony-dell,tony-omen,mn01,idc03,idc02,tony-macbook"
).split(",")

NOISE = re.compile(
    r"^(snap\.|ubuntu-insights|launchpadlib|motd|fwupd|man-db|"
    r"update-notifier|fstrim|logrotate|apt-|dpkg|phpsessionclean|"
    r"systemd-tmpfiles|e2scrub|sysstat|anacron|[0-9a-f]{16,})")

COLLECT_SH = r"""
names=$( { systemctl --user list-unit-files '*.timer' --no-legend --plain 2>/dev/null | awk '{print $1}';
           systemctl --user list-timers --all --no-legend --plain 2>/dev/null | awk '{print $(NF-1)}'; } \
         | grep -E '^[a-zA-Z0-9@_.-]+\.timer$' | sed 's/\.timer$//' | sort -u )
for n in $names; do
  echo "T|$n"
  systemctl --user show "$n.timer" -p UnitFileState,NextElapseUSecRealtime,LastTriggerUSec,ActiveState 2>/dev/null
  systemctl --user show "$n.service" -p Result,ExecMainStatus,ActiveState,ExecMainExitTimestamp 2>/dev/null | sed 's/^/SVC_/'
done
echo "@@FAILED@@"
systemctl --user list-units --type=service --state=failed --no-legend --plain 2>/dev/null | awk '{print $1}'
echo "@@JOURNAL@@"
journalctl --user --since "-26h" --no-pager -o short-iso 2>/dev/null \
  | grep -E "Finished .+\.service|Failed to start|Main process exited" \
  | tail -80
"""


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


def get_doc(key, lang="en"):
    docs = _search_all(COLLECTION)
    return next((d for d in docs
                 if d.get("key") == key and d.get("lang") == lang), None)


def publish(key, body, now, role, title, extra_meta=None):
    doc = get_doc(key) or {}
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    meta.update({
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "lang": ["en"], "kind": ["report"], "attribute": ["report"],
        "report_role": [role], "generated_by": [GENERATOR],
        "domain": ["ops"], "fresh_for": ["1h"],
        "sources": ["systemctl --user list-timers per host",
                    "journalctl --user -26h per host",
                    "ssot.audit.hosts.yml timer census"],
        "title": [title],
        "parent": ["timer-timeline" if role == "leaf" else "reports-index"],
        "written_by": ["timer-timeline"],
    })
    if extra_meta:
        meta.update(extra_meta)
    _post("add", {"collection": COLLECTION, "key": key, "lang": "en",
                  "contentMd": body, "meta": meta}, timeout=120)


# ---------- collect ----------

def collect_host(host, local=False):
    """Return {timers:{name:info}, failed:[svc], results:{svc:...},
    journal:[lines], ok:bool, error:str|None}"""
    if local:
        r = subprocess.run(["bash", "-c", COLLECT_SH],
                           capture_output=True, text=True, timeout=120)
        out, err = r.stdout, r.stderr
    else:
        try:
            r = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
                 host, "bash -s"],
                input=COLLECT_SH, capture_output=True, text=True,
                timeout=120)
            out, err = r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "ssh timeout", "timers": {},
                    "failed": [], "results": {}, "journal": []}
    if not out.strip():
        return {"ok": False,
                "error": (err.strip() or "no output")[:200],
                "timers": {}, "failed": [], "results": {}, "journal": []}
    secs = re.split(r"^@@(\w+)@@$", out, flags=re.M)
    # secs = [pre, name, body, name, body, ...]
    parts = {secs[i]: secs[i + 1]
             for i in range(1, len(secs) - 1, 2)}
    timers = {}
    cur = None
    for ln in secs[0].splitlines():
        ln = ln.strip()
        if ln.startswith("T|"):
            cur = ln.split("|", 1)[1]
            if not NOISE.match(cur):
                timers[cur] = {}
            else:
                cur = None
        elif cur in timers and "=" in ln:
            k, v = ln.split("=", 1)
            timers[cur][k] = v
    for name, d in timers.items():
        d["enabled"] = d.pop("UnitFileState", "-") or "-"
        d["timer_active"] = d.pop("ActiveState", "")
        d["next_us"] = _usec(d.pop("NextElapseUSecRealtime", 0))
        d["next"] = _usec_fmt(d["next_us"])
        d["last_us"] = _usec(d.pop("LastTriggerUSec", 0))
        d["last"] = _usec_fmt(d["last_us"])
        d["result"] = d.pop("SVC_Result", "-") or "-"
        d["exit"] = d.pop("SVC_ExecMainStatus", "-") or "-"
        d["svc_active"] = d.pop("SVC_ActiveState", "-") or "-"
        exit_ts = d.pop("SVC_ExecMainExitTimestamp", "")
        # wall-clock "last service exit" e.g. "Tue 2026-10-13 07:55:00 +07"
        m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", exit_ts)
        if m:
            d["last"] = m.group(1)[5:] + " " + m.group(2)
    failed = [ln.strip().replace(".service", "")
              for ln in parts.get("FAILED", "").splitlines()
              if ln.strip() and ln.strip() != "\u25cf"]
    for name, t in timers.items():
        if name in failed:
            t["failed_now"] = True
    journal = [ln.strip() for ln in parts.get("JOURNAL", "").splitlines()
               if ln.strip()]
    for t in timers.values():
        t["failed_now"] = t.get("failed_now", False)
    return {"ok": True, "error": None, "timers": timers,
            "failed": failed, "journal": journal}


def _usec(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _usec_fmt(v):
    us = _usec(v)
    if not us:
        return "-"
    return datetime.fromtimestamp(
        us / 1e6, tz=ICT).strftime("%m-%d %H:%M")


def classify(t, now_us=0):
    if t.get("enabled") in ("disabled", "masked"):
        return "off"
    if t.get("enabled") in ("missing", "-", ""):
        return "missing"
    if t.get("failed_now") or t.get("result") in ("failed", "exit-code"):
        return "failing"
    if (t.get("timer_active") or "") != "active":
        return "off"          # unit file enabled but timer not armed
    nxt = t.get("next_us") or 0
    if now_us and nxt and nxt < now_us:
        return "late"         # armed but past its own next-fire time
    return "ok"


ICON = {"ok": "ok", "off": "off", "missing": "missing",
        "failing": "FAILING", "late": "LATE"}


# ---------- render ----------

def render_rollup(sweep, now):
    L = [f"# Timer Timeline — fleet\n",
         f"_Updated {now.strftime('%Y-%m-%d %H:%M ICT')} · refreshed every "
         f"15min · leaf pages per host below_\n"]
    tot, cnt = 0, {"ok": 0, "off": 0, "missing": 0, "failing": 0, "late": 0}
    rows = []
    now_us = int(datetime.now().timestamp() * 1e6)
    for host, data in sweep["hosts"].items():
        if not data["ok"]:
            rows.append(f"| `{host}` | — | — | — | — | ⚠️ unreachable "
                        f"({data['error'] or '?'}) | — |")
            continue
        for name, t in sorted(data["timers"].items()):
            st = classify(t, now_us)
            cnt[st] += 1
            tot += 1
            mark = {"ok": "🟢", "off": "⬛", "missing": "⬛",
                    "failing": "🔴", "late": "🟡"}[st]
            rows.append(
                f"| `{name}` | {host} | {t.get('last','-')} | "
                f"{t.get('result','-')} (exit {t.get('exit','-')}) | "
                f"{mark} {ICON[st]} |")
    L.append(f"\n**{tot} timers** · 🟢 {cnt['ok']} · 🟡 {cnt['late']} · "
             f"🔴 {cnt['failing']} · ⬛ {cnt['off']+cnt['missing']}\n")
    L.append("\n| timer | host | last run | result | state |\n"
             "|---|---|---|---|---|\n")
    L += rows
    bad = [r for r in rows if "🔴" in r or "🟡" in r or "unreachable" in r]
    if bad:
        L.append("\n## ⚠️ Attention\n")
        L += bad
    L.append("\n_Ledger: ~/.local/share/chaba/timer-timeline/ledger.jsonl "
             "on tony-dell — the durable memory this page renders._\n")
    return "\n".join(L)


def render_host_leaf(host, data, now):
    L = [f"# Timer Timeline — {host}\n",
         f"_Updated {now.strftime('%Y-%m-%d %H:%M ICT')} · part of "
         f"[timer-timeline](#)_\n"]
    if not data["ok"]:
        L.append(f"\n⚠️ **host unreachable this sweep** — "
                 f"`{data['error']}`\n")
        L.append("An unreachable host is attributed as host-down, not "
                 "timer failure — see timer-timeline-qc.\n")
        return "\n".join(L)
    L.append("\n| timer | enabled | last run | result | exit |\n"
             "|---|---|---|---|---|\n")
    for name, t in sorted(data["timers"].items()):
        L.append(f"| `{name}` | {t.get('enabled','-')} | "
                 f"{t.get('last','-')} | {t.get('result','-')} | "
                 f"{t.get('exit','-')} |")
    if data["failed"]:
        L.append("\n## Currently failed services\n")
        for f in data["failed"]:
            L.append(f"- `{f}`")
    if data["journal"]:
        L.append("\n## Journal tail (24h)\n\n```\n")
        L += data["journal"][-60:]
        L.append("```")
    return "\n".join(L)


def render_qc(sweep, now, collect_ms, declared):
    L = [f"# Timer Timeline — QC / Audit\n",
         f"_Updated {now.strftime('%Y-%m-%d %H:%M ICT')} · what to expect "
         f"from the timer-timeline pages and how they were produced_\n"]
    L.append("## Collector self-checks\n")
    L.append("| check | value |\n|---|---|\n")
    seen = sum(len(d["timers"]) for d in sweep["hosts"].values())
    ok_hosts = sum(1 for d in sweep["hosts"].values() if d["ok"])
    L.append(f"| sweep duration | {collect_ms}ms |")
    L.append(f"| hosts reached | {ok_hosts}/{len(sweep['hosts'])} |")
    L.append(f"| timers observed | {seen} |")
    L.append(f"| timers declared in audit.hosts | {declared} |")
    cov = (f"{100*seen/declared:.0f}%" if declared else "n/a")
    L.append(f"| coverage (observed/declared) | {cov} |")
    L.append(f"| ledger | {LEDGER} |")
    L.append(f"| generator | {GENERATOR} v{VERSION} |")
    L.append("\n## Per-host collect\n\n| host | state | timers |\n"
             "|---|---|---|\n")
    for host, d in sweep["hosts"].items():
        st = "ok" if d["ok"] else f"unreachable: {d['error']}"
        L.append(f"| {host} | {st} | {len(d['timers'])} |")
    L.append("\n## Expected vs observed (health legend)\n")
    L.append("- 🟢 **ok** — unit enabled, next fire scheduled, last run not failed")
    L.append("- 🔴 **failing** — service currently in `failed` state or last Result=failed")
    L.append("- ⬛ **off/missing** — timer disabled or unit absent (drift-reconcile territory)")
    L.append("- 🟡 **late** — next fire is past-due (armed but starved)")
    L.append("- host unreachable ≠ timer failure — attributed separately so a down host does not cry wolf")
    L.append("\n## Sentinel\n")
    L.append("Independent `timer-sentinel.timer` (dell, 10min, NOT via "
             "dispatcher) reads state.json and fires `timer-alert-*` "
             "kanban cards for: disabled/missing expected timer, "
             "missed tick >2×cadence, ≥2 consecutive failures, stale "
             "collector sweep. Dedup: no re-fire while its card is open.")
    L.append("\n## Audit trail\n")
    L.append("- 2026-10-13 v1.0.0 — born from OPS-0531 (chaba-jobs.timer "
             "silently disabled 2d; 4 jobs starved). Initial census: "
             "114 timers declared across 5 hosts.")
    L.append("- Sentinel rules + this generator's changes get a line "
             "here — the audit of the auditor.\n")
    return "\n".join(L)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    t0 = datetime.now()
    now_utc = datetime.now(timezone.utc)
    now = now_utc.astimezone(ICT)

    sweep = {"ts": now_utc.isoformat(timespec="seconds"), "hosts": {}}
    import socket
    here = socket.gethostname().split(".")[0]
    for host in HOSTS:
        sweep["hosts"][host] = collect_host(host, local=(host == here))

    collect_ms = int((datetime.now() - t0).total_seconds() * 1000)

    # declared count from audit SSOT
    declared = 0
    try:
        import yaml
        doc = yaml.safe_load(
            (REPO / "docs/ssot/infrastructure/ssot.audit.hosts.yml")
            .read_text())
        for blk in doc["hosts"].values():
            declared += sum(1 for e in (blk.get("expected_services") or [])
                            if str(e.get("name", "")).endswith(".timer"))
    except Exception as e:
        print(f"warn: audit.hosts unreadable ({e})", file=sys.stderr)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a") as fh:
        fh.write(json.dumps(sweep) + "\n")
    STATE.write_text(json.dumps({
        "ts": sweep["ts"], "collect_ms": collect_ms,
        "timers": {h: {n: {"enabled": t.get("enabled"),
                          "result": t.get("result"),
                          "failed_now": t.get("failed_now"),
                          "last": t.get("last"), "next": t.get("next"),
                          "last_us": t.get("last_us"),
                          "next_us": t.get("next_us")}
                       for n, t in d["timers"].items()}
                   for h, d in sweep["hosts"].items()},
        "host_ok": {h: d["ok"] for h, d in sweep["hosts"].items()},
    }))

    rollup = render_rollup(sweep, now)
    qc = render_qc(sweep, now, collect_ms, declared)
    if args.dry_run:
        print(rollup)
        print("=" * 60)
        print(qc)
        for h in HOSTS:
            print("=" * 60, f"leaf {h}")
            print(render_host_leaf(h, sweep["hosts"][h], now)[:1500])
        return 0

    publish(PAGE, rollup, now_utc, "rollup", "Timer Timeline — fleet")
    publish(PAGE + "-qc", qc, now_utc, "leaf",
            "Timer Timeline — QC/Audit")
    for host, d in sweep["hosts"].items():
        publish(f"{PAGE}-{host}", render_host_leaf(host, d, now),
                now_utc, "leaf", f"Timer Timeline — {host}")

    try:
        sys.path.insert(0, str(REPO / "scripts" / "lib"))
        from cms_index import regen_reports_index
        regen_reports_index(MDDB, written_by=GENERATOR)
    except Exception as e:
        print(f"warn: reports-index regen failed ({e})", file=sys.stderr)

    print(f"timer-timeline published — {sum(len(d['timers']) for d in sweep['hosts'].values())} timers, "
          f"{collect_ms}ms, {ok_hosts} hosts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
