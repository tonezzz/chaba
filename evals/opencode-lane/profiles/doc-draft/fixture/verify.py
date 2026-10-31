#!/usr/bin/env python3
"""Held-out verifier for the doc-draft profile. Generic markdown-doc
contract: the emitted document must exist, be non-trivial, be
markdown-shaped, contain no placeholder markers, not parrot the rails
block — and must contain every sentinel string the CARD declares via
action.verify_contains (fetched from board-api; a declared-but-
unverifiable contract fails closed)."""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

MIN_BYTES = 300
BAD_MARKERS = ("TODO", "TBD", "FIXME", "lorem ipsum", "<placeholder",
               "xxx", "placeholder text")
API = os.environ.get("RUNNER_API") or os.environ.get(
    "BOARD_API") or "https://idc03.taila0626a.ts.net:10000"


def _card_sentinels(card_id: str):
    """action.verify_contains / verify_sections from the card itself —
    the declared contract, fetched live (fail closed on fetch error)."""
    if not card_id:
        return None, "no card id"
    try:
        req = urllib.request.Request(f"{API}/cards")
        cards = (json.load(urllib.request.urlopen(req, timeout=20))
                 or {}).get("cards") or []
        for c in cards:
            if c.get("id") == card_id:
                a = c.get("action") or {}
                sent = (a.get("verify_contains")
                        or a.get("verify_sections") or [])
                return [str(s) for s in sent if str(s).strip()], ""
        return None, f"card {card_id} not found"
    except Exception as e:
        return None, f"card fetch failed: {e}"


def verify(run_dir):
    """run_dir holds manifest.json + artifact.out (the emitted text)."""
    rd = Path(run_dir)
    checks = {}
    try:
        man = json.loads((rd / "manifest.json").read_text())
        text = (rd / "artifact.out").read_text()
    except Exception as e:
        return {"verdict": "fail",
                "checks": {"artifact readable": False, "error": str(e)}}
    env = (man.get("envelope") or {})

    checks["artifact non-empty"] = len(text.strip()) >= MIN_BYTES
    stripped = text.strip()
    checks["markdown shape"] = bool(
        re.search(r"^#{1,3} \S", stripped, re.M))
    checks["not rails echo"] = (
        not stripped.startswith("Rails: you are processing")
        and "Rails: you are processing" not in stripped[:400])
    # word-boundary match — 'todowrite'/'read_todo' tool names must not
    # trip placeholder markers (artwrite3 pilot 1793410460 false-fail)
    bad = [m for m in BAD_MARKERS
           if re.search(r"(?i)(?<![a-z])" + re.escape(m) + r"(?![a-z])",
                        stripped)]
    checks["no placeholder markers"] = not bad
    if bad:
        checks["markers found"] = bad

    sentinels, serr = _card_sentinels(str(env.get("card") or ""))
    if sentinels:
        missing = [s for s in sentinels if s not in text]
        checks["verify_contains present"] = not missing
        if missing:
            checks["missing sentinels"] = missing
    elif sentinels is None:
        # declared contract unreadable — cannot verify; fail closed
        # only when the card actually declares sentinels we can't read
        checks["sentinel fetch"] = False
        checks["sentinel error"] = serr
    else:
        checks["verify_contains declared"] = True  # none declared — n/a

    verdict = "pass" if all(v is True for v in checks.values()
                            if isinstance(v, bool)) else "fail"
    return {"verdict": verdict, "checks": checks,
            "artifact": env.get("artifact", {}).get("path", "?")}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1] if len(sys.argv) > 1
                            else os.getcwd()), indent=1))
