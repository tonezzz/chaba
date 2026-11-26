#!/usr/bin/env python3
"""approve-ask — raise a board request whose options carry declared
actions, i.e. the canonical "menu that can approve" emitter (card
ada-dispatch-approve-button).

Tony's flow: Ada (or a producer) raises the ask -> Tony clicks the
option on the board -> /respond executes the declared action in the
same write (_exec_option_action) -> kanban-dispatch claims the queued
card -> verified/unverified verdict reaches Tony via /publish ->
merge-sweep auto-closes verified cards. No answer-sweep tick wait —
the click IS the approval.

Default menu is the dispatch-approve pair:

    approve — Approve -> queue dispatch     (action: queue)
    hold    — Hold    -> do not dispatch    (action: hold)

answer-sweep stays the backstop: if /respond defers (live claim,
guard refusal) the request is left unexecuted and the sweep's normal
triage owns it — same outcome, ~15min later.

Usage:
    approve-ask.py <card-id> "<ask text>"
    approve-ask.py <card-id> "Retry the failed run?" --approve-action retry
    approve-ask.py <card-id> "Deploy?" --extra-option 'close|Close — mark done|close'
    approve-ask.py <card-id> "Pick one" --options-json '[{"id":"a","label":"A","action":"queue"},...]'
    approve-ask.py <card-id> "Approve?" --suggested approve

Env: BOARD_API (default: the tailnet board-api), same as every other
board writer. --dry-run prints the payload without posting.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import dispatch_repos as dr
    API_DEFAULT = dr.board_api_base()
except Exception:
    API_DEFAULT = (os.environ.get("BOARD_API")
                   or "https://idc03.taila0626a.ts.net:10000").rstrip("/")

# the menu Ada/emitters get for free — approve executes the dispatch
# transition, hold is the recorded "not now". Option labels double as
# the answer text, so keep them self-describing.
APPROVE_OPTS = [
    {"id": "approve", "label": "Approve — queue dispatch",
     "action": "queue"},
    {"id": "hold", "label": "Hold — do not dispatch",
     "action": "hold"},
]

ACTIONS = {"queue", "retry", "close", "hold", "none"}


def parse_extra(spec: str) -> dict:
    """'id|label|action' -> option dict."""
    parts = [p.strip() for p in spec.split("|")]
    if len(parts) != 3 or not all(parts):
        raise argparse.ArgumentTypeError(
            "extra-option needs 'id|label|action'")
    oid, label, act = parts
    if act not in ACTIONS:
        raise argparse.ArgumentTypeError(
            f"action must be one of {sorted(ACTIONS)} (got {act!r})")
    return {"id": oid, "label": label, "action": act}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="raise a click-approvable board request "
                    "(options carry declared actions)")
    ap.add_argument("card", help="kanban card id")
    ap.add_argument("ask", help="question text shown on the board")
    ap.add_argument("--request-id", default="",
                    help="default: approve-<card>")
    ap.add_argument("--approve-action", default="queue",
                    choices=sorted(ACTIONS - {"none"}),
                    help="what the Approve option does (default queue)")
    ap.add_argument("--extra-option", action="append", default=[],
                    type=parse_extra, metavar="ID|LABEL|ACTION",
                    help="add a menu option; repeatable")
    ap.add_argument("--options-json", default="",
                    help="full custom options list (JSON array of "
                         "strings/dicts) — replaces the default menu")
    ap.add_argument("--suggested", default="",
                    help="option id/label marked as the default")
    ap.add_argument("--to", default="tony")
    ap.add_argument("--from", dest="frm", default="ada",
                    choices=["devin", "ada", "chaba", "tony"])
    ap.add_argument("--api", default=API_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.options_json:
        options = json.loads(args.options_json)
        if not isinstance(options, list) or not options:
            ap.error("--options-json must be a non-empty JSON array")
    else:
        options = [dict(o) for o in APPROVE_OPTS]
        options[0]["action"] = args.approve_action
        options[0]["label"] = f"Approve — {args.approve_action} dispatch"
        options.extend(args.extra_option)

    rid = args.request_id or f"approve-{args.card}"
    body = {"id": args.card, "from": args.frm, "to": args.to,
            "request_id": rid, "ask": args.ask, "options": options}
    if args.suggested:
        body["suggested"] = args.suggested

    if args.dry_run:
        print(json.dumps(body, indent=1))
        return 0

    req = urllib.request.Request(
        f"{args.api.rstrip('/')}/request",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        if e.code == 400 and "duplicate request id" in text:
            # emitters get called on every pass — an existing ask IS the
            # desired state, not an error
            print(f"request {rid} already raised on {args.card}")
            return 0
        print(f"board-api {e.code}: {text[:400]}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"board-api unreachable: {e}", file=sys.stderr)
        return 1
    print(out.get("msg") or out.get("result") or json.dumps(out)[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
