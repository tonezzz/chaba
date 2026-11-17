#!/usr/bin/env python3
"""report-comms-narrate.py — narrate the comms digest onto the TG lanes.

Layer over the comms-digest-builder (card narrated-comms-digest): after
daily-brief publishes ada-cms-pages/tony-team-digest, each live lane reads
the digest aloud in-channel in its own persona voice — ada :8911 (Tony DM),
kaewta :8913 (KK-HA group). chaba's lane is pending (LINE blocked — Yomi
token revoked) and is skipped until a relay exists. Lane contract:
docs/kb/msg-lane-standard.md — outbound only via loopback POST /send.

Voice text comes from the LiteLLM gateway (scripts/ada/litellm_chat.py,
mddb-gemini.env creds) on the `chat` alias — gemini-3.5-flash normally,
with the ordered free -> OpenRouter -> lite -> local fallback chain, so a
billing/quota outage never silences the channel (ssot.llm-gateway.yml —
the OR leg is the 2026-10-11-proven fallback). A lane that still can't
produce or send text posts '[<tag>] (digest narration failed)' on its own
channel — never silence (ssot.comms-digest.yml narration_delivery).

Input: --stdin / --md-file, else the live CMS page (mddb ada-cms-pages get
tony-team-digest). report-daily-brief.py pipes the freshly rendered digest
on stdin after the comms publish. Standalone use:

  report-comms-narrate.py --edition evening            # fetch page, narrate
  report-comms-narrate.py --md-file x.md --print       # render only
  report-comms-narrate.py --lanes ada                  # one lane

Env:
  COMMS_NARRATE_MODEL       gateway alias, default "chat"
  COMMS_NARRATE_LANES       comma list, default all live lanes
  COMMS_NARRATE_PAGE_URL    detail link (default idc03 tailnet cms viewer)
  COMMS_NARRATE_SEND_<LANE> /send URL override per lane
  COMMS_NARRATE_CHAT_<LANE> explicit chat_id per lane (default = relay's
                            first allowed chat — Tony DM / KK-HA group)
  MDDB_BASE_URL             default http://100.102.134.91:11027/v1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "ada"))
import litellm_chat  # noqa: E402

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11027/v1").rstrip("/")
CMS_SLUG = "tony-team-digest"
PAGE_URL = os.environ.get(
    "COMMS_NARRATE_PAGE_URL",
    "https://idc03.taila0626a.ts.net/cms/#/tony-team-digest")
MODEL = os.environ.get("COMMS_NARRATE_MODEL", "chat")
MAX_LINES = 10  # format contract, incl. the [tag] line and link line

# Lane registry — mirrors docs/kb/msg-lane-standard.md. state:pending
# lanes are skipped with a note until their relay exists.
LANES = {
    "ada": {
        "send": "http://127.0.0.1:8911/send",
        "tag": "ada",
        "voice": ("You are Ada, Tony's home AI assistant — warm, direct, "
                  "a colleague catching him up. Mostly English; a natural "
                  "Thai phrase is fine. Brief, no fluff."),
        "link_lede": "full digest:",
    },
    "kaewta": {
        "send": "http://127.0.0.1:8913/send",
        "tag": "kaewta",
        "voice": ("You are Kaewta (แก้วตา), the KK household's assistant — "
                  "warm, gentle, family register. Write mostly in Thai, "
                  "short friendly lines."),
        "link_lede": "ดูฉบับเต็ม:",
    },
}
PENDING = {"chaba": "LINE lane blocked (Yomi token revoked); no TG relay"}

PROMPT = """{voice}

Below is the "{edition}" edition of the Tony↔Team comms digest — what Tony
asked across all channels (board, TG, voice), what the team answered or
shipped, and what is still open.

Narrate it for your channel in at most {max_lines} lines, spoken register —
like you'd tell it, not read a table. Cover: the asks, what landed, and
honestly what is still waiting. Plain lines only — no headers, no bullets,
no markdown, no [tag] prefix, no link (the caller adds both).

DIGEST:
{digest}"""


def fetch_page() -> str | None:
    """Live ada-cms-pages/tony-team-digest markdown — the published surface
    the narration points at."""
    req = urllib.request.Request(
        f"{MDDB}/get",
        data=json.dumps({"collection": "ada-cms-pages", "key": CMS_SLUG,
                         "lang": "en"}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        doc = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as e:
        print(f"warn: CMS get {CMS_SLUG} failed ({e})", file=sys.stderr)
        return None
    return (doc or {}).get("contentMd") or None


def narrate(lane: str, digest: str, edition: str) -> str | None:
    """One gateway chat call -> raw narration text, or None."""
    cfg = LANES[lane]
    prompt = PROMPT.format(voice=cfg["voice"], edition=edition,
                           max_lines=MAX_LINES - 1,
                           digest=digest[:8000])
    # max_tokens is high on purpose: the `chat` chain's gemini upstreams
    # are thinking models — ~10x of the budget is reasoning tokens, so a
    # small cap truncates the visible reply mid-line (seen live 2026-11-17).
    return litellm_chat.chat(
        prompt, model=MODEL, temperature=0.4, max_tokens=3000,
        timeout=120, label=f"narrate-{lane}",
        tags=f"service=comms-narrate,job=daily-brief,lane={lane}")


def compose(lane: str, text: str) -> str:
    """Model text -> the posted message: '[<tag>] ' on the first line,
    capped at MAX_LINES, detail link appended."""
    body = re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip())
    body = re.sub(r"^\[(?:ada|kaewta|chaba)\]\s*", "", body)
    lines = [l.strip().strip('"\'').strip()
             for l in body.splitlines() if l.strip()]
    lines = lines[:MAX_LINES - 2]
    cfg = LANES[lane]
    out = [f"[{cfg['tag']}] {lines[0] if lines else 'digest narration'}"]
    out += lines[1:]
    out.append(f"{cfg['link_lede']} {PAGE_URL}")
    return "\n".join(out)


def send(lane: str, text: str) -> bool:
    cfg = LANES[lane]
    url = os.environ.get(f"COMMS_NARRATE_SEND_{lane.upper()}",
                         cfg["send"])
    payload = {"text": text}
    chat = os.environ.get(f"COMMS_NARRATE_CHAT_{lane.upper()}")
    if chat:
        payload["chat_id"] = chat
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        print(f"warn: /send {lane} failed ({e})", file=sys.stderr)
        return False


def run_lane(lane: str, digest: str, edition: str,
             print_only: bool) -> bool:
    """Generate + post for one lane. A failed lane posts '(digest
    narration failed)' on its own channel — never silence."""
    text = narrate(lane, digest, edition)
    if text:
        msg = compose(lane, text)
    else:
        msg = (f"[{LANES[lane]['tag']}] (digest narration failed — "
               "model unavailable)")
    if print_only:
        print(f"--- {lane} -> {LANES[lane]['send']} ---\n{msg}\n")
        return text is not None
    ok = send(lane, msg)
    print(f"narrate {lane}: {'sent' if ok else 'FAILED'}")
    return ok


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--edition", default=os.environ.get(
        "COMMS_NARRATE_EDITION", "latest"))
    p.add_argument("--lanes", default=os.environ.get(
        "COMMS_NARRATE_LANES", ",".join(LANES)))
    p.add_argument("--md-file", type=str, default=None)
    p.add_argument("--stdin", action="store_true")
    p.add_argument("--print", dest="print_only", action="store_true",
                   help="render messages, never POST")
    args = p.parse_args()

    if args.stdin:
        digest = sys.stdin.read()
    elif args.md_file:
        digest = open(args.md_file).read()
    else:
        digest = fetch_page() or ""
    if not digest.strip():
        print("warn: empty digest — nothing to narrate", file=sys.stderr)
        return 0

    lanes = [l.strip() for l in args.lanes.split(",") if l.strip()]
    for name in PENDING:
        if name in lanes:
            print(f"narrate {name}: skipped — {PENDING[name]}")
            lanes.remove(name)
    unknown = [l for l in lanes if l not in LANES]
    for u in unknown:
        print(f"warn: unknown lane {u}", file=sys.stderr)
    results = [run_lane(l, digest, args.edition, args.print_only)
               for l in lanes if l in LANES]
    # best-effort: a lane failure is reported, never a script failure
    return 0


if __name__ == "__main__":
    sys.exit(main())
