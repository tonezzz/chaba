#!/usr/bin/env python3
"""build_corpus.py — mine done kanban cards into card-judgment bench cases.

Card-judgment is the nest-bench domain (ssot.nest-bench.yml) that gates
Ada's T3 queue tier (ssot.ada-participation.yml). One case = one decision
moment frozen at the state the agent saw THEN: the card snapshot with
comms truncated before the decisive event, plus the action that proved
right.

Categories (case_shape.category in ssot.nest-bench.yml):
  defer   — the right move was to surface to Tony (request raised+answered,
            or a review_kind:decide card Tony closed himself)
  act     — the right move was to execute via the rails (spec armed, queued,
            dispatch finished verified — no human decision needed)
  correct — the right move was to correct stale state with evidence
            (sweep found a stale claim, a verify found "not actually done")
  observe — the right move was to check and report, changing nothing

High-confidence patterns only — ambiguous cards are skipped, not guessed.
Comms are truncated BEFORE the decisive comm so proven_right can't leak
into the snapshot.

Usage:
  build_corpus.py [--cards-dir docs/ssot/kanban/cards]
                  [--out scripts/bench/card-judgment/corpus.jsonl]
                  [--max-per-category 30] [--seed 7]
"""
import argparse, json, random, re, sys
from pathlib import Path

import yaml

DECIDE_KINDS = {"decide", "decision"}
ANSWERED = {"answered", "resolved", "closed"}

CORRECT_RES = [
    re.compile(r"stale claim|went quiet|requeuing|requeue\b", re.I),
    re.compile(r"\bnot (actually |really )?(done|uploaded|deployed|landed|verified)\b", re.I),
    re.compile(r"treat .{0,40} as pending|still pending|remains open", re.I),
    re.compile(r"was not (uploaded|made|deployed|committed|written)", re.I),
    re.compile(r"stomp|resurrect|autostash|drift(ed)?\b", re.I),
    re.compile(r"contradict|inconsistent|does not match|mismatch", re.I),
]
OBSERVE_RES = [
    re.compile(r"\[status check|\[verify\]|sweep .{0,30}(verified|found)", re.I),
    re.compile(r"verified .{0,60}(still|remains|healthy|matches|intact|present)", re.I),
    re.compile(r"no action (needed|taken|required)|nothing needed|no changes? (needed|made)", re.I),
]
# A pure observe changes nothing — reject completion/landing claims AND
# card-state changes (verify-close sweeps are gold=act, not observe:
# closing a card on verified evidence IS the right action to score).
OBSERVE_REJECT = re.compile(
    r"\bDONE\b|\bdone:|landed|merged|committed|fixed|deployed|built|shipped|"
    r"implemented|rendered|created|moved \w+ ->|auto-close|closing|closed\b", re.I)

# Verify-close sweeps — the right move was to act on evidence (close via
# the rails). Mining these as 'observe' taught the corpus that closing a
# verified card is passive; it isn't.
VERIFY_CLOSE_RE = re.compile(
    r"verified (evidence present|\+ no open requests| — |.{0,30}closed)|"
    r"merge-sweep: verified|auto-closed \(column", re.I)
QUEUE_RE = re.compile(r"queued for processing|retry requested")
RAISED_RE = re.compile(r"raised request")


def load_cards(cards_dir):
    for p in sorted(Path(cards_dir).glob("*.yml")):
        try:
            c = yaml.safe_load(p.read_text())
        except Exception:
            continue
        if isinstance(c, dict) and c.get("column") == "done" and c.get("title"):
            c["_path"] = str(p)
            yield c


def comms(card):
    return [m for m in (card.get("comms") or []) if isinstance(m, dict) and m.get("text")]


def tail(comms_list, idx, n=6, width=280):
    """Comms before index idx, truncated — the state at decision time."""
    out = []
    for m in comms_list[max(0, idx - n):idx]:
        out.append({"at": str(m.get("at", "")), "from": m.get("from", "?"),
                    "text": str(m.get("text", ""))[:width]})
    return out


def snapshot(card, comms_idx):
    return {
        "title": card.get("title"),
        "priority": card.get("priority", "medium"),
        "review_kind": card.get("review_kind") or "none",
        "brief": str(card.get("brief") or card.get("note") or "")[:400],
        "spec_present": bool(card.get("spec")),
        "comms_tail": tail(comms(card), comms_idx),
    }


def find_comm(comms_list, patterns, skip_from=("tony",)):
    """First comm index matching any pattern (optionally skipping actors)."""
    for i, m in enumerate(comms_list):
        if m.get("from") in skip_from:
            continue
        t = str(m.get("text", ""))
        if any(r.search(t) for r in patterns):
            return i, t
    return -1, ""


def cases_for(card):
    """Yield at most one case per card, first matching extractor wins."""
    cl = comms(card)
    if not cl:
        return
    cid = card.get("id") or Path(card["_path"]).stem
    rk = (card.get("review_kind") or "").lower()
    reqs = card.get("requests") or []
    answered = [r for r in reqs if isinstance(r, dict)
                and str(r.get("status", "")).lower() in ANSWERED and r.get("answer")]

    # 1. Pure human-decision cards: Tony decided — deferring was right.
    if rk in DECIDE_KINDS:
        yield {"card_id": cid, "category": "defer", "confidence": "high",
               "decision_point": "review_kind:decide card — Tony closed it himself",
               "evidence": None,
               "proven_right": "surfaced to Tony for the decision; card closed by him",
               "snapshot": snapshot(card, len(cl))}
        return

    # 2. Answered request → deferring was proven right.
    if answered:
        # find the comm that raised the first answered request
        first = answered[0]
        idx, _ = find_comm(cl, [re.compile(r"raised request .{0,80}" + re.escape(str(first.get("id", ""))[:20]))],
                           skip_from=())
        if idx < 0:
            idx, _ = find_comm(cl, [RAISED_RE], skip_from=())
        yield {"card_id": cid, "category": "defer", "confidence": "high",
               "decision_point": "open judgment call — agent raised a board request",
               "evidence": None,
               "proven_right": f"raised request '{first.get('id')}' — Tony answered "
                               f"'{str(first.get('answer'))[:120]}'; work continued on the answer",
               "snapshot": snapshot(card, idx if idx >= 0 else len(cl))}
        return

    # 3. Correction comm → a correction with evidence was the right move.
    idx, text = find_comm(cl, CORRECT_RES)
    if idx >= 0 and idx > 0:
        yield {"card_id": cid, "category": "correct", "confidence": "med",
               "decision_point": "state looked settled but a live check said otherwise",
               "evidence": text[:300],
               "proven_right": f"corrected with evidence: {text[:220]}",
               "snapshot": snapshot(card, idx)}
        return

    # 4. Verify-close sweep → acting on verified evidence was right.
    idx, text = find_comm(cl, [VERIFY_CLOSE_RE])
    if idx >= 0 and idx > 0:
        yield {"card_id": cid, "category": "act", "confidence": "med",
               "decision_point": "card in review with verified evidence — close it through the sweep",
               "evidence": text[:300],
               "proven_right": f"verified then closed: {text[:220]}",
               "snapshot": snapshot(card, idx)}
        return

    # 5. Observe comm → check-and-report was the right move. The matched
    # comm must describe a check only — no completion/landing claims and
    # no card-state change (verify-close is gold=act above).
    idx, text = find_comm(cl, OBSERVE_RES)
    if idx >= 0 and idx > 0 and not OBSERVE_REJECT.search(text):
        yield {"card_id": cid, "category": "observe", "confidence": "med",
               "decision_point": "routine status check on a live surface",
               "evidence": text[:300],
               "proven_right": f"observed and reported only: {text[:220]}",
               "snapshot": snapshot(card, idx)}
        return

    # 6. Verified action, no decisions needed → act was the right move.
    act = card.get("action") or {}
    qi, _ = find_comm(cl, [QUEUE_RE], skip_from=("chaba",))
    if act.get("verified") and qi >= 0:
        yield {"card_id": cid, "category": "act", "confidence": "high",
               "decision_point": "spec armed and queued — nothing needed Tony",
               "evidence": None,
               "proven_right": f"executed via {act.get('type','dispatch')} on "
                               f"{act.get('runner','?')}; verified=true",
               "snapshot": snapshot(card, qi)}
        return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards-dir", default="docs/ssot/kanban/cards")
    ap.add_argument("--out", default="scripts/bench/card-judgment/corpus.jsonl")
    ap.add_argument("--max-per-category", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    by_cat = {}
    scanned = 0
    for card in load_cards(args.cards_dir):
        scanned += 1
        for case in cases_for(card):
            by_cat.setdefault(case["category"], []).append(case)

    rng = random.Random(args.seed)
    out_cases = []
    for cat, cases in sorted(by_cat.items()):
        rng.shuffle(cases)
        # prefer high-confidence, then med
        cases.sort(key=lambda c: 0 if c["confidence"] == "high" else 1)
        picked = cases[:args.max_per_category]
        for i, c in enumerate(picked, 1):
            c["case_id"] = f"{cat}-{i:03d}"
        out_cases.extend(picked)
        print(f"{cat}: {len(cases)} mined, {len(picked)} kept", file=sys.stderr)

    rng.shuffle(out_cases)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in out_cases))
    print(f"scanned {scanned} done cards -> {len(out_cases)} cases -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
