#!/usr/bin/env python3
"""waiting_cards — the hands-off waiting-card gate (KNB-0928).

Canonical implementation of the `waiting_cards:` contract in
docs/ssot/infrastructure/ssot.devin-autonomy.yml. It does NOT replace
kanban-dispatch / runner-agent / kanban-act — it names which cards those
may touch unattended, what must be true first (eligibility + preflight),
and when they must stop safely.

Queue EXECUTION (claim -> run -> finish) and auto-CLOSE (kanban-act's
review-column drain) are separate concerns: this module gates execution;
kanban-act.py keeps gating close. A card may be eligible to RUN and still
require human close (review_kind: decide, no auto_done_when).

Recoverability classes (worst data class the card can touch wins):
  R0  rebuildable caches/reports/derived data — failure loses nothing
  R1  git-tracked worktree — recoverable iff clean or merged
  R2  stateful DB/service data — needs verified backup + integrity +
      no active writer
  R3  secrets/identity/external accounts — NEVER autonomous
  R4  production/destructive/deploy — human-gated always

Usage:
  waiting_cards.py --evaluate <card.yml|card-id> [--json]
  waiting_cards.py --board            # verdict table for all queued cards
  waiting_cards.py --preflight        # probe this host once, print JSON

Env:
  KANBAN_WAITING_GATE   off|warn|strict — claim-mode default for callers
                        that consult this module (kanban-dispatch reads
                        its own KANBAN_WAITING_GATE; 'warn' logs but
                        still claims, 'strict' defers ineligible cards,
                        R3/R4 are deferred in EVERY mode)
  WAITING_DISK_MIN_MB   disk headroom floor (default 2048)
  WAITING_BACKUP_PROOF  path to a freshness stamp for R2 cards — when
                        unset, R2 cards defer with 'no backup proof
                        configured' (fail closed)
  KANBAN_PUBLISH_API    board-api base for Telegram summaries
                        (default http://127.0.0.1:8787 — loopback on the
                        writer host; remote callers pass their
                        RUNNER_API tailnet base)
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
import urllib.request
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
POLICY_FILE = REPO / "docs/ssot/infrastructure/ssot.devin-autonomy.yml"
CARDS_DIR = REPO / "docs/ssot/kanban/cards"

EXEC_TYPES = {"dispatch", "script", "container"}
TIER_ORDER = {"t0": 0, "t1": 1, "t2": 2, "t3": 3, "t4": 4}
RECOVERABILITY = ("R0", "R1", "R2", "R3", "R4")
NEVER_AUTONOMOUS = {"R3", "R4"}

DISK_MIN_MB = int(os.environ.get("WAITING_DISK_MIN_MB", "2048"))
BACKUP_PROOF = os.environ.get("WAITING_BACKUP_PROOF", "")
PUBLISH_API = os.environ.get(
    "KANBAN_PUBLISH_API", "http://127.0.0.1:8787").rstrip("/")
KILL_SWITCH = "/tmp/no-kanban-dispatch"
DEPLOY_LOCK = "/tmp/pfg-deploy.lock"


# ---------- policy + card fields ----------

@lru_cache(maxsize=4)
def load_policy() -> dict:
    """waiting_cards + dispatch sections of the autonomy contract."""
    try:
        p = yaml.safe_load(POLICY_FILE.read_text()) or {}
    except Exception:
        return {}
    return {"waiting_cards": p.get("waiting_cards") or {},
            "dispatch": p.get("dispatch") or {}}


def _action(card: dict) -> dict:
    return card.get("action") or {}


def autonomy_tier(card: dict) -> str:
    return str(card.get("autonomy") or "t1").lower()


def recoverability(card: dict) -> str:
    """Declared R-class, upper-cased; '' when undeclared. Accepts the
    top-level card field (schema-documented) and an action-level alias."""
    raw = (card.get("recoverability")
           or _action(card).get("recoverability") or "")
    r = str(raw).strip().upper()
    return r if r in RECOVERABILITY else ""


def declares_artifact(card: dict) -> bool:
    a = _action(card)
    return bool(a.get("artifact") or card.get("report")
                or (card.get("pipeline") or {}).get("goals"))


def declares_verifier(card: dict) -> bool:
    a = _action(card)
    return bool(card.get("auto_done_when") or a.get("verifier")
                or a.get("verify")
                or (card.get("pipeline") or {}).get("goals"))


def open_requests(card: dict) -> list:
    """Unanswered requests/ask — same semantics as kanban-act's gate."""
    out = []
    for r in card.get("requests") or []:
        if isinstance(r, dict) and (r.get("status") or "open") != "answered":
            out.append(r.get("id") or str(r.get("ask", "?"))[:30])
    ask = card.get("ask") or {}
    if (isinstance(ask, dict) and ask.get("question")
            and (ask.get("status") or "open") != "answered"):
        out.append("ask")
    return out


def target_host(card: dict) -> str:
    """Explicit execution host — action.target_host wins, action.host
    (the legacy pin) counts; '' means 'any live runner'."""
    a = _action(card)
    return str(a.get("target_host") or a.get("host") or "").strip()


# ---------- preflight probes ----------

def disk_free_mb(path: str | Path) -> float:
    st = shutil.disk_usage(str(path))
    return st.free / (1024 * 1024)


def lock_held(path: str) -> bool:
    """True when another process holds an flock on `path`."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def preflight(card: dict, env: dict | None = None) -> list:
    """Pre-claim environment checks -> list of failure strings.

    env keys (all optional; missing = check skipped, EXCEPT the ones a
    caller is expected to supply for a real claim):
      kill_switch    bool   /tmp/no-kanban-dispatch present
      deploy_lock    bool   /tmp/pfg-deploy.lock held by another unit
      disk_free_mb   float  free space on the work path
      disk_path      str    path disk_free_mb was measured on
      disk_min_mb    float  floor (default WAITING_DISK_MIN_MB)
      claimed        int    in-flight claims on this runner
      cap            int    runner cap
      backup_fresh   bool   R2 only — verified backup exists
      backup_proof   str    evidence string recorded with the verdict
      heartbeat_age_s float age of the runner/timer heartbeat
      heartbeat_max_s float freshness ceiling
    """
    env = env or {}
    fails = []
    if env.get("kill_switch"):
        fails.append(f"kill switch {KILL_SWITCH} present")
    if env.get("deploy_lock"):
        fails.append(f"deploy lock {DEPLOY_LOCK} held")
    df = env.get("disk_free_mb")
    if df is not None:
        floor = float(env.get("disk_min_mb") or DISK_MIN_MB)
        if df < floor:
            fails.append(f"disk headroom {df:.0f}MB < {floor:.0f}MB floor"
                         + (f" on {env['disk_path']}"
                            if env.get("disk_path") else ""))
    claimed = env.get("claimed")
    cap = env.get("cap")
    if claimed is not None and cap is not None and int(claimed) >= int(cap):
        fails.append(f"queue capacity {claimed}/{cap} reached")
    rec = recoverability(card)
    if rec == "R2":
        fresh = env.get("backup_fresh")
        proof = env.get("backup_proof") or BACKUP_PROOF
        if fresh is False or (fresh is not True and not proof):
            fails.append("R2 card: no verified backup proof"
                         + (f" ({proof})" if proof else
                            " (set WAITING_BACKUP_PROOF or pass "
                            "backup_fresh=True)"))
    hb = env.get("heartbeat_age_s")
    hb_max = env.get("heartbeat_max_s")
    if hb is not None and hb_max is not None and hb > hb_max:
        fails.append(f"stale heartbeat {hb:.0f}s > {hb_max:.0f}s")
    return fails


def local_env(host: str = "", claimed: int | None = None,
              cap: int | None = None, path: str | Path | None = None,
              backup_fresh: bool | None = None,
              heartbeat_age_s: float | None = None,
              heartbeat_max_s: float | None = None) -> dict:
    """Probe THIS host once — the env dict preflight() consumes."""
    p = Path(path) if path else Path.home()
    return {
        "host": host,
        "kill_switch": Path(KILL_SWITCH).exists(),
        "deploy_lock": lock_held(DEPLOY_LOCK),
        "disk_free_mb": round(disk_free_mb(p), 1),
        "disk_path": str(p),
        "disk_min_mb": DISK_MIN_MB,
        "claimed": claimed,
        "cap": cap,
        "backup_fresh": backup_fresh,
        "backup_proof": BACKUP_PROOF,
        "heartbeat_age_s": heartbeat_age_s,
        "heartbeat_max_s": heartbeat_max_s,
    }


# ---------- eligibility verdict ----------

def evaluate(card: dict, env: dict | None = None,
             push_probe=None) -> dict:
    """Full waiting-card verdict for one card.

    Returns {eligible, never, recoverability, reasons[], checks{}}.
    `never` marks the hard floor (R3/R4 declared — backups do not apply);
    `reasons` lists every unmet requirement. `push_probe(repo)->bool`
    is injected by the caller (runner-agent/kanban-dispatch own the
    push-credential caches); when absent the check is skipped.
    """
    pol = load_policy()
    wc = pol.get("waiting_cards") or {}
    disp = pol.get("dispatch") or {}
    env = env if env is not None else local_env()

    reasons: list = []
    checks: dict = {}
    a = _action(card)
    cid = card.get("id") or "?"

    # 1. executor exists — unattended paths serve these types only
    atype = str(a.get("type") or "dispatch")
    checks["action.type"] = atype in EXEC_TYPES
    if not checks["action.type"]:
        reasons.append(f"action.type={atype!r} has no unattended executor")

    # 2. explicit target host (spec: runners may process only cards with
    #    explicit target_host — a fleet-any card is a scheduling decision,
    #    not an unattended-safe one)
    th = target_host(card)
    checks["target_host"] = bool(th)
    if not th:
        reasons.append("no explicit action.target_host/host")

    # 3. autonomy ceiling
    tier = autonomy_tier(card)
    max_tier = TIER_ORDER.get(str(disp.get("max_autonomy") or "t3"), 3)
    ctier = TIER_ORDER.get(tier, -1)
    checks["autonomy"] = ctier <= max_tier
    if not checks["autonomy"]:
        reasons.append(f"autonomy {tier} exceeds dispatch.max_autonomy")

    # 4. artifact + verifier declared
    checks["artifact"] = declares_artifact(card)
    checks["verifier"] = declares_verifier(card)
    if not checks["artifact"]:
        reasons.append("no declared artifact (action.artifact/report/"
                       "pipeline.goals)")
    if not checks["verifier"]:
        reasons.append("no declared verifier (auto_done_when/action."
                       "verifier/pipeline.goals)")

    # 5. no open Tony request
    reqs = open_requests(card)
    checks["no_open_requests"] = not reqs
    if reqs:
        reasons.append(f"open request(s): {', '.join(reqs)}")

    # 6. recoverability class declared
    rec = recoverability(card)
    checks["recoverability_declared"] = bool(rec)
    if not rec:
        reasons.append("recoverability class undeclared (R0-R4)")
    elif rec in NEVER_AUTONOMOUS:
        reasons.append(f"recoverability {rec} — never autonomous "
                       "(secrets/accounts/prod are human-gated)")

    # 7. preflight
    pf = preflight(card, env)
    checks["preflight"] = not pf
    reasons.extend(pf)

    # 8. push credentials for the card's repo (dispatch cards only —
    #    script/container executors may not push)
    repo = str(a.get("repo") or "")
    if atype == "dispatch" and repo and push_probe is not None:
        ok = bool(push_probe(repo))
        checks["push_credentials"] = ok
        if not ok:
            reasons.append(f"no push credentials proven for repo {repo!r}")

    never = rec in NEVER_AUTONOMOUS
    return {"id": cid, "eligible": not reasons, "never": never,
            "recoverability": rec or None, "autonomy": tier,
            "reasons": reasons, "checks": checks}


# ---------- Telegram / publication summaries ----------

def publish(api_base: str, card_id: str, kind: str, title: str,
            body: str = "", source: str = "waiting-cards",
            confidence: str = "observed",
            visibility: str = "members", timeout: int = 10) -> bool:
    """POST a canonical PublicationEvent to board-api /publish — the
    fan-out (Telegram sink, board comms audit, json ledger) lives
    server-side with its noise policy, so callers never hold the TG
    relay address. milestone/alert reach Telegram; progress does not
    (heartbeat noise policy). Never raises."""
    if kind not in ("milestone", "alert", "progress", "report",
                    "lesson", "news"):
        return False
    if not card_id:
        return False
    ev = {"kind": kind, "title": title[:240], "body": body[:2000],
          "source": source, "confidence": confidence,
          "visibility": visibility, "card": card_id,
          "meta": {"lane": "unattended"}}
    try:
        req = urllib.request.Request(
            f"{api_base.rstrip('/')}/publish",
            data=json.dumps(ev).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def notify_lifecycle(api_base: str, card_id: str, event: str,
                     detail: str = "", host: str = "") -> bool:
    """start/finish/fail/stalled -> Telegram via /publish.

    event: start|finish|fail|stalled. finish->milestone, fail/stalled->
    alert (telegram-routed kinds), start->progress (audited on the card
    + ledger but NOT telegram — a claim is a heartbeat, not news)."""
    kind = {"start": "progress", "finish": "milestone",
            "fail": "alert", "stalled": "alert"}.get(event)
    if not kind:
        return False
    where = f" on {host}" if host else ""
    title = f"card {event}: {card_id}{where}"
    if detail:
        title = f"{title} — {detail[:120]}"
    return publish(api_base, card_id, kind, title,
                   body=detail, source="runner-lifecycle")


# ---------- CLI ----------

def _load_card(path: Path) -> dict:
    c = yaml.safe_load(path.read_text()) or {}
    c.setdefault("id", path.stem)
    return c


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--evaluate", metavar="CARD",
                    help="card id or path to a card yml")
    ap.add_argument("--board", action="store_true",
                    help="verdict table for every card with a queued/"
                         "starting action")
    ap.add_argument("--preflight", action="store_true",
                    help="probe this host and print the env JSON")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--host", default="",
                    help="runner identity recorded in the verdict")
    args = ap.parse_args()

    if args.preflight:
        print(json.dumps(local_env(host=args.host), indent=2))
        return 0

    if args.board:
        verdicts = []
        for f in sorted(CARDS_DIR.glob("*.yml")):
            try:
                c = _load_card(f)
            except Exception:
                continue
            st = str((_action(c).get("status") or "")).lower()
            if st not in ("queued", "starting"):
                continue
            verdicts.append(evaluate(c, env=local_env(host=args.host)))
        if args.json:
            print(json.dumps(verdicts, indent=2))
        else:
            for v in verdicts:
                mark = "OK " if v["eligible"] else (
                    "NEVER" if v["never"] else "HOLD")
                print(f"[{mark}] {v['id']} "
                      f"(R{v['recoverability'] or '?'}, "
                      f"{v['autonomy']})"
                      + ("" if v["eligible"]
                         else " — " + "; ".join(v["reasons"])))
            n_ok = sum(1 for v in verdicts if v["eligible"])
            print(f"{n_ok}/{len(verdicts)} queued cards eligible")
        return 0

    if args.evaluate:
        p = Path(args.evaluate)
        if not p.suffix:
            p = CARDS_DIR / f"{args.evaluate}.yml"
        card = _load_card(p)
        v = evaluate(card, env=local_env(host=args.host))
        if args.json:
            print(json.dumps(v, indent=2))
        else:
            print(f"{v['id']}: {'ELIGIBLE' if v['eligible'] else 'HOLD'}"
                  f" (recoverability={v['recoverability']}, "
                  f"autonomy={v['autonomy']}, never={v['never']})")
            for r in v["reasons"]:
                print(f"  - {r}")
            print("  checks: " + json.dumps(v["checks"], sort_keys=True))
        return 0 if v["eligible"] or not v["never"] else 2

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
