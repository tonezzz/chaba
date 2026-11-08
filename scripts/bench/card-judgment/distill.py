#!/usr/bin/env python3
"""distill.py — free-lane card distiller (ADA-1133).

Distills a kanban card into a FIXED SLOT brief — not freeform summary,
so nothing decisive is lost. Cached by (card_id, updated) so a card only
re-distills on change.

Slots (the things a judgment needs, no prose):
  state          — one line: where the card actually is
  open_asks      — pending requests[] with unresolved status (defer signal)
  gates          — priority:high / review_kind:decide / prod-security flags
  evidence       — is there a checkable fact in comms? yes/no + what
  staleness      — days since updated + one-word smell (fresh|stale|dead)
  last_action    — last thing that happened (from comms tail)
  needed_class   — what kind of move this card wants next
                   (execute|decide|correct|monitor)

Lane chain: CF workers-ai 70b -> local ollama -> (future: or-free).
Usage:
  distill.py CARD_ID [CARD_ID...]        # print slot brief per card
  distill.py --all-done                  # distill every done card (batch)
  distill.py --bench-corpus FILE         # distill each corpus case's card
"""
import argparse, json, os, re, sys, urllib.request, hashlib

API = os.environ.get("BOARD_API", "https://idc03.taila0626a.ts.net:10000")
CF_BASE = "https://api.cloudflare.com/client/v4/accounts/%s/ai/v1"
CACHE = os.path.expanduser("~/.cache/card-distill.json")

SLOTS = ["state", "open_asks", "gates", "evidence", "staleness",
         "last_action", "needed_class"]

PROMPT = """Distill this kanban card into the fixed slot brief below. Output
ONLY a JSON object with EXACTLY these keys — no extra keys, no prose:

{"state":"one line","open_asks":"none | the pending ask",
"gates":"none | priority:high | review_kind:decide | prod/security",
"evidence":"no | checkable fact present: what",
"staleness":"fresh|stale|dead",
"last_action":"one line from comms tail",
"needed_class":"execute|decide|correct|monitor"}

Card: """


def _chat(url, model, key, system, user, timeout=120, max_tokens=400):
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {key}"} if key else {})})
    d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    return d["choices"][0]["message"]["content"]


def card_text(card):
    out = {k: card.get(k) for k in
           ("id", "title", "column", "priority", "review_kind", "tags",
            "brief", "spec", "updated")}
    out["requests"] = [{"ask": r.get("ask"), "status": r.get("status")}
                       for r in (card.get("requests") or [])]
    out["comms_tail"] = [m.get("text", "")[:140]
                         for m in (card.get("comms") or [])[-6:]]
    return json.dumps(out, ensure_ascii=False)[:5000]


def distill(card, lanes):
    """lanes: [(base_url, model, api_key), ...] — try in order."""
    user = card_text(card)
    for base, model, key in lanes:
        try:
            text = _chat(base, model, key, PROMPT, user)
            m = re.search(r"\{.*\}", text, re.S)
            brief = json.loads(m.group(0))
            brief["_lane"] = model
            # normalize slots: needed_class must be ONE enum value
            nc = str(brief.get("needed_class") or "").lower()
            for c in ("execute", "decide", "correct", "monitor"):
                if c in nc:
                    brief["needed_class"] = c
                    break
            else:
                brief["needed_class"] = "monitor"
            return brief
        except Exception:
            continue
    return {"state": "distill-failed", "_lane": "none"}


def cache_key(card):
    return f"{card.get('id')}@{card.get('updated')}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cards", nargs="*")
    ap.add_argument("--bench-corpus", default="")
    ap.add_argument("--all-done", action="store_true")
    args = ap.parse_args()

    acct = os.environ.get("CF_API_ACCOUNT_ID", "")
    lanes = [
        (CF_BASE % acct, "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
         os.environ.get("CF_API_WORKER_TOKEN", "")),
        ("http://127.0.0.1:11434/v1", "llama3.2:3b", ""),
    ]

    cache = {}
    if os.path.exists(CACHE):
        cache = json.load(open(CACHE))

    if args.bench_corpus:
        ids = []
        for l in open(args.bench_corpus):
            d = json.loads(l)
            if d.get("card_id") and d["card_id"] not in ids:
                ids.append(d["card_id"])
        todo = ids
    else:
        todo = args.cards

    if not todo:
        print("usage: distill.py CARD_ID... | --bench-corpus FILE"); return

    req = urllib.request.Request(API + "/cards")
    allc = json.loads(urllib.request.urlopen(req, timeout=60).read())
    allc = allc if isinstance(allc, list) else allc.get("cards", [])
    byid = {c.get("id"): c for c in allc}

    for cid in todo:
        card = byid.get(cid)
        if not card:
            print(f"[{cid}] not on board"); continue
        k = cache_key(card)
        if k in cache:
            brief = cache[k]
        else:
            brief = distill(card, lanes)
            cache[k] = brief
        print(f"[{cid}] via {brief.get('_lane')}: "
              f"gates={brief.get('gates')} | asks={str(brief.get('open_asks'))[:60]} | needed={brief.get('needed_class')}")

    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, "w"), indent=1)


if __name__ == "__main__":
    main()
