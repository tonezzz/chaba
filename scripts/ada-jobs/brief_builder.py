#!/usr/bin/env python3
"""brief_builder.py — Ada job-brief builder (ADA-1132).

Gives her job-scoped context like Devin gets: standing memory + the card
+ on-demand pull. This builds the PULL: top-N similar done-cards with
their proven-right outcomes — judgment follows evidence, not instinct.

v1 retrieval: token-overlap similarity over the card-judgment corpus
(labeled past decisions) + keyword-matched SSOT pointers. No embeddings
needed — the corpus IS the precedent index.

Usage:
  brief_builder.py <card-id>                 # print the bundle
  (import build_brief(card) for lanes)       # returns dict
"""
import json, os, re, sys, urllib.request

API = os.environ.get("BOARD_API", "https://idc03.taila0626a.ts.net:10000")
CORPUS = os.path.join(os.path.dirname(__file__), "..",
                      "bench/card-judgment/corpus.jsonl")

STOP = {"the", "and", "for", "with", "card", "a", "an", "of", "to", "on",
        "in", "is", "it", "this", "that", "from", "by", "as", "be", "or"}


def tokens(text):
    return {t for t in re.findall(r"[a-z0-9_-]+", (text or "").lower())
            if t not in STOP and len(t) > 2}


def load_corpus():
    try:
        return [json.loads(l) for l in open(CORPUS)]
    except Exception:
        return []


def similar_cases(card, corpus, top=3):
    """Score corpus cases by token overlap with the card — the precedent
    list with proven-right outcomes."""
    qt = tokens(card.get("title", "") + " " + str(card.get("brief") or "")
                + " " + " ".join(card.get("tags") or []))
    if not qt:
        return []
    scored = []
    for c in corpus:
        snap = c.get("snapshot") or {}
        ct = tokens(str(snap.get("title") or "") + " "
                    + str(snap.get("brief") or ""))
        if not ct:
            continue
        inter = len(qt & ct)
        if inter:
            scored.append((inter / (len(qt | ct) or 1), c))
    scored.sort(key=lambda x: -x[0])
    return [{"case_id": c["case_id"], "gold": c["category"],
             "evidence": (c.get("evidence") or "")[:120],
             "proven_right": (c.get("proven_right") or "")[:140],
             "sim": round(s, 2)} for s, c in scored[:top] if s > 0]


def get_card(cid):
    req = urllib.request.Request(API + "/cards")
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())
    cs = d if isinstance(d, list) else d.get("cards", [])
    return next((c for c in cs if c.get("id") == cid), None)


def build_brief(card, corpus=None, top=3):
    """The job-brief: card snapshot + past precedents with outcomes."""
    corpus = corpus if corpus is not None else load_corpus()
    return {
        "card_id": card.get("id"),
        "title": card.get("title"),
        "priority": card.get("priority"),
        "review_kind": card.get("review_kind"),
        "spec_present": bool(card.get("spec")),
        "open_requests": [{"ask": r.get("ask")} for r in
                          (card.get("requests") or [])
                          if str(r.get("status", "")).lower() not in
                          ("answered", "resolved", "closed")][:3],
        "comms_tail": [m.get("text", "")[:140]
                       for m in (card.get("comms") or [])[-4:]],
        "precedents": similar_cases(card, corpus, top),
    }


if __name__ == "__main__":
    cid = sys.argv[1] if len(sys.argv) > 1 else ""
    if not cid:
        print("usage: brief_builder.py <card-id>"); sys.exit(1)
    card = get_card(cid)
    if not card:
        print(f"{cid} not on board"); sys.exit(1)
    print(json.dumps(build_brief(card), indent=2, ensure_ascii=False))
