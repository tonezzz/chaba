#!/usr/bin/env python3
"""answer-sweep — executes answered board requests.

request-sweep escalates requests nobody answered; this sweep acts on the
ones that were. An answer sits inert until someone turns it into a board
action — answered asks piled up under awaiting_action with nothing
executing them (card knb-answer-action-triage). The sweep maps
unambiguous answer verbs onto the same transitions the board buttons
perform and leaves everything else flagged for human triage.

Runs inside the kanban-sync tick (15min, chaba-kanban-sync worktree on
tony-dell) — card writes hold /tmp/board-api.lock, the tick commits.

An answer resolves through, in order:

  1. option action — when the request's options are dicts and the answer
     matches one (exact 'id — label', bare id, or bare label), an
     explicit `action: queue|retry|close|hold|none` on that option wins.
     Opt-in per-option path: the emitter declares the consequence at
     request time, the sweep executes it blindly.
  2. verb word — else the first whitespace token of the answer's head
     (text before ' — '; dict-option ids count first) is looked up in
     VERBS. Only hard board verbs auto-fire; an answer that is a
     *decision* ('two-pools', 'move-cache', 'raise — spend') stays
     flagged — it chose WHAT, a human still owns the HOW. When the
     request had options and the answer matched none (free text), the
     soft assent family (yes/approve/continue/...) does not fire — a
     bare 'yes' is only read as 'queue' on a no-options ask.

Verbs and their board-api do_action equivalents:

  queue|dispatch|proceed|go|run|start|build|yes|yeah|approve|continue
      -> action.status=queued (done/review -> backlog) — a dispatch
         session picks the card up; the answered request on the card is
         its marching orders
  retry -> queue + attempts bump (do_action retry)
  close|done|resolve|retire|archive
      -> column=done, action.status=done — merge-guarded: when the card
         has live session work dispatch_repos.guard cannot clear, the
         close defers (retried each tick — it lands once the merge
         does), never closes on faith
  hold|park|defer|wait|later|keep|stay|backlog
      -> action.status=idle, column=backlog — the recorded 'not now'
  superseded|duplicate|self-resolved|merged|n/a|nothing|skip
      -> none: stamped executed, no transition — the answer resolves the
         request without board work

Skip rules: done/lab cards; requests other executors own (id prefixes
lab-review -> lab-review-sweep, merge-conflict* -> merge-sweep's
re-raise lifecycle); verbs on cards whose action is starting/running
(deferred, not dropped — a 'close' becomes executable when the session
finishes; 'queued' is not busy — hold/close disarm it). Conflicting
recognized verbs on one card defer the card — a human untangles
'close' vs 'queue'.

An executed answer stamps `executed: "<date> <verb>"`; awaiting_action
clears when no unanswered-for-triage answer remains.

Usage: answer-sweep.py [--dry-run]
Env:   CHABA_REPO (cards checkout), ANSWER_SWEEP_MAX (executions cap,
       default 10)
"""

from __future__ import annotations

import fcntl
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import dispatch_repos as dr
except Exception:  # close verb degrades to defer when the guard can't load
    dr = None

REPO = Path(os.environ.get(
    "CHABA_REPO", str(Path(__file__).resolve().parents[2])))
CARD_DIR = REPO / "docs" / "ssot" / "kanban" / "cards"
LOCK = Path("/tmp/board-api.lock")
MAX_ACTS = int(os.environ.get("ANSWER_SWEEP_MAX", "10"))
TZ = timezone(timedelta(hours=7))  # same stamp board-api's now() writes

# Requests another component executes — their answers are not generic
# verbs (lab-review outcomes stamp lab.outcome; merge-conflict answers
# are resolved by the human merge + re-raise lifecycle).
OWNED_PREFIXES = ("lab-review", "merge-conflict")

ACTIONS = {"queue", "retry", "close", "hold", "none"}

# First-token answer -> board action. 'none' = acknowledged, no
# transition. Deliberately conservative: decision-words (option ids like
# two-pools/move-cache, spend asks, hardware picks) are not verbs and
# stay for human triage.
VERBS = {
    "queue": "queue", "dispatch": "queue", "proceed": "queue",
    "go": "queue", "run": "queue", "start": "queue", "build": "queue",
    "yes": "queue", "yeah": "queue", "approve": "queue",
    "approved": "queue", "continue": "queue",
    "retry": "retry",
    "close": "close", "done": "close", "resolve": "close",
    "resolved": "close", "retire": "close", "archive": "close",
    "hold": "hold", "park": "hold", "parked": "hold", "defer": "hold",
    "wait": "hold", "later": "hold", "keep": "hold", "stay": "hold",
    "backlog": "hold",
    "superseded": "none", "duplicate": "none", "self-resolved": "none",
    "merged": "none", "n/a": "none", "none": "none", "nothing": "none",
    "skip": "none", "no-op": "none",
}

# Assent words that only fire on option-less asks — on a multi-option
# request an unmatched 'yes' proves nothing about which option won.
SOFT = {"yes", "yeah", "approve", "approved", "continue", "go", "run",
        "start", "build"}

EM_DASH = re.compile(r"\s+[—–-]\s+|\s+[—–-]\s*|\s*—\s*")


def now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def comms_add(card: dict, frm: str, text: str) -> None:
    card.setdefault("comms", []).append(
        {"at": now(), "from": frm, "text": text[:500]})


def _opt_id(o) -> str:
    return str(o.get("id") or "") if isinstance(o, dict) else ""


def _opt_label(o) -> str:
    if isinstance(o, dict):
        return str(o.get("label") or o.get("id") or "")
    return str(o)


def _clean(s: str) -> str:
    return str(s or "").replace("★", "").replace("✓", "").strip()


def match_option(answer: str, opts: list):
    """The option the answer selected, or None. Dict options answer as
    'id — label'; a truncated/verbatim label still matches on bare id or
    the em-dash head."""
    norm = _clean(answer)
    for o in opts:
        oid, lbl = _opt_id(o), _opt_label(o)
        cands = {_clean(oid), _clean(lbl)}
        if oid and lbl:
            cands.add(_clean(f"{oid} — {lbl}"))
            cands.add(_clean(f"{oid} - {lbl}"))
        if norm in {c for c in cands if c}:
            return o
    head = EM_DASH.split(norm, 1)[0].strip()
    if head:
        for o in opts:
            if _opt_id(o) and head == _clean(_opt_id(o)):
                return o
    return None


def classify(req: dict) -> tuple[str | None, str]:
    """(action, why) for one answered request — action in ACTIONS, or
    None when the answer maps to no verb (stays for human triage)."""
    answer = _clean(req.get("answer"))
    if not answer:
        return None, "empty answer"
    opts = req.get("options") or []
    opt = match_option(answer, opts) if opts else None
    if isinstance(opt, dict) and opt.get("action"):
        act = str(opt["action"]).strip().lower()
        if act in ACTIONS:
            return act, f"option {_opt_id(opt)!r} action={act}"
        return None, f"option {_opt_id(opt)!r} bad action={act!r}"
    candidates = []
    if isinstance(opt, dict) and _opt_id(opt):
        candidates.append(_opt_id(opt))           # emitter-chosen id
    if opt is not None and not isinstance(opt, dict):
        candidates.append(_clean(opt).split()[0] if _clean(opt) else "")
    head = EM_DASH.split(answer, 1)[0].strip()
    first = head.split()[0] if head.split() else ""
    candidates += [first, first.split("-")[0] if "-" in first else ""]
    free_text = bool(opts) and opt is None
    for cand in candidates:
        verb = _clean(cand).lower().strip(".,!:")
        if not verb:
            continue
        act = VERBS.get(verb)
        if act is None:
            continue
        if free_text and verb in SOFT:
            continue  # unmatched free text on an options ask — too loose
        return act, f"verb {verb!r}"
    return None, "unmapped answer"


def pending(card: dict) -> list[dict]:
    """Answered, unexecuted, unowned requests + the card-level ask."""
    out = []
    for r in card.get("requests") or []:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        if any(rid.startswith(p) for p in OWNED_PREFIXES):
            continue
        if r.get("status") == "answered" and not r.get("executed"):
            out.append(r)
    ask = card.get("ask")
    if isinstance(ask, dict) and ask.get("status") == "answered" \
            and not ask.get("executed"):
        ask.setdefault("id", "ask")
        out.append(ask)
    return out


def close_ok(card: dict) -> tuple[bool, str]:
    """Merge-guard for the close verb — stricter than the board button:
    an unresolvable guard defers instead of allowing."""
    a = card.get("action") or {}
    if a.get("type") != "dispatch" or not a.get("task_id") or dr is None:
        return True, ""
    try:
        g = dr.guard(card)
    except Exception as e:
        return False, f"merge guard erred: {e}"
    if g["note"]:
        comms_add(card, "chaba", g["note"])
    if not g["allowed"]:
        return False, g["summary"]
    return True, ""


def apply_verb(card: dict, verb: str) -> str:
    """do_action equivalents; returns the comms-worthy outcome."""
    a = card.setdefault("action", {})
    if verb in ("queue", "retry") and a.get("type") not in (None,
                                                          "dispatch"):
        # a 'queue' answer must not flip a manual/container/script card
        # into a devin dispatch — those belong to a human/runner-agent
        return f"DEFER:card action type={a.get('type')} — not " \
               "dispatch-claimable"
    if verb == "queue":
        a.setdefault("type", "dispatch")
        a["status"] = "queued"
        a.pop("runner", None)
        a.pop("task_id", None)
        a.pop("verified", None)
        if card.get("column") in ("done", "review"):
            card["column"] = "backlog"
        return "queued for processing"
    if verb == "retry":
        a["status"] = "queued"
        prev = a.pop("result", None)
        if prev:
            a["last_failure"] = str(prev)[:300]
        a.pop("runner", None)
        a["attempts"] = int(a.get("attempts") or 0) + 1
        a.pop("verified", None)
        return "re-queued"
    if verb == "close":
        ok, why = close_ok(card)
        if not ok:
            return f"DEFER:{why}"
        card["column"] = "done"
        a["status"] = "done"
        card.setdefault("claim", {}).pop("session", None)
        return "moved to done"
    if verb == "hold":
        a["status"] = "idle"
        if card.get("column") != "backlog":
            card["column"] = "backlog"
        return "put on hold"
    return f"DEFER:unknown verb {verb}"


def triage_card(card: dict, ref: str, budget: list[int]) -> tuple[list, list]:
    """(acted, notes) — executes at most one verb per card per pass."""
    reqs = pending(card)
    if not reqs:
        return [], []
    a = card.get("action") or {}
    # busy = a dispatch is claimed/in flight — verbs defer rather than
    # race the runner. 'queued' is NOT busy: a hold/close answer disarms
    # it (the answer IS the triage), matching the board buttons.
    busy = a.get("status") in ("starting", "running")
    noops, verbs, unmapped = [], {}, []
    for r in reqs:
        act, why = classify(r)
        if act is None:
            unmapped.append(r)
        elif act == "none":
            noops.append((r, why))
        else:
            verbs.setdefault(act, []).append((r, why))
    acted, notes = [], []

    def stamp(rs, verb, note_extra=""):
        for r, _why in rs:
            r["executed"] = f"{ref} {verb}"
            acted.append(str(r.get("id") or "ask"))
        if note_extra:
            notes.append(note_extra)

    for r, why in noops:  # resolution receipts — always safe to stamp
        r["executed"] = f"{ref} none"
        acted.append(str(r.get("id") or "ask"))
        notes.append(f"answer-sweep: '{_clean(r.get('answer'))[:60]}' "
                     f"resolves {r.get('id')} — no board action ({why})")

    live = [v for v in verbs if v in ("queue", "retry", "close", "hold")]
    if len(live) > 1:
        notes.append(
            f"answer-sweep: conflicting answered verbs {live} — "
            "needs human triage")
    elif live:
        verb = live[0]
        if busy:
            # in flight — a 'queue' answer's intent is satisfied;
            # retry/close/hold wait for the session to finish
            if verb == "queue":
                stamp(verbs[verb], f"queue (already {a.get('status')})")
            else:
                notes.append(
                    f"answer-sweep: '{verb}' deferred — action already "
                    f"{a.get('status')}")
        elif a.get("status") == "queued" and verb == "queue":
            stamp(verbs[verb], "queue (already queued)")
        elif budget[0] <= 0:
            notes.append(f"answer-sweep: '{verb}' deferred — "
                         "ANSWER_SWEEP_MAX reached")
        else:
            out = apply_verb(card, verb)
            if out.startswith("DEFER:"):
                notes.append(f"answer-sweep: '{verb}' deferred — "
                             f"{out[6:]}")
            else:
                stamp(verbs[verb], verb)
                notes.append(f"answer-sweep: executed "
                             f"'{_clean(verbs[verb][0][0].get('answer'))[:60]}'"
                             f" -> {out}")
                budget[0] -= 1
    if unmapped and (acted or notes):
        notes.append(f"answer-sweep: {len(unmapped)} answered request(s) "
                     "still unmapped — stays flagged")
    return acted, notes


def card_needs_triage(card: dict) -> bool:
    """awaiting_action should persist while an answered request is still
    unexecuted (unmapped answers included — they ARE the triage). The
    flag is meaningless on done/lab cards — cleared there."""
    if card.get("column") in ("done", "lab"):
        return False
    return bool(pending(card))


def main() -> int:
    dry = "--dry-run" in sys.argv
    ref = today()
    report = []
    # pass 1 (unlocked): cards with answers to execute OR an
    # awaiting_action flag to heal (pre-flag answers still count)
    cands = []
    for p in sorted(CARD_DIR.glob("*.yml")):
        try:
            card = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if card.get("awaiting_action") or (
                card.get("column") not in ("done", "lab")
                and pending(card)):
            cands.append((p, card.get("id") or p.stem))
    if not cands:
        print("answer-sweep: no answered requests awaiting triage")
        return 0
    if dry:
        for p, cid in cands:
            card = yaml.safe_load(p.read_text()) or {}
            if card.get("column") in ("done", "lab"):
                if card.get("awaiting_action"):
                    print(f"  {cid}: done/lab — would clear stale flag")
                continue
            reqs = pending(card)
            kinds = [(str(r.get("id")), classify(r)) for r in reqs]
            flag = "" if card.get("awaiting_action") else " +flag"
            print(f"  {cid}: " + "; ".join(
                f"{rid}={act or 'unmapped'} ({why})"
                for rid, (act, why) in kinds) + flag)
        print(f"answer-sweep: dry-run — {len(cands)} card(s) with "
              "answered requests")
        return 0

    budget = [MAX_ACTS]
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        for p, cid in cands:
            try:
                card = yaml.safe_load(p.read_text()) or {}
            except Exception:
                continue
            if card.get("column") in ("done", "lab"):
                acted, notes = [], []  # flag hygiene only on done/lab
            else:
                acted, notes = triage_card(card, ref, budget)
            # deferred-verb notes repeat every tick — dedup against the
            # card's recent comms so a held card doesn't spam the log
            recent = {str(m.get("text")) for m in
                      (card.get("comms") or [])[-8:]}
            fresh = [n for n in notes if n not in recent]
            needs = card_needs_triage(card)
            flag_flip = bool(card.get("awaiting_action")) != needs
            if not acted and not fresh and not flag_flip:
                continue
            if needs:
                card["awaiting_action"] = True
            else:
                card.pop("awaiting_action", None)
            for n in fresh:
                comms_add(card, "chaba", n)
            card["updated"] = now()
            p.write_text(yaml.safe_dump(card, allow_unicode=True,
                                        sort_keys=False, width=110))
            report.append(f"{cid} ({len(acted)} executed)")
    print("answer-sweep: "
          + (f"{len(report)} card(s) triaged: {', '.join(report)}"
             if report else "answers still unmapped — none executable"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
