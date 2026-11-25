#!/usr/bin/env python3
"""scenario-runner drift check (card scenario-runner-deployed-drift-check).

Watches the copy-on-install payload of stacks/services/ada-scenario-runner/
on idc03. install.sh deliberately installs scenario-suite-run.sh to
~/.local/share/ada-scenario-runner/ so a stale checkout can never break
the weekly suites — but that isolation also means repo fixes do NOT
reach the installed wrapper until someone re-runs install.sh. The
2026-11-08 incident is the detection gap this closes: the OPS-0581
exit-code contract merged Oct 13, yet the Oct 30 + Nov 6 weekly runs
completed and still alerted as exit-code because the installed wrapper
was 24 days stale and nobody noticed.

For each payload pair (installed path, repo-relative source):
  * missing         — installed file absent (install.sh never ran, or
                      the file was deleted)
  * not-executable  — payload lost its +x bit; the weekly .service
                      ExecStart lines exec it directly
  * content-drift   — sha256 differs from the repo source
  * reference-missing — the repo checkout lacks the source file, so
                      drift cannot be judged (checkout broken or the
                      payload moved — either way the check is blind)

Reference = the exec checkout ~/CascadeProjects/chaba (ssot.jobs.yml
config.repo.idc03; kept current by chaba-repo-sync.timer's git-safe-pull).
Runtime state in the same installed dir (gate-state.json, prod-allow-*
sentinels) is NOT payload and is never compared — the manifest below is
the whole contract; extend PAYLOAD to cover more install.sh outputs.

Alert channel: board-api /inbox — a deduped focus-inbox entry that
surfaces in the daily brief, at most once per --repeat-h per condition
(default 6h). Recovery is silent + journaled, matching the inbox's
no-resolve semantics.

Exit-code contract (docs/kb/timer-expectations.md, OPS-0581): the check
COMPLETED whether or not it found drift — exit 0 on any completed
evaluation; findings travel on the inbox channel. Non-zero only when
the run itself fails (uncaught error). The sibling watchdogs
served-checkout-watchdog / netdata-nodes-watch exit 1 on alert, which
red-flags the timer-sentinel on findings — deliberately not repeated.

Usage: scenario-runner-drift-check.py [--repo DIR] [--state FILE]
       [--repeat-h H] [--no-alert]
Env:   CHABA_REPO — repo checkout override (default ~/CascadeProjects/chaba)
       BOARD_API  — default https://idc03.taila0626a.ts.net:10000
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

HOME = Path.home()
REPO = Path(os.environ.get("CHABA_REPO",
                           str(HOME / "CascadeProjects/chaba")))
BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
STATE = Path.home() / ".local/state/scenario-runner-drift-check.json"
LABEL = "Scenario runner drift — idc03"
TAGS = ["ops", "monitor", "ada-scenario-runner", "drift-check"]

# (installed path relative to ~, repo-relative source path) — the
# copy-on-install payload install.sh places outside the checkout.
PAYLOAD = [
    (".local/share/ada-scenario-runner/scenario-suite-run.sh",
     "stacks/services/ada-scenario-runner/scenario-suite-run.sh"),
]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def collect(repo: Path) -> list[tuple[str, str]]:
    """-> [(condition, detail)] — empty list means clean."""
    problems = []
    for inst_rel, repo_rel in PAYLOAD:
        inst = HOME / inst_rel
        src = repo / repo_rel
        name = Path(inst_rel).name
        if not src.is_file():
            problems.append((
                "reference-missing",
                f"{name}: repo source {src} missing — drift cannot be "
                "judged; check the exec checkout is healthy and the "
                "payload still lives at this path"))
            continue
        if not inst.is_file():
            problems.append((
                "missing",
                f"{name}: {inst} absent — re-run "
                "stacks/services/ada-scenario-runner/install.sh on idc03"))
            continue
        if not os.access(inst, os.X_OK):
            problems.append((
                "not-executable",
                f"{name}: {inst} lost its +x bit — the weekly "
                "ada-scenario-*.service ExecStart lines exec it "
                "directly; chmod 0755 or re-run install.sh"))
        inst_sha, src_sha = sha256(inst), sha256(src)
        if inst_sha != src_sha:
            problems.append((
                "content-drift",
                f"{name}: installed sha {inst_sha[:16]} != repo "
                f"{src_sha[:16]} ({src}) — the copy-on-install "
                "wrapper is stale; re-run install.sh on idc03 (the "
                "2026-11-08 OPS-0581 incident class)"))
    return problems


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"alerts": {}}


def save_state(path: Path, st: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as f:
        f.write(json.dumps(st))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def recently_alerted(st: dict, cond: str, repeat_h: float) -> bool:
    at = (st.get("alerts") or {}).get(cond)
    if not at:
        return False
    try:
        return (dt.datetime.now(dt.timezone.utc)
                - dt.datetime.fromisoformat(at)).total_seconds() \
            < repeat_h * 3600
    except Exception:
        return False


def file_inbox(text: str) -> bool:
    body = {"text": text, "label": LABEL, "priority": "high",
            "tags": TAGS, "owner": "tony"}
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/inbox", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception as e:
        sys.stderr.write(f"drift-check: inbox post failed: {e}\n")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(REPO),
                    help="chaba checkout holding the repo source "
                         "(default ~/CascadeProjects/chaba)")
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--repeat-h", type=float, default=6.0,
                    help="min hours between repeat alerts per condition")
    ap.add_argument("--no-alert", action="store_true",
                    help="check only, print verdict — never posts")
    args = ap.parse_args()

    state_path = Path(args.state)
    repo = Path(args.repo)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    st = load_state(state_path)
    problems = collect(repo)

    # per-file condition keys so two drifting payloads alert independently
    seen = set()
    for cond, detail in problems:
        key = f"{cond}:{detail.split(':', 1)[0]}"
        if key in seen:
            continue
        seen.add(key)
        if recently_alerted(st, key, args.repeat_h):
            print(f"alert suppressed (dedupe): {detail}")
            continue
        text = (f"Deployed ada-scenario-runner drift on idc03: {detail}. "
                "The wrapper is copy-on-install by design "
                "(stacks/services/ada-scenario-runner/install.sh -> "
                "~/.local/share/ada-scenario-runner/) — repo fixes do "
                "not reach it until install.sh re-runs. This is the gap "
                "behind the 2026-11-08 OPS-0581 exit-code incident; fix "
                "with `cd ~/CascadeProjects/chaba/stacks/services/"
                "ada-scenario-runner && ./install.sh` on idc03.")
        if args.no_alert or file_inbox(text):
            st.setdefault("alerts", {})[key] = now
        print(f"ALERT: {detail}")

    alerts = st.setdefault("alerts", {})
    live = {f"{c}:{d.split(':', 1)[0]}" for c, d in problems}
    for key in list(alerts):
        if key not in live:
            print(f"recovered (silent): {key}")
            del alerts[key]

    if not problems:
        print(f"ok — {len(PAYLOAD)} payload file(s) match {repo}")
        st["last_ok"] = now

    save_state(state_path, st)
    # OPS-0581 contract: a completed check exits 0 whether or not it
    # found drift — findings ride the /inbox channel, not the exit code.
    return 0


if __name__ == "__main__":
    sys.exit(main())
