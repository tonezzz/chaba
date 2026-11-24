#!/usr/bin/env python3
"""card-triage — run /v1/systemone decision backends over real kanban cards.

Phase-1 pilot for card jev-pilot-decision-layer-for-card-triage-d47b53
(KNB-0822): for each card ask three questions in ONE systemone call —

  lane      choice  — cheapest dispatch lane (criteria mirror
                      dispatch_repos.classify_lane's jevos fallback)
  priority  score   — 5-level priority (criteria is a LIST; openjev
                      ScoreQuestion requires list, dict 422s)
  ready     noul    — spec complete enough to dispatch without Tony

Backends are wire-compatible /v1/systemone servers but answer shapes
differ: openjev (gemma students) returns {choice,probabilities,
confidence} / {score,legend,probabilities,confidence} / {noul:p};
jev-student-distilmulti collapses choice->'answer'@0.0 and score/noul
to the same head probability. Raw answers are kept verbatim in the
output so degenerate heads stay visible.

Usage:
  card-triage.py --cards cards.json --out out.json [--md report.md]
  card-triage.py --ids id1,id2 --api https://idc03...:10000 --out out.json
  --backend name=base-url   (repeatable; default jev-student + student-1b)

Env: JEV_STUDENT_URL (default http://100.75.102.88:8780),
     JEV_STUDENT_1B_URL (default http://100.75.102.88:8778).
"""
import argparse, json, os, sys, time, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))

LANE_CRITERIA = {
    "codemod": "deterministic pattern change, known transform, no judgment",
    "free_lane": "single-step chore, verification exists, no long horizon",
    "paid_frontier": "contained code task needing strong reasoning",
    "devin": "multi-step, remote diagnosis, ambiguous, or no-gate work",
    "manual": "needs Tony's hands (hardware, accounts, physical)",
}
PRIORITY_LEVELS = ["trivial", "low", "normal", "high", "urgent"]

QUESTIONS = {
    "lane": {"type": "choice",
             "instructions": "Choose the cheapest lane that can complete "
                             "this card's work class.",
             "criteria": LANE_CRITERIA},
    "priority": {"type": "score",
                 "instructions": "Rate this card's priority for the "
                                 "operator (1=trivial .. 5=urgent).",
                 "criteria": PRIORITY_LEVELS},
    "ready": {"type": "noul",
              "instructions": "Does this card carry a complete enough "
                              "spec/brief to dispatch without asking the "
                              "operator a clarifying question?",
              "criteria": {"true": "spec is actionable as written",
                           "false": "spec is missing, ambiguous, or "
                                    "needs a decision first"}},
}

DEFAULT_BACKENDS = [
    ("jev-student", os.environ.get("JEV_STUDENT_URL",
                                 "http://100.75.102.88:8780")),
    ("student-1b", os.environ.get("JEV_STUDENT_1B_URL",
                                "http://100.75.102.88:8778")),
]


def fetch_cards(api, ids=None, column="backlog", limit=0):
    q = f"fields=id,title,column,priority,tags,brief,spec,action"
    if ids:
        out = []
        for cid in ids:
            u = (f"{api}/cards?id={cid}&{q}")
            d = json.load(urllib.request.urlopen(u, timeout=30))
            out.extend(d.get("cards") or [])
        return out
    u = f"{api}/cards?column={column}&{q}&limit={limit or 50}"
    d = json.load(urllib.request.urlopen(u, timeout=60))
    return d.get("cards") or []


def card_state(card):
    return {"card": card.get("id"), "title": card.get("title") or "",
            "brief": card.get("brief") or "",
            "spec": (card.get("spec") or "")[:1200]}


def ask(base, state, questions, timeout=180):
    payload = {"model": "jev-latest", "state": state,
               "questions": questions}
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/systemone",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        return r.get("answers") or {}, round((time.time() - t0) * 1000), None
    except Exception as e:
        return {}, round((time.time() - t0) * 1000), str(e)[:160]


def summarize(answers):
    """Normalize the three answer shapes into {lane,priority,ready}."""
    out = {}
    lane = answers.get("lane") or {}
    out["lane"] = {"choice": lane.get("choice"),
                   "confidence": lane.get("confidence"),
                   "probabilities": lane.get("probabilities")}
    prio = answers.get("priority") or {}
    score = prio.get("score")
    legend = prio.get("legend") or {}
    # openjev score = float index into the criteria list; distilmulti
    # score = raw head probability. Keep both raw + a best-effort label.
    label = None
    if isinstance(score, (int, float)) and legend:
        label = legend.get(str(int(round(score))))
    elif isinstance(score, (int, float)) and 0 <= score <= 4:
        label = PRIORITY_LEVELS[int(round(score))]
    out["priority"] = {"score": score, "label": label,
                       "confidence": prio.get("confidence")}
    ready = answers.get("ready") or {}
    out["ready"] = {"noul": ready.get("noul")}
    return out


def prod_lane(card):
    """Production keyword classifier verdict, for the reference column."""
    try:
        import dispatch_repos as dr
        return dr.classify_lane(card, with_detail=True)
    except Exception as e:
        return (None, f"err:{e}", None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", help="JSON file: list or {cards:[...]}")
    ap.add_argument("--ids", help="comma-separated card ids (needs --api)")
    ap.add_argument("--api", default="https://idc03.taila0626a.ts.net:10000")
    ap.add_argument("--column", default="backlog")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--backend", action="append", default=[],
                    help="name=base-url (repeatable)")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--out", required=True)
    ap.add_argument("--md", help="also write a markdown triage table")
    args = ap.parse_args()

    if args.cards:
        raw = json.load(open(args.cards))
        cards = raw.get("cards") if isinstance(raw, dict) else raw
    else:
        ids = [s for s in (args.ids or "").split(",") if s]
        cards = fetch_cards(args.api, ids or None, args.column, args.limit)
    if not cards:
        print("no cards", file=sys.stderr)
        return 1

    backends = []
    for spec in args.backend:
        name, _, base = spec.partition("=")
        backends.append((name, base))
    if not backends:
        backends = DEFAULT_BACKENDS

    records = []
    for card in cards:
        cid = card.get("id")
        state = card_state(card)
        lane, src, conf = prod_lane(card)
        row = {"id": cid, "title": card.get("title"),
               "column": card.get("column"),
               "priority_field": card.get("priority"),
               "prod_lane": lane, "prod_source": src,
               "prod_conf": conf, "arms": {}}
        for name, base in backends:
            ans, ms, err = ask(base, state, QUESTIONS, args.timeout)
            row["arms"][name] = {"ms": ms, "err": err,
                                 "raw": ans, "sum": summarize(ans)}
            print(f"  {cid[:44]:46s} {name:12s} {ms:6d}ms"
                  + (f" ERR {err}" if err else ""), flush=True)
        records.append(row)

    json.dump({"cards": records, "questions": QUESTIONS,
               "backends": [n for n, _ in backends]},
              open(args.out, "w"), ensure_ascii=False, indent=1)
    print("wrote", args.out)

    if args.md:
        lines = ["| card | prod lane | " +
                 " | ".join(f"{n} lane (conf)" for n, _ in backends) +
                 " | " + " | ".join(f"{n} prio" for n, _ in backends) +
                 " | " + " | ".join(f"{n} ready" for n, _ in backends) + " |",
                 "|" + "---|" * (3 + 3 * len(backends))]
        for r in records:
            cells = [f"`{r['id']}`", f"{r['prod_lane']} ({r['prod_source']})"]
            for n, _ in backends:
                s = (r["arms"].get(n) or {}).get("sum") or {}
                ln = s.get("lane") or {}
                cells.append(f"{ln.get('choice')} ({ln.get('confidence')})")
            for n, _ in backends:
                s = (r["arms"].get(n) or {}).get("sum") or {}
                p = s.get("priority") or {}
                cells.append(f"{p.get('label') or p.get('score')}")
            for n, _ in backends:
                s = (r["arms"].get(n) or {}).get("sum") or {}
                rd = s.get("ready") or {}
                v = rd.get("noul")
                cells.append(f"{v:.2f}" if isinstance(v, (int, float)) else "-")
            lines.append("| " + " | ".join(cells) + " |")
        open(args.md, "w").write("\n".join(lines) + "\n")
        print("wrote", args.md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
