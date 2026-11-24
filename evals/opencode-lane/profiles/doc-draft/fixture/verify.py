#!/usr/bin/env python3
"""Held-out verifier for the doc-draft profile. Generic markdown-doc
contract: the emitted document must exist, be non-trivial, be
markdown-shaped, contain no placeholder markers, not parrot the rails
block — and must satisfy every check the CARD declares in its action
block (fetched live from board-api; a declared-but-unverifiable
contract fails closed):

  action.verify_contains / verify_sections — literal sentinel strings,
      ALL must appear verbatim (the OPS-1014 gap: sentinels alone are
      mechanical, not semantic — pick strings only a correct
      deliverable contains).
  action.verify_regex — regex patterns, ALL must match the artifact.
  action.verify_min_terms — {terms: [...], at_least: N} keyword
      coverage: at least N distinct terms must appear
      (case-insensitive); a bare list means all terms required.
"""
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
CONTRACT_KEYS = ("verify_contains", "verify_sections", "verify_regex",
                 "verify_min_terms")


def _str_list(v):
    """Normalize a declared string-or-list-of-strings to a clean list."""
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    return [str(s).strip() for s in v if str(s).strip()]


def _min_terms_spec(v):
    """verify_min_terms -> (terms, at_least). Dict form:
    {terms: [...], at_least: N} (at_least defaults to all terms). Bare
    list = all terms required. Raises ValueError on a bad spec."""
    if isinstance(v, dict):
        terms = _str_list(v.get("terms"))
        raw = v.get("at_least")
        at_least = len(terms) if raw is None else int(raw)
    else:
        terms = _str_list(v)
        at_least = len(terms)
    return terms, at_least


def _card_contract(card_id: str):
    """The card's declared verify contract (action.verify_*) — fetched
    live from board-api (fail closed on fetch error)."""
    if not card_id:
        return None, "no card id"
    try:
        req = urllib.request.Request(f"{API}/cards")
        cards = (json.load(urllib.request.urlopen(req, timeout=20))
                 or {}).get("cards") or []
        for c in cards:
            if c.get("id") == card_id:
                a = c.get("action") or {}
                return {k: a.get(k) for k in CONTRACT_KEYS
                        if a.get(k) not in (None, "", [], {})}, ""
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

    contract, cerr = _card_contract(str(env.get("card") or ""))
    if contract is None:
        # declared contract unreadable — cannot verify; fail closed
        checks["contract fetch"] = False
        checks["contract error"] = cerr
    elif not contract:
        checks["verify contract declared"] = True  # none — n/a
    else:
        sent = (_str_list(contract.get("verify_contains"))
                or _str_list(contract.get("verify_sections")))
        if sent:
            missing = [s for s in sent if s not in text]
            checks["verify_contains present"] = not missing
            if missing:
                checks["missing sentinels"] = missing
        rx = _str_list(contract.get("verify_regex"))
        if rx:
            misses, uncompilable = [], []
            for pat in rx:
                try:
                    if not re.search(pat, text):
                        misses.append(pat)
                except re.error:
                    uncompilable.append(pat)
            checks["verify_regex matched"] = not misses \
                and not uncompilable
            if misses:
                checks["regex misses"] = misses
            if uncompilable:
                checks["regex uncompilable"] = uncompilable
        if contract.get("verify_min_terms") not in (None, "", [], {}):
            try:
                terms, at_least = _min_terms_spec(
                    contract["verify_min_terms"])
            except (TypeError, ValueError):
                terms, at_least = [], -1
            if not terms or at_least <= 0:
                # declared but vacuous/unsatisfiable — fail closed
                checks["verify_min_terms coverage"] = False
                checks["min_terms spec"] = (
                    f"terms={len(terms)} at_least={at_least}")
            else:
                low = text.lower()
                hit = [t for t in terms if t.lower() in low]
                miss = [t for t in terms if t.lower() not in low]
                checks["verify_min_terms coverage"] = \
                    len(hit) >= at_least
                checks["terms matched"] = \
                    f"{len(hit)}/{len(terms)} (need {at_least})"
                if len(hit) < at_least:
                    checks["terms missed"] = miss

    verdict = "pass" if all(v is True for v in checks.values()
                            if isinstance(v, bool)) else "fail"
    return {"verdict": verdict, "checks": checks,
            "artifact": env.get("artifact", {}).get("path", "?")}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1] if len(sys.argv) > 1
                            else os.getcwd()), indent=1))
