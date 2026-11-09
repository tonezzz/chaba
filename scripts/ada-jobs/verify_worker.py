#!/usr/bin/env python3
"""verify_worker.py — the 'ada-jobs-verify' micro-entity (card
ada-t4-micro-entity-design / ADA-1091).

First T4 lane: Ada finishes ONE bounded card class herself —
verify/observe cards. Loop: pull eligible review cards -> give her the
card -> she returns ONE action -> the matrix is enforced IN CODE -> the
action lands via board-api as from: ada audit lines.

Opt-in contract (never touches an unmarked card):
  column=review AND review_kind=verify AND tag 'ada-verify'
  AND NOT priority:high AND NOT review_kind:decide AND no prod/security tags
  AND no open requests[]

Her allowed actions (all already inside kanban-tool authority):
  close    review->done — only when she supplies evidence= (a checkable
           fact she verified this run); refused on priority:high /
           decide / prod-security by BOTH prompt and code.
  comment  post an evidence/status comms line.
  request  defer to Tony — raise a board request (her safe failure mode).
  skip     nothing to do this pass.

Default brain: CF Workers AI llama-3.3-70b (free, always-on) —
override with --model/--base-url/--api-key-env (e.g. local ollama
llama3.2:3b, the current bench gate-passer).

Usage:
  verify_worker.py --once                 # process up to --max cards once
  verify_worker.py --once --card <id>     # one named card (probe/pilot)
  verify_worker.py --dry-run --card <id>  # decide but don't write
  verify_worker.py --with-brief ...       # attach a job brief (SSOT+KB+
                                          # similar-card outcomes) to her turn
"""
import argparse, json, os, re, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "bench", "card-judgment"))

API = os.environ.get("BOARD_API",
                     "https://idc03.taila0626a.ts.net:10000")
CF_BASE = "https://api.cloudflare.com/client/v4/accounts/%s/ai/v1"
BLOCKED_TAGS = {"prod", "security", "prod-security", "production"}

CLEANUP_PROMPT = """You are Ada's ada-jobs-cleanup lane — a scoped sweeper
assessing ONE old kanban card for board hygiene. Your whole authority
(enforced in code after you):

- comment — post [cleanup] verdict + one-line reason (stale|superseded|
  dead|alive). The assessment IS the deliverable.
- close   — ONLY review-column cards that are clearly dead WITH evidence
  (e.g. superseded by card X, work verified done elsewhere, surface
  retired per docs). NEVER backlog cards, NEVER priority:high, NEVER
  review_kind:decide — those are Tony's calls.
- request — dead-ish but not provable? defer to Tony with a close/keep
  question. When unsure, this is the right move.
- skip    — card is alive/current; no action needed.

You may NEVER delete/archive anything — closes and requests only.
Evidence or it didn't happen. Card is below. Answer ONLY JSON:
{"action":"close|comment|request|skip","verdict":"dead|stale|alive",
"evidence":"concrete proof","comment":"[cleanup] ...","request":"question for Tony"}
"""

PROMPT = """You are Ada's ada-jobs-verify lane — a scoped worker finishing ONE
verify-class kanban card. Your whole authority (enforced in code after you):

- close   — move review->done ONLY with evidence: a checkable fact you
            verified (HTTP status, service state, file/field present).
            HARD REFUSED on priority:high, review_kind:decide, prod/security.
- comment — post an evidence/status note. The evidence IS the comment.
- request — defer to Tony (a request he answers on the board). When in
            ANY doubt, this is the right move — never guess.
- skip    — genuinely nothing to verify right now.

Card is below. If live_checks is present it is REAL probe output you ran
this turn (url/status/body) — cite it as your evidence, never invent a
check you didn't run. Answer ONLY JSON:
{"action":"close|comment|request|skip","evidence":"the checkable fact",
"comment":"text to post","request":"the question for Tony"}
"""


def post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=75).read())


def get_cards():
    req = urllib.request.Request(API + "/cards")
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())
    return d if isinstance(d, list) else d.get("cards", [])


def eligible(card):
    if card.get("column") != "review" or card.get("review_kind") != "verify":
        return False
    tags = set(card.get("tags") or [])
    if "ada-verify" not in tags and card.get("ada_job") != "verify":
        return False
    if card.get("priority") == "high" or card.get("review_kind") == "decide":
        return False
    if tags & BLOCKED_TAGS:
        return False
    reqs = [r for r in (card.get("requests") or [])
            if str(r.get("status", "")).lower() not in
            ("answered", "resolved", "closed")]
    return not reqs


PROBE_ALLOW = re.compile(
    r"https?://(127\.0\.0\.1|localhost|100\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|"
    r"[a-z0-9.-]+\.taila0626a\.ts\.net)(:\d+)?(/[^\s'\"`]*)?", re.I)


def probe_urls(card, limit=3, timeout=8):
    """Bounded check tool: GET each http(s) URL the card itself declares,
    tailnet/loopback/LAN hosts only. Read-only, fixed allowlist — the
    model can't steer it to arbitrary hosts."""
    text = " ".join(str(card.get(k) or "") for k in ("spec", "brief", "note"))
    text += " ".join(str(m.get("text", "")) for m in (card.get("comms") or [])[-8:])
    found, seen = [], set()
    for m in PROBE_ALLOW.finditer(text):
        u = m.group(0).rstrip(".,);]")
        if u in seen:
            continue
        seen.add(u)
        try:
            r = urllib.request.urlopen(
                urllib.request.Request(u, headers={"User-Agent": "ada-verify"}),
                timeout=timeout)
            body = r.read(300).decode("utf-8", "replace")
            found.append({"url": u, "status": r.status, "body": body[:200]})
        except Exception as e:
            found.append({"url": u, "status": "ERR", "body": str(e)[:160]})
        if len(found) >= limit:
            break
    return found


UNIT_RE = re.compile(r"\b([a-zA-Z0-9_.@-]+\.(?:service|timer|socket))\b")
PATH_RE = re.compile(r"(?<![\w.-])(/[a-zA-Z0-9_./~-]{8,})")


def probe_local(card, limit=6, timeout=6):
    """Bounded local checks: systemd unit state + file existence for
    units/paths the card itself declares. Read-only, no shell — the model
    cannot inject commands."""
    import subprocess, os
    text = " ".join(str(card.get(k) or "") for k in ("spec", "brief", "note"))
    text += " ".join(str(m.get("text", "")) for m in (card.get("comms") or [])[-8:])
    out = []
    for u in dict.fromkeys(UNIT_RE.findall(text)):
        try:
            r = subprocess.run(["systemctl", "--user", "is-active", u],
                               capture_output=True, text=True, timeout=timeout)
            state = r.stdout.strip() or r.stderr.strip() or "unknown"
        except Exception as e:
            state = f"ERR {e}"
        out.append({"unit": u, "state": state})
        if len(out) >= limit:
            return out
    for p in dict.fromkeys(PATH_RE.findall(text)):
        p = os.path.expanduser(p.strip().rstrip(".,);]"))
        if not p.startswith(("/home/tony/", "/srv/", "/tmp/", "/etc/")):
            continue
        out.append({"path": p, "exists": os.path.exists(p)})
        if len(out) >= limit:
            break
    return out


def llm_action(card, base_url, model, key, system=PROMPT, brief=None,
               distilled=None):
    snap = {k: card.get(k) for k in
            ("id", "title", "brief", "note", "spec", "expected_goals")}
    snap["comms_tail"] = (card.get("comms") or [])[-6:]
    probes = probe_urls(card) + probe_local(card)
    if probes:
        snap["live_checks"] = probes
    if brief:
        snap["job_brief"] = brief
    if distilled:
        snap["distilled_brief"] = distilled
    body = {"model": model, "temperature": 0, "max_tokens": 800,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(
                             snap, ensure_ascii=False)[:6000]}]}
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {key}"} if key else {})})
    d = json.loads(urllib.request.urlopen(req, timeout=180).read())
    text = d["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {"action": "skip",
                                           "comment": f"unparseable: {text[:120]}"}


def enforce(action, card):
    """The authority matrix in code — the prompt can't widen it."""
    a = (action.get("action") or "skip").lower()
    if a == "close":
        if card.get("priority") == "high" or card.get("review_kind") == "decide":
            return "request", {"ask": "close requested but card is "
                "priority:high/decide — your call", "options": ["close", "hold"]}
        if not (action.get("evidence") or "").strip():
            return "comment", {"text": "[verify] attempted close without "
                "evidence — refused by matrix"}
        return "close", {"evidence": action["evidence"],
                         "comment": action.get("comment")}
    if a in ("comment", "request", "skip"):
        return a, action
    return "skip", {}


import datetime


def _age_days(card):
    try:
        up = str(card.get("updated") or "")[:10]
        d = datetime.date.fromisoformat(up)
        return (datetime.date.today() - d).days
    except Exception:
        return 0


def eligible_cleanup(card, min_age=21):
    """Old cards she may assess. Hard exclusions: done, claimed,
    priority:high, review_kind:decide, open requests — those are Tony's."""
    if card.get("column") not in ("backlog", "review"):
        return False
    if _age_days(card) < min_age:
        return False
    if card.get("priority") == "high" or card.get("review_kind") == "decide":
        return False
    if card.get("claim"):
        return False
    reqs = [r for r in (card.get("requests") or [])
            if str(r.get("status", "")).lower() not in
            ("answered", "resolved", "closed")]
    return not reqs


def run_once(args):
    cards = get_cards()
    cleanup = args.sweep == "cleanup"
    if args.card:
        targets = [c for c in cards if c.get("id") == args.card]
    elif cleanup:
        targets = [c for c in cards if eligible_cleanup(c, args.min_age)][:args.max]
    else:
        targets = [c for c in cards if eligible(c)][:args.max]
    if not targets:
        print("no eligible cards")
        return
    elig = eligible_cleanup if cleanup else (lambda c: eligible(c))
    for card in targets:
        cid = card.get("id")
        print(f"[card] {cid} (age {_age_days(card)}d)")
        if not elig(card):
            print("  not eligible under matrix — skip"); continue
        brief = None
        if args.with_brief:
            try:
                import brief_builder
                b = brief_builder.build_brief(card,
                                              exclude_card_ids={cid})
                brief = brief_builder.render(b)
                print("  -- job brief --")
                for line in brief.splitlines():
                    print(f"  {line}")
            except Exception as e:
                print(f"  brief build failed ({str(e)[:80]}) — "
                      "turn runs without it")
        distilled = None
        if args.with_distill:
            try:
                import distill as card_distill
                db = card_distill.distill_card(card)
                distilled = {s: db.get(s, "") for s in card_distill.SLOTS}
                print(f"  -- distilled ({db.get('_lane')}) --")
                print("  " + card_distill.brief_text(db).replace("\n", "\n  "))
            except Exception as e:
                print(f"  distill failed ({str(e)[:80]}) — turn runs without it")
        try:
            raw = llm_action(card, args.base_url, args.model, args.api_key,
                             system=CLEANUP_PROMPT if cleanup else PROMPT,
                             brief=brief, distilled=distilled)
        except Exception as e:
            print(f"  primary brain failed ({str(e)[:80]}) — trying fallback")
            raw = llm_action(card, args.fallback_base_url,
                             args.fallback_model, "",
                             system=CLEANUP_PROMPT if cleanup else PROMPT,
                             brief=brief, distilled=distilled)
        if cleanup and (raw.get("action") or "").lower() == "close" \
                and card.get("column") != "review":
            raw["action"] = "request"   # backlog closes are Tony's — degrade to ask
            raw["request"] = raw.get("request") or \
                "cleanup suggests dead — close or keep?"
        action, payload = enforce(raw, card)
        print(f"  ada decides: {action} -> {json.dumps(payload)[:160]}")
        if args.dry_run:
            print("  dry-run — not writing"); continue
        if action == "close":
            post("/comment", {"id": cid, "from": "ada",
                 "text": f"[verify] {payload['comment'] or payload['evidence']} "
                         f"(evidence: {payload['evidence'][:180]})"})
            post("/action", {"id": cid, "do": "close", "from": "ada",
                             "evidence": payload["evidence"]})
            print("  closed review->done with evidence")
        elif action == "comment":
            post("/comment", {"id": cid, "from": "ada",
                 "text": f"[verify] {payload.get('comment') or payload.get('text','')}"})
        elif action == "request":
            body = {"id": cid, "from": "ada",
                    "ask": payload.get("ask") or payload.get("request") or "needs Tony"}
            opts = payload.get("options") or [
                {"id": "close", "label": "Close — cleanup verdict is right"},
                {"id": "keep", "label": "Keep — still alive, dismiss verdict"}]
            body["options"] = opts
            sug = payload.get("suggested")
            if sug:
                body["suggested"] = sug
            post("/request", body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--card", default="")
    ap.add_argument("--sweep", choices=["", "cleanup"], default="")
    ap.add_argument("--with-brief", action="store_true",
                    help="assemble a job brief (SSOT+KB+similar-card "
                    "outcomes) before her turn and show it")
    ap.add_argument("--with-distill", action="store_true",
                    help="attach the fixed-slot distilled brief "
                    "(card-distill-free-lane) to her turn")
    ap.add_argument("--min-age", type=int, default=21)
    ap.add_argument("--max", type=int, default=3)
    ap.add_argument("--model", default=os.environ.get(
        "ADA_JOBS_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"))
    ap.add_argument("--base-url", default=os.environ.get(
        "ADA_JOBS_BASE_URL",
        CF_BASE % os.environ.get("CF_API_ACCOUNT_ID", "MISSING")))
    ap.add_argument("--api-key-env", default="CF_API_WORKER_TOKEN")
    ap.add_argument("--fallback-base-url", default=os.environ.get(
        "ADA_JOBS_FALLBACK_URL", "http://127.0.0.1:11434/v1"))
    ap.add_argument("--fallback-model", default=os.environ.get(
        "ADA_JOBS_FALLBACK_MODEL", "llama3.2:3b"))
    args = ap.parse_args()
    args.api_key = os.environ.get(args.api_key_env, "")
    run_once(args)


if __name__ == "__main__":
    main()
