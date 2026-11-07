#!/usr/bin/env python3
"""deploy-preflight — the human-gated deploy stage for merged cards.

Card contract (KNB-1090): a card carries a top-level `deploy:` block:

    deploy:
      target: ada-voice-prod     # key into DEPLOY_TARGETS below

Lifecycle (card YAML mutated under /tmp/board-api.lock on the served
checkout; comms/requests go through board-api HTTP so notify works;
deploy execution happens OUTSIDE the lock — it can run for minutes):

  review|done + action.status=done + deploy.target known
    -> deploy.status=preflight, evidence collected, request raised
       (options: approve / hold / abort — Tony's gate, R4 human-gated)
  request answered approve
    -> run the registry's deploy command on its host, then verify the
       declared health surface; deploy.status=deployed|failed + comms
  request answered hold|abort|unparsed
    -> deploy.status=held, comms, never re-raised
  unanswered
    -> waits (request-sweep escalates after 12h as usual)

Fail-closed rules:
  - target must exist in DEPLOY_TARGETS — a card can never supply a
    command, host, or URL; the registry owns all of that.
  - autonomy:t4 cards are never touched.
  - deploy runs at most once per card; failed deploys stamp
    deploy.failed_at and do not loop.
  - verify requires BOTH producer proof (command exit 0) and consumer
    proof (verify_url returns ok) — verify-by-surface rule.

Usage: deploy-preflight.py [--dry-run]
Env:   CHABA_REPO (served checkout), BOARD_API (default 127.0.0.1:8787),
       DEPLOY_PREFLIGHT_SSH (default "ssh -o BatchMode=yes"),
       DEPLOY_TIMEOUT_S (default 1200).
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

REPO = Path(os.environ.get(
    "CHABA_REPO", str(Path(__file__).resolve().parents[2])))
CARD_DIR = REPO / "docs" / "ssot" / "kanban" / "cards"
LOCK = Path("/tmp/board-api.lock")
API = os.environ.get("BOARD_API", "http://127.0.0.1:8787")
RUN_LOCK = Path("/tmp/deploy-preflight.lock")
SSH = os.environ.get("DEPLOY_PREFLIGHT_SSH", "ssh -o BatchMode=yes")
DEPLOY_TIMEOUT = int(os.environ.get("DEPLOY_TIMEOUT_S", "1200"))

# Deploy target registry — the ONLY deployable surfaces. A card selects
# by name; it cannot inject commands, hosts, or URLs.
DEPLOY_TARGETS = {
    "ada-voice-prod": {
        "host": "idc03",
        "repo": "ada-voice",
        # deploy checkout on the target host — deploy-ada.sh itself does
        # the ff-merge + gates + restart; we only invoke it
        "checkout": "~/CascadeProjects/ada-voice",
        "command": ["~/.local/bin/deploy-ada.sh"],
        # ada-ha-tony health surface (tailscale serve -> 127.0.0.1:8002)
        "verify_url": "http://127.0.0.1:8002/api/health",
        "verify_ok_key": "ok",
    },
}

REQUEST_OPTS = [
    "approve — run the deploy now",
    "hold — keep merged, do not deploy",
    "abort — do not deploy",
]


def now() -> str:
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=7))).strftime(
        "%Y-%m-%d %H:%M")


def load(p: Path) -> dict:
    return yaml.safe_load(p.read_text()) or {}


def save(p: Path, card: dict) -> None:
    card["updated"] = now()
    p.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False))


def api_post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def comms(card_id: str, text: str) -> None:
    try:
        api_post("/comment", {"id": card_id, "from": "chaba",
                              "text": text[:1500]})
    except Exception as e:
        print(f"comms failed for {card_id}: {e}", file=sys.stderr)


def find_merge_sha(repo_path: Path, cid: str) -> str | None:
    """Latest merge on the default branch whose message names the card id
    (dispatch close-out merges --no-ff branches dispatch/<cid>-<tid>)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_path), "log", "--merges",
             "--format=%H %s", "-40"],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    for line in (r.stdout or "").splitlines():
        if cid in line:
            return line.split()[0]
    return None


def diff_stat(repo_path: Path, sha: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_path), "show", "--stat", "--format=",
             sha], capture_output=True, text=True, timeout=30)
        lines = [l for l in (r.stdout or "").splitlines() if l.strip()]
        return "; ".join(lines[-3:])[:300] or "?"
    except Exception:
        return "?"


def preflight_evidence(card: dict, cid: str, dep: dict) -> dict:
    tgt = DEPLOY_TARGETS[dep["target"]]
    checkout = Path(tgt["checkout"]).expanduser()
    sha = find_merge_sha(checkout, cid)
    return {
        "at": now(),
        "merge_sha": sha,
        "files": diff_stat(checkout, sha) if sha else "?",
        "tests": "see card comms (close-out gate)",
        "comms_tail": [str(m.get("text"))[:120]
                       for m in (card.get("comms") or [])[-6:]],
    }


def run_deploy(dep: dict) -> dict:
    tgt = DEPLOY_TARGETS[dep["target"]]
    cmd = " ".join(tgt["command"])
    # target host == this host -> run locally under this user manager;
    # otherwise ssh. The registry command is a fixed argv, never card input.
    if tgt["host"] == os.uname().nodename:
        full = [os.path.expanduser(c) for c in tgt["command"]]
    else:
        full = [*SSH.split(), tgt["host"], cmd]
    try:
        r = subprocess.run(full, capture_output=True, text=True,
                           timeout=DEPLOY_TIMEOUT)
        tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        return {"ok": r.returncode == 0, "rc": r.returncode,
                "output_tail": tail[-15:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": None,
                "output_tail": [f"timeout after {DEPLOY_TIMEOUT}s"]}
    except Exception as e:
        return {"ok": False, "rc": None,
                "output_tail": [f"{type(e).__name__}: {e}"]}


def verify_surface(tgt: dict) -> dict:
    try:
        with urllib.request.urlopen(tgt["verify_url"], timeout=15) as r:
            body = r.read().decode(errors="replace")
            ok_key = tgt.get("verify_ok_key")
            ok = r.status == 200 and (
                ok_key is None
                or f'"{ok_key}": true' in body
                or f'"{ok_key}":true' in body)
            return {"ok": ok, "status": r.status, "body_head": body[:200]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def deploy_request(card: dict, cid: str) -> dict | None:
    rid = f"deploy-{cid}"
    for r in card.get("requests") or []:
        if str(r.get("id") or "") == rid:
            return r
    return None


def raise_request(cid: str, dep: dict, ev: dict) -> None:
    tgt = DEPLOY_TARGETS[dep["target"]]
    ask = (
        f"Deploy {cid} to {dep['target']}?\n"
        f"repo: {tgt['repo']} on {tgt['host']}\n"
        f"command: {' '.join(tgt['command'])}\n"
        f"rollback: git revert the merge commit on {tgt['repo']} "
        f"({ev.get('merge_sha') or 'see comms'})\n"
        f"verify: GET {tgt['verify_url']} must return ok\n\n"
        f"Preflight: merge={ev.get('merge_sha') or '?'} "
        f"files={ev.get('files', '?')} tests={ev.get('tests', '?')}")
    api_post("/request", {
        "id": cid, "from": "chaba", "to": "tony",
        "request_id": f"deploy-{cid}", "ask": ask,
        "options": REQUEST_OPTS,
        # suggested must be an option string verbatim — do_request
        # rejects anything not in options[] (int 1 400'd the first live
        # raise, 2026-11-07). Default is hold.
        "suggested": REQUEST_OPTS[1],
    })


def decide(card: dict, cid: str) -> tuple[str, dict | None]:
    """Return (action, payload). Actions: skip, wait, held, preflight,
    deploy, error. File mutations are applied by caller under lock."""
    dep = card.get("deploy")
    if not isinstance(dep, dict):
        return "skip", {"why": "no-deploy-block"}
    target = str(dep.get("target") or "").strip()
    if not target:
        return "skip", {"why": "no-target"}
    if target not in DEPLOY_TARGETS:
        dep["status"] = "error"
        dep["error"] = (f"unknown deploy.target {target!r} — not in "
                        "registry")
        return "error", {"comment": dep["error"]}
    if str(card.get("autonomy") or "") == "t4":
        return "skip", {"why": "t4"}
    if card.get("column") not in ("review", "done"):
        return "skip", {"why": f"column={card.get('column')}"}
    if (card.get("action") or {}).get("status") != "done":
        return "skip", {"why": "action-not-done"}
    st = str(dep.get("status") or "")
    if st in ("deployed", "held"):
        return "skip", {"why": st}
    if st == "failed" and dep.get("failed_at"):
        return "skip", {"why": "failed-once"}

    req = deploy_request(card, cid)
    if req is not None:
        if req.get("status") in ("answered", "closed"):
            ans = str(req.get("answer") or "").strip().lower()
        else:
            return "wait", {"why": "approval-pending"}
    else:
        ans = ""

    if not ans:
        # no open/answered request -> (re)raise approval request
        if st == "preflight":
            # status set but request missing (raise raced/lost) -> retry
            pass
        ev = preflight_evidence(card, cid, dep)
        dep["status"] = "preflight"
        dep["preflight"] = ev
        dep["request_id"] = f"deploy-{cid}"
        return "preflight", {"ev": ev, "dep": dep}

    if ans.startswith("approve"):
        return "deploy", {"dep": dep}
    # hold / abort / unparsed -> hold, never guess a deploy
    dep["status"] = "held"
    dep["held_answer"] = ans[:200] or "(empty)"
    note = ("held by Tony" if ans else "answer missing") + \
        f" ({ans[:120]}) — no deploy will run"
    return "held", {"comment": f"deploy gate: {note}"}


def finish_deploy(cid: str, dep: dict, res: dict, ver: dict) -> str:
    """Write deploy outcome back under lock; returns final status."""
    p = CARD_DIR / f"{cid}.yml"
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        card = load(p)
        d = card.get("deploy") or {}
        d["status"] = "deployed" if (res["ok"] and ver.get("ok")) \
            else "failed"
        d["deployed_at"] = now()
        if d["status"] == "failed":
            d["failed_at"] = now()
        d["deploy_rc"] = res.get("rc")
        d["verify"] = ver
        card["deploy"] = d
        save(p, card)
    out = "\n".join(res.get("output_tail") or [])
    comms(cid, f"deploy gate: {d['status'].upper()} — "
               f"rc={res.get('rc')} verify={ver.get('ok')}\n{out[-900:]}")
    return d["status"]


def main() -> int:
    dry = "--dry-run" in sys.argv
    RUN_LOCK.touch(exist_ok=True)
    with RUN_LOCK.open("w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another deploy-preflight run holds the lock")
            return 0

        # Phase 1 (lock): decide + apply file mutations, collect effects.
        effects = []   # (kind, cid, payload)
        with LOCK.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for p in sorted(CARD_DIR.glob("*.yml")):
                cid = p.stem
                try:
                    card = load(p)
                    action, pl = decide(card, cid)
                except Exception as e:
                    print(f"{cid}: decide error {e}", file=sys.stderr)
                    continue
                if action == "skip":
                    continue
                if action in ("error", "held", "preflight") and not dry:
                    save(p, card)
                if action == "error":
                    effects.append(("comment", cid, pl["comment"]))
                    effects.append(("result", cid, action))
                elif action == "held":
                    effects.append(("comment", cid, pl["comment"]))
                    effects.append(("result", cid, action))
                elif action == "preflight":
                    effects.append(("request", cid, pl))
                    effects.append(("comment", cid,
                                    "deploy gate: preflight done — "
                                    f"approval request deploy-{cid} "
                                    "raised (default hold)"))
                    effects.append(("result", cid, action))
                elif action == "deploy":
                    effects.append(("deploy", cid, pl["dep"]))
                elif action == "wait":
                    effects.append(("result", cid, action))

        # Phase 2 (no lock): HTTP effects, then deploys.
        for kind, cid, pl in effects:
            if kind == "comment":
                if not dry:
                    comms(cid, pl)
            elif kind == "request":
                if not dry:
                    try:
                        raise_request(cid, pl["dep"], pl["ev"])
                    except Exception as e:
                        # mark error under lock so next tick retries
                        p = CARD_DIR / f"{cid}.yml"
                        with LOCK.open("w") as lock:
                            fcntl.flock(lock, fcntl.LOCK_EX)
                            card = load(p)
                            d = card.get("deploy") or {}
                            d["status"] = "error"
                            d["error"] = f"request raise failed: {e}"
                            card["deploy"] = d
                            save(p, card)
                        comms(cid, f"deploy gate: could not raise "
                                   f"approval request: {e}")
            elif kind == "deploy":
                if dry:
                    print(f"{cid}: would deploy "
                          f"{pl.get('target')}")
                    continue
                tgt = DEPLOY_TARGETS[pl["target"]]
                comms(cid, f"deploy gate: approved — running "
                           f"{' '.join(tgt['command'])} on {tgt['host']}")
                res = run_deploy(pl)
                ver = (verify_surface(tgt) if res["ok"]
                       else {"ok": False, "skipped": "deploy failed"})
                final = finish_deploy(cid, pl, res, ver)
                print(f"{cid}: deploy {final}")
                continue
        for kind, cid, pl in effects:
            if kind == "result":
                print(f"{cid}: {pl if isinstance(pl, str) else pl.get('why')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
