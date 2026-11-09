#!/usr/bin/env python3
"""distill.py — free-lane card distiller (card-distill-free-lane / ADA-1133).

Distills a kanban card into a FIXED SLOT brief — not freeform summary,
so nothing decisive is lost. Sidecar cache per card, keyed by
(card_id, updated) for live cards or an explicit key for frozen bench
snapshots — a card re-distills only when its key changes.

Slots (schemas/card-distill-slots.schema.json):
  state            — one line: where the card actually is
  open_asks        — pending requests[] with unresolved status (defer signal)
  gates            — priority:high / review_kind:decide / prod-security flags
  evidence_present — is there a checkable fact in comms? yes/no + what
  staleness        — fresh|stale|dead (days since updated drives it)
  last_action      — last thing that happened (comms tail)
  needed_move_class— execute|decide|correct|monitor

Lane chain (same fallback pattern as verify_worker):
  cf-70b        Cloudflare Workers AI llama-3.3-70b
                (CF_API_ACCOUNT_ID + CF_API_WORKER_TOKEN|CF_API_TOKEN)
  local-ollama  127.0.0.1:11434 llama3.2:3b
  or-free       OpenRouter :free via litellm gateway (or-free-gemma31b)
  flash-lite-free gemini free tier via litellm gateway
  gemini-direct  tail lane: direct Gemini API w/ GEMINI_API_KEY (free key)

Each lane is env-overridable; a lane without its precondition (missing
key / unreachable) is skipped, the next serves. Gateway lanes take
LITELLM_URL + first set of LITELLM_KEY|LITELLM_KEY_CHABA|LITELLM_KEY_BENCH.

Consumers:
  bench:   build_corpus_v4.py distills frozen case snapshots (v4 corpus)
  live:    verify_worker.py --with-distill attaches slots to Ada's turn

Usage:
  distill.py CARD_ID [CARD_ID...]      # distill live cards (board-api)
  distill.py --all                     # every card on the board
  distill.py --json CARD_ID            # full brief JSON, not the one-liner
  distill.py --refresh CARD_ID         # ignore cache, re-distill
"""
import argparse, datetime, hashlib, json, os, re, sys, urllib.request

API = os.environ.get("BOARD_API", "https://idc03.taila0626a.ts.net:10000")
CF_BASE = "https://api.cloudflare.com/client/v4/accounts/%s/ai/v1"
GW_BASE = "http://100.102.134.91:4000/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
CACHE_DIR = os.environ.get("CARD_DISTILL_CACHE",
                           os.path.expanduser("~/.cache/card-distill"))

SLOTS = ["state", "open_asks", "gates", "evidence_present", "staleness",
         "last_action", "needed_move_class"]
MOVE_CLASSES = ("execute", "decide", "correct", "monitor")

PROMPT = """Distill this kanban card into the fixed slot brief below. Output
ONLY a JSON object with EXACTLY these keys — no extra keys, no prose:

{"state":"one line","open_asks":"none | the pending ask",
"gates":"none | priority:high | review_kind:decide | prod/security",
"evidence_present":"no | checkable fact present: what",
"staleness":"fresh|stale|dead",
"last_action":"one line from the comms tail",
"needed_move_class":"execute|decide|correct|monitor"}

Card: """


def default_lanes():
    """Ordered (name, base_url, model, api_key) — same chain shape as
    verify_worker: primary arg, fallback arg, every piece env-overridable."""
    lanes = []
    acct = os.environ.get("CF_API_ACCOUNT_ID", "")
    cf_key = (os.environ.get("CF_API_WORKER_TOKEN")
              or os.environ.get("CF_API_TOKEN") or "")
    if acct and cf_key:
        lanes.append(("cf-70b", CF_BASE % acct, os.environ.get(
            "DISTILL_CF_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
            cf_key))
    lanes.append(("local-ollama", os.environ.get(
        "DISTILL_OLLAMA_BASE", "http://127.0.0.1:11434/v1"),
        os.environ.get("DISTILL_OLLAMA_MODEL", "llama3.2:3b"), ""))
    gw_key = (os.environ.get("LITELLM_KEY")
              or os.environ.get("LITELLM_KEY_CHABA")
              or os.environ.get("LITELLM_KEY_BENCH") or "")
    gw_base = os.environ.get("LITELLM_URL", GW_BASE).rstrip("/")
    if gw_key:
        lanes.append(("or-free", gw_base, os.environ.get(
            "DISTILL_OR_MODEL", "or-free-gemma31b"), gw_key))
        lanes.append(("flash-lite-free", gw_base, os.environ.get(
            "DISTILL_FREE_MODEL", "gemini-3.5-flash-lite-free"), gw_key))
    gem_key = os.environ.get("GEMINI_API_KEY", "")
    if gem_key:
        lanes.append(("gemini-direct", os.environ.get(
            "DISTILL_GEMINI_BASE", GEMINI_BASE), os.environ.get(
            "DISTILL_GEMINI_MODEL", "gemini-3.5-flash-lite"), gem_key))
    return lanes


def _chat(base_url, model, key, system, user, timeout=90, max_tokens=400):
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {key}"} if key else {})})
    d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    return d["choices"][0]["message"]["content"]


def card_text(card):
    out = {k: card.get(k) for k in
           ("id", "title", "column", "priority", "review_kind", "tags",
            "brief", "spec", "updated")}
    out["claim"] = (card.get("claim") or {}).get("status")
    out["action_status"] = (card.get("action") or {}).get("status")
    out["requests"] = [{"ask": r.get("ask"), "status": r.get("status")}
                       for r in (card.get("requests") or [])]
    out["comms_tail"] = [f"{m.get('from','?')}: {str(m.get('text',''))[:140]}"
                         for m in (card.get("comms") or [])[-6:]]
    out["today"] = str(datetime.date.today())
    return json.dumps(out, ensure_ascii=False)[:5000]


def pseudo_card(snapshot, card_id=""):
    """Reconstruct a card-view from a frozen bench case snapshot — the
    distiller sees the decision-moment state, NOT the live card (post-
    decision comms would leak proven_right)."""
    s = snapshot or {}
    return {
        "id": card_id or "snapshot",
        "title": s.get("title"),
        "priority": s.get("priority"),
        "review_kind": s.get("review_kind"),
        "tags": s.get("tags"),
        "brief": s.get("brief"),
        "spec": "present" if s.get("spec_present") else "",
        "claim": {"status": s.get("claim")} if s.get("claim") else None,
        "action": {"status": s.get("action_status")}
                  if s.get("action_status") else None,
        "requests": [{"ask": r.get("ask"), "status": "open"}
                     for r in (s.get("open_requests") or [])],
        "comms": [{"at": m.get("at"), "from": m.get("from"),
                   "text": m.get("text")}
                  for m in (s.get("comms_tail") or [])],
    }


def snapshot_key(snapshot):
    """Cache key for a frozen bench snapshot — content hash, since there
    is no live 'updated' to key on."""
    blob = json.dumps(snapshot or {}, sort_keys=True, ensure_ascii=False)
    return "snap:" + hashlib.sha1(blob.encode()).hexdigest()[:12]


def _normalize(brief):
    """Force the fixed template: every slot present as a string,
    needed_move_class one enum value."""
    out = {s: str(brief.get(s) or "").strip() for s in SLOTS}
    nc = out["needed_move_class"].lower()
    out["needed_move_class"] = next(
        (c for c in MOVE_CLASSES if c in nc), "monitor")
    st = out["staleness"].lower()
    out["staleness"] = next(
        (w for w in ("fresh", "stale", "dead") if w in st), "stale")
    return out


def distill(card, lanes):
    """lanes: [(name, base_url, model, api_key)] — try in order."""
    user = card_text(card)
    for name, base, model, key in lanes:
        try:
            text = _chat(base, model, key, PROMPT, user)
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                continue
            brief = _normalize(json.loads(m.group(0)))
            brief["_lane"] = name
            return brief
        except Exception:
            continue
    return {"state": "distill-failed", "_lane": "none"}


def cache_key(card):
    return str(card.get("updated") or snapshot_key(card))


def _sidecar_path(card_id, cache_dir):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(card_id or "anon"))[:120]
    return os.path.join(cache_dir, safe + ".json")


def _sidecar_load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {"card_id": None, "entries": {}}


def sidecar_get(card_id, key, cache_dir=CACHE_DIR):
    d = _sidecar_load(_sidecar_path(card_id, cache_dir))
    return (d.get("entries") or {}).get(key, {}).get("brief")


def sidecar_put(card_id, key, brief, cache_dir=CACHE_DIR):
    os.makedirs(cache_dir, exist_ok=True)
    p = _sidecar_path(card_id, cache_dir)
    d = _sidecar_load(p)
    if d.get("card_id") != card_id:
        d["card_id"] = card_id
    d.setdefault("entries", {})[key] = {
        "lane": brief.get("_lane"), "at": str(datetime.datetime.now())[:16],
        "brief": brief}
    with open(p, "w") as f:
        json.dump(d, f, indent=1)
    return p


def distill_card(card, lanes=None, key=None, cache_dir=CACHE_DIR,
                 refresh=False):
    """The consumer entry: cached sidecar keyed by (card_id, updated) —
    or an explicit key for frozen snapshots."""
    lanes = default_lanes() if lanes is None else lanes
    k = key or cache_key(card)
    cid = card.get("id")
    if not refresh:
        hit = sidecar_get(cid, k, cache_dir)
        if hit:
            return hit
    brief = distill(card, lanes)
    brief["_key"] = k
    if brief.get("_lane") != "none":
        sidecar_put(cid, k, brief, cache_dir)
    return brief


def brief_text(brief):
    """Compact render for prompt injection — the slots, no prose."""
    return "\n".join(f"{s}: {brief.get(s, '')}" for s in SLOTS)


def _board_cards():
    req = urllib.request.Request(API + "/cards")
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())
    return d if isinstance(d, list) else d.get("cards", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cards", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--cache-dir", default=CACHE_DIR)
    args = ap.parse_args()

    lanes = default_lanes()
    print("lanes: " + " -> ".join(n for n, *_ in lanes) or "NONE",
          file=sys.stderr)
    if not lanes:
        print("no lanes configured (need CF_*/ollama/LITELLM_*/GEMINI_API_KEY)",
              file=sys.stderr)
        sys.exit(2)

    todo = args.cards
    byid = {}
    if args.all or todo:
        byid = {c.get("id"): c for c in _board_cards()}
        if args.all:
            todo = sorted(byid)

    if not todo:
        print("usage: distill.py CARD_ID... | --all"); return

    for cid in todo:
        card = byid.get(cid)
        if not card:
            print(f"[{cid}] not on board"); continue
        brief = distill_card(card, lanes, cache_dir=args.cache_dir,
                             refresh=args.refresh)
        if args.json:
            print(json.dumps(brief, ensure_ascii=False, indent=1))
        else:
            print(f"[{cid}] via {brief.get('_lane')}: "
                  f"gates={brief.get('gates')} | "
                  f"asks={str(brief.get('open_asks'))[:60]} | "
                  f"needed={brief.get('needed_move_class')}")


if __name__ == "__main__":
    main()
