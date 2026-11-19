#!/usr/bin/env python3
"""consultant_worker.py — the consultant-lane drainer (card
ada-consultant-tier / ADA-1206, tiered judgment).

Ada's bounded lanes (verify_worker --consultant) defer judgment-call
boundary cards to `to: consultant` board requests instead of straight to
Tony. This worker drains them with the bench-qualified consultant brain —
a bigger model under the SAME composite the card-judgment bench scores
(enforce matrix in code + job brief context). Tony only sees what the
consultant can't resolve.

Contract per open `to: consultant` request:
  input  — card snapshot + Ada's deferred ask + job brief
            (brief_builder: related SSOT/KB + top-3 similar done-cards
            with proven-right outcomes)
  output — {"action": "answer|comment|close|escalate", "verdict",
            "confidence" 0..1, "evidence", "comment",
            "request"/"options"/"suggested" for escalate}
    answer   — resolve the deferral: /respond the request with the
               verdict, post a [consultant] comms line. The card's own
               rails take it from there (awaiting_action triage is the
               same as a Tony answer).
    comment  — verified something worth recording but no verdict yet:
               post the note, leave the request open.
    close    — review-column cards only, evidence required, refused on
               priority:high / review_kind:decide / prod|security tags —
               the matrix does not widen for the consultant.
    escalate — the call is genuinely Tony's (ambiguous direction, spend,
               irreversible, gated class, or confidence <
               --min-confidence): raise to:tony with the consultant's
               framing + suggested pick, and answer the consultant
               request noting the escalation.

INERT by design — it only touches cards carrying an open to:consultant
request; with verify_worker's lane off (default) that set is empty.

Default brain: model_name `consultant` on the LiteLLM gateway (->
kk-mac qwen2.5:32b per the consultant-* bench runs); override with
--model/--base-url/--api-key-env (e.g. direct ollama for bench reruns).

Usage:
  consultant_worker.py --once                # drain up to --max requests
  consultant_worker.py --once --card <id>    # one named card
  consultant_worker.py --dry-run --card <id> # decide but don't write
"""
import argparse, json, os, re, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API = os.environ.get("BOARD_API",
                     "https://idc03.taila0626a.ts.net:10000")
LITELLM = "http://100.102.134.91:4000/v1"
BLOCKED_TAGS = {"prod", "security", "prod-security", "production"}

PROMPT = """You are the consultant tier — a stronger reviewer between Ada's
bounded lanes and Tony, called on ONE kanban card she deferred. Her
deferral ask is in deferred_ask. Resolve it if you can — Tony should only
see what genuinely needs him.

- answer   — you have a verdict: return it with confidence 0..1. Your
             answer resolves the deferral; the card's normal rails act on
             it exactly like a Tony answer.
- comment  — you verified a fact worth recording but the call itself is
             still open. Evidence note only.
- close    — ONLY review-column cards where evidence proves the work is
             finished (a checkable fact). Refused on priority:high,
             review_kind:decide, prod/security — those stay Tony's.
- escalate — the call is genuinely Tony's: ambiguous direction, spend,
             irreversible ops, gated classes, or your confidence is low.
             Escalation is for real gates, not discomfort — give Tony your
             best recommendation in `suggested` so he answers in one word.

Card + her ask below. job_brief, when present, is retrieved context —
past outcomes are evidence, not authority. Answer ONLY JSON:
{"action":"answer|comment|close|escalate","verdict":"one-line call",
"confidence":0.0,"evidence":"checkable fact or empty",
"comment":"[consultant] note for the card",
"request":"the reframed ask for Tony (escalate only)",
"options":["a","b"],"suggested":"a"}
"""


def post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=75).read())


def get_cards():
    req = urllib.request.Request(API + "/cards")
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())
    return d if isinstance(d, list) else d.get("cards", [])


def consultant_requests(card):
    """Open requests deferred to the consultant lane."""
    return [r for r in (card.get("requests") or [])
            if r.get("to") == "consultant"
            and str(r.get("status", "")).lower() not in
            ("answered", "resolved", "closed")]


def llm_verdict(card, req, base_url, model, key, brief=None):
    snap = {k: card.get(k) for k in
            ("id", "title", "column", "priority", "review_kind",
             "brief", "note", "spec", "expected_goals", "tags")}
    snap["comms_tail"] = (card.get("comms") or [])[-6:]
    snap["deferred_ask"] = {"id": req.get("id"), "ask": req.get("ask"),
                            "options": req.get("options"),
                            "from": req.get("from")}
    if brief:
        snap["job_brief"] = brief
    body = {"model": model, "temperature": 0, "max_tokens": 800,
            "messages": [{"role": "system", "content": PROMPT},
                         {"role": "user", "content": json.dumps(
                             snap, ensure_ascii=False)[:6000]}]}
    r = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {key}"} if key else {})})
    d = json.loads(urllib.request.urlopen(r, timeout=240).read())
    text = d["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {"action": "escalate",
        "verdict": "unparseable consultant output",
        "request": text[:200], "confidence": 0}


def gated(card):
    return (card.get("priority") == "high"
            or card.get("review_kind") == "decide"
            or bool(set(card.get("tags") or []) & BLOCKED_TAGS))


def enforce(raw, card):
    """The authority matrix in code — the consultant's prompt can't widen
    it. Confidence below threshold degrades answer/close to escalate."""
    a = (raw.get("action") or "escalate").lower()
    try:
        conf = float(raw.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    if a == "close":
        if gated(card) or card.get("column") != "review":
            a = "escalate"
        elif not (raw.get("evidence") or "").strip():
            a = "escalate"
    if a == "answer" and conf < ENFORCE_MIN_CONF:
        a = "escalate"
    if a not in ("answer", "comment", "close", "escalate"):
        a = "comment"
    return a, conf


ENFORCE_MIN_CONF = 0.7


def run_once(args):
    global ENFORCE_MIN_CONF
    ENFORCE_MIN_CONF = args.min_confidence
    cards = get_cards()
    targets = []
    for c in cards:
        if args.card and c.get("id") != args.card:
            continue
        for r in consultant_requests(c):
            targets.append((c, r))
        if len(targets) >= args.max:
            break
    if not targets:
        print("no open to:consultant requests")
        return
    for card, req in targets[:args.max]:
        cid = card.get("id")
        print(f"[card] {cid} req={req.get('id')}: {str(req.get('ask'))[:80]}")
        brief = None
        if not args.no_brief:
            try:
                import brief_builder
                b = brief_builder.build_brief(card, exclude_card_ids={cid})
                brief = brief_builder.render(b)
                print("  -- job brief --")
                for line in brief.splitlines():
                    print(f"  {line}")
            except Exception as e:
                print(f"  brief build failed ({str(e)[:80]}) — "
                      "verdict runs without it")
        try:
            raw = llm_verdict(card, req, args.base_url, args.model,
                              args.api_key, brief=brief)
        except Exception as e:
            print(f"  primary brain failed ({str(e)[:80]}) — trying fallback")
            try:
                raw = llm_verdict(card, req, args.fallback_base_url,
                                  args.fallback_model, "", brief=brief)
            except Exception as e2:
                print(f"  fallback failed too ({str(e2)[:80]}) — "
                      "leaving request open")
                continue
        action, conf = enforce(raw, card)
        print(f"  consultant: {action} conf={conf} "
              f"verdict={str(raw.get('verdict'))[:100]}")
        if args.dry_run:
            print("  dry-run — not writing"); continue
        comment = raw.get("comment") or raw.get("verdict") or ""
        if action == "comment":
            if not comment.strip():
                print("  empty comment — leaving request open"); continue
            post("/comment", {"id": cid, "from": "consultant",
                 "text": f"[consultant] {comment}"})
            continue
        if action == "close":
            post("/comment", {"id": cid, "from": "consultant",
                 "text": f"[consultant] {comment} "
                         f"(evidence: {raw['evidence'][:180]})"})
            post("/action", {"id": cid, "do": "close", "from": "consultant",
                             "evidence": raw["evidence"]})
        if action in ("answer", "close"):
            post("/respond", {"id": cid, "from": "consultant",
                              "request_id": req["id"],
                              "answer": str(raw.get("verdict") or
                                            comment)[:500]})
            print(f"  resolved {req.get('id')}")
            continue
        # escalate — re-raise to Tony with the consultant's framing
        ask = raw.get("request") or req.get("ask") or "needs Tony"
        esc = {"id": cid, "from": "consultant",
               "ask": f"[consultant escalated] {ask}",
               "options": raw.get("options") or ["proceed", "hold"]}
        if raw.get("suggested"):
            esc["suggested"] = raw["suggested"]
        try:
            post("/request", esc)
        except Exception as e:
            print(f"  tony escalation failed ({str(e)[:80]}) — "
                  "consultant request stays open")
            continue
        post("/respond", {"id": cid, "from": "consultant",
                          "request_id": req["id"],
                          "answer": f"escalated to Tony — "
                                    f"{str(raw.get('verdict'))[:300]}"})
        post("/comment", {"id": cid, "from": "consultant",
             "text": f"[consultant] escalated (conf {conf}): {comment[:200]}"})
        print(f"  escalated {req.get('id')} -> tony")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--card", default="")
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--min-confidence", type=float, default=0.7,
                    help="below this an 'answer' degrades to escalate")
    ap.add_argument("--no-brief", action="store_true",
                    help="skip the job brief (bench ablation)")
    ap.add_argument("--model", default=os.environ.get(
        "CONSULTANT_MODEL", "consultant"))
    ap.add_argument("--base-url", default=os.environ.get(
        "CONSULTANT_BASE_URL", LITELLM))
    ap.add_argument("--api-key-env", default="LITELLM_KEY_CHABA")
    ap.add_argument("--fallback-base-url", default=os.environ.get(
        "CONSULTANT_FALLBACK_URL", "http://kk-mac:11434/v1"))
    ap.add_argument("--fallback-model", default=os.environ.get(
        "CONSULTANT_FALLBACK_MODEL", "qwen2.5:32b"))
    args = ap.parse_args()
    args.api_key = os.environ.get(args.api_key_env, "")
    run_once(args)


if __name__ == "__main__":
    main()
