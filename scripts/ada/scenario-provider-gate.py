#!/usr/bin/env python3
"""scenario-provider-gate — fail-fast ExecCondition for ada-scenario-smoke.

(card scenario-spend-guard, 2026-10-11) The hourly smoke tier opens real
/ws sessions against ada-ha-tony; each session opens an upstream Gemini
Live session. When the provider is quota-dead the in-suite sentinel does
NOT trip: the 1011 'exceeded your current quota' close only lives in the
backend journal — scenario-live sees a bare ready-timeout and reports
plain 'fail', so all ~34 scenarios x 2 retries burn connects anyway
(2026-10-11 03:00 run: ~64 billed connect attempts in 6 min while dead).

This gate probes ONCE per scheduled run, before the container starts —
zero API spend (journal + env-file reads only):

  1. unit live     — target backend unit must be active (else 'infra').
  2. free lane     — the unit's GEMINI_API_KEY must not be the PAID key
                     while a FREE lane exists (sha-compare against
                     gemini-keys.env; key material never logged).
  3. quota-dead    — quota-shaped provider errors in the last --window
                     minutes with no healthy session marker newer than
                     the newest error (else 'skip-quota').

On a skip verdict it records the skip the way the runner itself would:
one report/<scenario>-<ts> doc per smoke-tier scenario with status
skip-quota|infra (lab-results stays honest), a report/smoke-gate-<ts>
summary doc, and a throttled chaba-event. Exit 1 -> systemd skips the
unit cleanly ('start condition failed', not a failure).

Reconnect churn (always runs, both verdicts): counts ws 'client
connected' + upstream 'provider reconnected' per ada-* unit over the last
hour; >50 ws connects/hour emits a throttled warn to chaba-events —
retry-storming clients are the other half of the quota burn (card
acceptance #4).

Wired as ExecCondition on ada-scenario-smoke.service:
  ExecCondition=/usr/bin/python3 %h/CascadeProjects/chaba/scripts/ada/\\
      scenario-provider-gate.py --unit ada-ha-tony

Env: MDDB_BASE_URL / MDDB_OPS_URL (the unit [Service] env already sets
MDDB_BASE_URL; the gate additionally reads --env-file for MDDB_OPS_URL),
SECRETS_DIR, ADA_PI_DIR, GATE_STATE_FILE. Stdlib only — host python3.

  --dry-run   probe and print the verdict, write nothing, exit by verdict
  --report    force MDDB skip-reporting even when the verdict is 'ok'
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

COLLECTION = "ada-ha-scenario-reports"
REPORT_TTL_S = 3 * 86400  # skip-quota/infra TTL — parity with scenario-report.py
DEFAULT_UNITS = ["ada-ha-tony", "ada-ha-michael"]
STATE = Path(os.environ.get(
    "GATE_STATE_FILE",
    "~/.local/share/ada-scenario-runner/gate-state.json")).expanduser()
SECRETS = Path(os.environ.get(
    "SECRETS_DIR", "~/.config/secrets")).expanduser()
SCENARIOS_DIR = Path(os.environ.get(
    "ADA_PI_DIR", "~/CascadeProjects/ada-voice")).expanduser() / \
    "tests" / "scenarios-live"

# Dunning evidence in the backend journal. 'provider (re)connect failed'
# is the connect-level kill; the quota strings are the reason stamped by
# the upstream close. The bare-429 alternative refuses ',429'/'.429'
# (log-timestamp millis) and 'out=429'/'in=429' (usage-turn lines) —
# both false-positived on real journals (2026-10-11).
RX_CONN_FAIL = re.compile(
    r"provider (connect|reconnect) failed", re.I)
RX_QUOTA = re.compile(
    r"exceeded your current quota|resource.?exhausted|"
    r"received 1011|APIError: 1011|check your plan and billing|"
    r"HTTP.{0,10}429|status.{0,6}429|(?<![0-9A-Za-z=,.])429(?![0-9A-Za-z])",
    re.I)
# Healthy-provider markers — a provider that served anything after the
# last dunning line is not dead.
RX_OK = re.compile(
    r"provider reconnected|prime injected|usage turn|"
    r"assistant response|ready event", re.I)
RX_WS_CONNECT = re.compile(r"client connected", re.I)
RX_UPSTREAM = re.compile(r"provider reconnected", re.I)

RX_YAML_NAME = re.compile(r"^name:\s*(\S+)", re.M)
RX_YAML_TIER = re.compile(r"^tier:\s*(\S+)", re.M)

CHURN_WARN_PER_HOUR = 50          # card acceptance: >50 ws connects/hour
CHURN_WARN_MIN_S = 4 * 3600       # warn at most this often per unit
GATE_WARN_MIN_S = 4 * 3600        # repeat the same verdict at most this often

REPORT_STATUSES = {"quota-dead": "skip-quota", "paid-lane": "skip-quota",
                   "infra": "infra"}


def _sh(args: list[str], timeout: int = 40) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout).stdout
    except Exception:
        return ""


def _journal(unit: str, since: str, until: str | None = None,
             timeout: int = 40) -> list[str]:
    cmd = ["journalctl", "--user", "-u", unit, "--since", since,
           "--no-pager", "-o", "short-iso"]
    if until:
        cmd += ["--until", until]
    out = _sh(cmd, timeout)
    return [l for l in out.splitlines() if l.strip()]


def _env_value(path: Path, name: str) -> str:
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _mddb() -> str:
    return (os.environ.get("MDDB_OPS_URL")
            or os.environ.get("MDDB_BASE_URL")
            or "http://127.0.0.1:11023/v1").rstrip("/")


def _post(url: str, payload: dict, timeout: int = 15) -> bool:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=timeout).read()
        return True
    except Exception as exc:
        print(f"  gate: report write failed: {exc}", file=sys.stderr)
        return False


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state))
    except OSError:
        pass


def emit_event(payload: dict) -> None:
    """chaba-event warn — best-effort via scripts/ada/chaba_event.py."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import chaba_event
        ok, via = chaba_event.send(payload)
        print(f"  gate: chaba-event {'ok via ' + via if ok else 'failed: ' + via}",
              file=sys.stderr)
    except Exception as exc:
        print(f"  gate: chaba-event failed: {exc}", file=sys.stderr)


def maybe_emit(state: dict, key: str, min_gap_s: float, payload: dict) -> None:
    """Emit payload at most once per min_gap_s per key (state file)."""
    import time
    last = float((state.get("emit_at") or {}).get(key, 0) or 0)
    if time.time() - last < min_gap_s:
        print(f"  gate: chaba-event '{key}' throttled")
        return
    emit_event(payload)
    state.setdefault("emit_at", {})[key] = time.time()
    _save_state(state)


def smoke_scenarios(scenarios_dir: Path) -> list[str]:
    """Smoke-tier scenario names — flat name:/tier: fields, no yaml dep."""
    names = []
    try:
        paths = sorted(scenarios_dir.glob("*.yaml"))
    except OSError:
        return names
    for p in paths:
        try:
            text = p.read_text()
        except OSError:
            continue
        tier = RX_YAML_TIER.search(text)
        if (tier.group(1) if tier else "full") != "smoke":
            continue
        name = RX_YAML_NAME.search(text)
        names.append(name.group(1) if name else p.stem)
    return names


def report_skip(mddb: str, scenario: str, status: str, tier: str,
                reason: str) -> bool:
    """Same doc shape as scenario-report.py._report — lab-results reads
    it identically, so a gated run still shows in the status matrix."""
    now = datetime.datetime.now()
    key = f"report/{scenario}-{now.strftime('%Y%m%d-%H%M%S')}"
    meta = {
        "kind": ["report"], "subject": ["scenario-live"],
        "scenario": [scenario], "status": [status], "tier": [tier],
        "runs": ["0"], "gated": [reason],
        "last_verified": [now.date().isoformat()],
        "valid_until": [
            (now.date() + datetime.timedelta(days=14)).isoformat()],
    }
    body = (f"# {scenario} — {status}\n\nSkipped by scenario-provider-gate "
            f"({reason}) — provider probed dead before the run; zero "
            f"sessions opened. See `report/smoke-gate` for the gate "
            f"verdict trail.\n")
    return _post(f"{mddb}/add", {
        "collection": COLLECTION, "key": key, "lang": "en",
        "contentMd": body, "meta": meta, "ttl": REPORT_TTL_S})


def report_gate_summary(mddb: str, verdict: dict, names: list[str]) -> bool:
    now = datetime.datetime.now()
    key = f"report/smoke-gate-{now.strftime('%Y%m%d-%H%M%S')}"
    meta = {
        "kind": ["report"], "subject": ["scenario-gate"],
        "scenario": ["smoke-gate"], "status": [verdict["status"]],
        "tier": ["smoke"], "runs": ["0"],
        "last_verified": [now.date().isoformat()],
        "valid_until": [
            (now.date() + datetime.timedelta(days=14)).isoformat()],
    }
    lines = [f"# smoke-gate — {verdict['status']}", "",
             f"- verdict: **{verdict['status']}** — {verdict['reason']}"]
    for k, v in verdict.get("checks", {}).items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append(f"Recorded `skip` on {len(names)} smoke scenarios.")
    return _post(f"{mddb}/add", {
        "collection": COLLECTION, "key": key, "lang": "en",
        "contentMd": "\n".join(lines), "meta": meta, "ttl": REPORT_TTL_S})


def check_unit_active(unit: str) -> tuple[bool, str]:
    out = _sh(["systemctl", "--user", "is-active", unit], timeout=8).strip()
    return out == "active", out or "unknown"


def check_free_lane(unit: str) -> tuple[str, str]:
    """(verdict, detail) — 'ok' | 'paid-lane' | 'unknown'.
    Compares sha256 of the unit's GEMINI_API_KEY against the FREE/PAID
    marks in gemini-keys.env — values are never printed."""
    env_file = SECRETS / f"{unit}.env"
    lanes = SECRETS / "gemini-keys.env"
    live_key = _env_value(env_file, "GEMINI_API_KEY")
    if not live_key:
        return "unknown", f"no GEMINI_API_KEY in {env_file.name}"
    free = _env_value(lanes, "GEMINI_API_KEY_FREE")
    paid = _env_value(lanes, "GEMINI_API_KEY_PAID")
    if not (free or paid):
        return "unknown", f"no GEMINI_API_KEY_FREE/PAID in {lanes.name}"
    live_sha = _sha(live_key)
    if free and live_sha == _sha(free):
        return "ok", "live key = free lane"
    if paid and live_sha == _sha(paid):
        if free:
            return "paid-lane", ("live key is the PAID lane while a free "
                                 "lane exists — refusing to bill the suite")
        return "ok", "live key = paid lane, no free lane configured"
    return "unknown", "live key matches neither FREE nor PAID mark"


def check_quota(unit: str, window_min: int) -> tuple[str, dict]:
    """(verdict, detail) — 'ok' | 'quota-dead' | 'quota-suspect'.
    quota-suspect = repeated connect failures without a quota stamp —
    still gated: a storming retry loop is exactly what we must not feed."""
    lines = _journal(unit, f"-{window_min} min")
    last_quota = last_fail = last_ok = -1
    n_quota = n_fail = n_ok = 0
    for i, line in enumerate(lines):
        if RX_QUOTA.search(line):
            n_quota += 1
            last_quota = i
        if RX_CONN_FAIL.search(line):
            n_fail += 1
            last_fail = i
        if RX_OK.search(line):
            n_ok += 1
            last_ok = i
    detail = {"window_min": window_min, "quota_lines": n_quota,
              "provider_connect_fails": n_fail, "healthy_markers": n_ok,
              "journal_lines": len(lines)}
    if n_quota and last_quota > last_ok:
        return "quota-dead", detail
    if n_fail >= 5 and last_fail > last_ok:
        # persistent connect failure without a quota string — treat as an
        # upstream outage; the retry storm burns attempts either way.
        return "quota-dead", {**detail, "note": "connect-fail streak, "
                              "no success marker after last failure"}
    return "ok", detail


def churn_scan(units: list[str], state: dict) -> dict[str, dict]:
    """ws connects + upstream reconnects per unit over the last hour;
    >50 ws connects/hour -> throttled chaba-event warn (acceptance #4)."""
    out = {}
    for unit in units:
        lines = _journal(unit, "-60 min")
        ws = sum(1 for l in lines if RX_WS_CONNECT.search(l))
        up = sum(1 for l in lines if RX_UPSTREAM.search(l))
        out[unit] = {"ws_connects": ws, "upstream_reconnects": up}
        if ws > CHURN_WARN_PER_HOUR:
            maybe_emit(state, f"churn:{unit}", CHURN_WARN_MIN_S, {
                "title": f"reconnect churn: {unit}",
                "category": "ada-scenario",
                "source": "scenario-provider-gate",
                "severity": "warn",
                "body": (f"{unit}: {ws} ws connects/hour "
                         f"(>{CHURN_WARN_PER_HOUR}), "
                         f"{up} upstream reconnects/hour — a retry-storm "
                         "burns billed Live connects; check client "
                         "reconnect loops before the quota does"),
                "requires_response": False,
                "confidence": 0.9,
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--unit", default="ada-ha-tony",
                    help="backend unit the smoke tier targets")
    ap.add_argument("--window", type=int, default=70,
                    help="journal window (minutes) for the quota probe")
    ap.add_argument("--tier", default="smoke")
    ap.add_argument("--scenarios-dir", type=Path, default=SCENARIOS_DIR)
    ap.add_argument("--env-file", type=Path,
                    default=SECRETS / "ada-ha-tony.env",
                    help="dotenv carrying MDDB_OPS_URL (never logged)")
    ap.add_argument("--churn-units", default=",".join(DEFAULT_UNITS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true",
                    help="write the gate summary doc even on verdict ok")
    ap.add_argument("--daily-budget", type=int, default=0,
                    help="max allowed runs per UTC day; 0 = unlimited. The "
                         "incremental ratchet — raise it as the canary "
                         "proves headroom (gemini-live-canary ledger).")
    args = ap.parse_args()

    # MDDB_OPS_URL lives in the instance env file — [Service] only exports
    # MDDB_BASE_URL to ExecCondition, so read the ops URL ourselves.
    ops = _env_value(args.env_file, "MDDB_OPS_URL")
    if ops and "MDDB_OPS_URL" not in os.environ:
        os.environ["MDDB_OPS_URL"] = ops

    state = _load_state()
    checks: dict[str, str] = {}

    active, active_detail = check_unit_active(args.unit)
    checks["unit_active"] = f"{args.unit}={active_detail}"

    lane, lane_detail = check_free_lane(args.unit)
    checks["free_lane"] = lane_detail

    quota, quota_detail = check_quota(args.unit, args.window)
    checks["quota_probe"] = json.dumps(quota_detail)

    churn = churn_scan(
        [u.strip() for u in args.churn_units.split(",") if u.strip()],
        state)
    checks["churn"] = "; ".join(
        f"{u}: {c['ws_connects']}ws/{c['upstream_reconnects']}up"
        for u, c in churn.items())

    if not active:
        status, reason = "infra", f"target unit {args.unit} is {active_detail}"
    elif lane in ("paid-lane", "unknown"):
        # fail-closed: an unmarked key may be a NEW paid key not yet added
        # to gemini-keys.env — a QA skip costs nothing, a wrong guess burns
        # credit (2026-10-12: the hole was unknown->ok).
        status, reason = "paid-lane", (
            f"unmarked/PAID lane key — {lane_detail}")
    elif quota == "quota-dead":
        status, reason = "quota-dead", (
            f"provider dunning in last {args.window}min "
            f"({json.dumps(quota_detail)})")
    elif args.daily_budget > 0:
        today = datetime.datetime.now(datetime.timezone.utc
                                      ).strftime("%Y-%m-%d")
        runs = [d for d in state.get("allowed_runs", []) if d == today]
        if len(runs) >= args.daily_budget:
            status, reason = "budget", (
                f"daily budget {args.daily_budget} run(s) reached")
        else:
            status, reason = "ok", "provider healthy — run proceeds"
    else:
        status, reason = "ok", "provider healthy — run proceeds"

    print(f"scenario-provider-gate: {status} — {reason}")
    for k, v in checks.items():
        print(f"  {k}: {v}")

    if status == "ok" and not args.report:
        if args.daily_budget > 0 and not args.dry_run:
            allowed = state.setdefault("allowed_runs", [])
            allowed.append(today)
            state["allowed_runs"] = allowed[-64:]
            _save_state(state)
        return 0

    # report path — skip verdicts always; 'ok' only under --report
    names = smoke_scenarios(args.scenarios_dir)
    report_status = REPORT_STATUSES.get(status, status if status != "ok"
                                        else "pass")
    verdict = {"status": report_status if status != "ok" else "ok",
               "reason": reason, "checks": checks}
    if not args.dry_run:
        mddb = _mddb()
        if status != "ok":
            written = 0
            for name in names:
                if report_skip(mddb, name, report_status, args.tier, reason):
                    written += 1
            report_gate_summary(mddb, verdict, names)
            print(f"  gate: recorded {report_status} on "
                  f"{written}/{len(names)} scenarios -> {mddb}")
            maybe_emit(state, f"gate:{status}", GATE_WARN_MIN_S, {
                "title": f"scenario smoke gated: {status}",
                "category": "ada-scenario",
                "source": "scenario-provider-gate",
                "severity": "warn",
                "body": (f"hourly smoke tier skipped — {reason}. "
                         f"{len(names)} scenarios recorded "
                         f"{report_status}, zero sessions opened."),
                "requires_response": False,
                "confidence": 0.9,
            })
        elif args.report:
            report_gate_summary(mddb, verdict, names)
    if status == "ok" and args.daily_budget > 0 and not args.dry_run:
        allowed = state.setdefault("allowed_runs", [])
        allowed.append(today)
        state["allowed_runs"] = allowed[-64:]
        _save_state(state)

    return 0 if status == "ok" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # fail-closed, but loud
        print(f"scenario-provider-gate: INTERNAL ERROR {exc} — "
              "gating the run (fail-closed)", file=sys.stderr)
        emit_event({
            "title": "scenario-provider-gate broke",
            "category": "ada-scenario",
            "source": "scenario-provider-gate",
            "severity": "error",
            "body": f"gate crashed: {exc} — smoke tier gated fail-closed",
            "requires_response": False,
            "confidence": 0.5,
        })
        raise SystemExit(1)
