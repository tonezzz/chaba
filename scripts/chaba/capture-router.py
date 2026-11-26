#!/usr/bin/env python3
"""capture-router.py -- deterministic Knowledge Capture Matrix router (READ-ONLY).

Classifies one capture candidate against the 7-row Capture Matrix in
docs/ssot/ssot.knowledge-capture.yml and emits a proposal with audit metadata:

    {source, source_id, as_of, proposed_sink, dedupe_key, action,
     confidence, rule, run_id}

It NEVER writes to a canonical sink (SSOT, board-api, lesson store, OC
knowledge, docs/kb, evidence surfaces). It only returns/emits the proposal.
The companion harvester.py calls it over scanned sources.

Design: OPS-0016 Phase C, approved 2026-11-23 (read-only propose; sink-native
stable keys; upsert-in-place, never fork). No model calls -- keyword scoring.

Usage:
    capture-router.py --text "..." --source card-comms --source-id X [--as-of ...]
    capture-router.py --input candidate.json          # keys = the --flags above
    echo '{"text":...}' | capture-router.py --input -
    capture-router.py --self-test                     # deterministic rule checks
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from typing import Any

MATRIX_VERSION = "ssot.knowledge-capture.yml@2026-11"
RUN_ID = time.strftime("%Y%m%dT%H%M%S")

# Sink-native key namespaces, straight from the Capture Matrix rows.
SINK_KEYS = {
    "ssot": "ssot_key",
    "kanban": "card_or_request_id",
    "lesson": "topic_slug",
    "oc-note": "note_id_or_domain",
    "kb": "kb_path",
    "evidence": "artifact_path_or_id",
    "none": "skip",
}

# Ordered rules: (name, sink, action, confidence, keywords).
# First pass scores by distinct keyword hits; ties break by this order.
RULES = [
    ("reusable-explainer", "lesson", "create", 0.85, (
        "explain", "what is", "what's", "how does", "why does", "compare",
        "difference between", "educate me", "tutorial", "walk me through",
        "overview of", "lesson", "deep dive",
    )),
    ("execution-evidence", "evidence", "link", 0.80, (
        "landed as", "exit=0", "verified", "result:", "outcome", "benchmark",
        "evidence", "proof", "commit ", "sha256", "dispatch outcome",
        "pushed to", "moved to done", "closed by",
    )),
    ("actionable-work", "kanban", "create", 0.80, (
        "follow-up", "follow up", "blocked", "unmet request", "need to",
        "should we", "please ", "fix ", "wire ", "dispatch", "card ",
        "request ", "next action", "decision needed", "todo", "proceed",
    )),
    ("durable-runbook", "kb", "link", 0.70, (
        "runbook", "how-to", "how to", "troubleshoot", "deployment procedure",
        "engineering knowledge", "cookbook", "playbook",
    )),
    ("stable-rule", "ssot", "link", 0.72, (
        "policy", "procedure", "schema", "ownership", "owner:", "quality rule",
        "audit rule", "governing", "must ", "standard", "guardrail",
        "canonical", "field ownership",
    )),
    ("navigation", "oc-note", "create", 0.70, (
        "where is", "how do i find", "entry point", "navigation", "pointer",
        "lookup", "index", "map of", "architecture", "retrieval recipe",
    )),
    ("transient", "none", "skip", 0.60, (
        "status?", "what's pending", "uptime", "right now", "live state",
        "current health", "today's status",
    )),
]

# References that mean a candidate already has an artifact somewhere.
FILED_RE = re.compile(
    r"(?:docs/ssot/[\w./-]+|docs/kb/[\w./-]+|dispatch-outcome-[\w-]+\.md|"
    r"https?://\S+|(?<![0-9a-f])(?![0-9]{8}(?![0-9]))[0-9a-f]{8,40}(?![0-9a-f])|"
    r"\bcard\s+[a-z0-9]+(?:-[a-z0-9]+)+\b|"
    r"\blesson\s+[a-z0-9]+(?:-[a-z0-9]+)+\b)",
    re.IGNORECASE,
)

# Focus-inbox entries emitted by scheduled producers already have a durable
# home (focus-inbox). Phase D baseline showed 382 of 383 focus-inbox kanban
# creates came from these shapes -- re-cardfing them floods the board.
PRODUCER_FOCUS_PATTERNS = (
    re.compile(r"job-fail-"),
    re.compile(r"-report-watch-"),
    re.compile(r"kanban-cards-"),
    re.compile(r"^handoff-"),
    re.compile(r"-audit-"),
)


def _is_producer_focus(sid: str) -> bool:
    return any(p.search(str(sid or "")) for p in PRODUCER_FOCUS_PATTERNS)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _hash(*parts: Any) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _slug(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", _norm(text).split("\n")[0])[:max_words]
    return "-".join(words) or "untitled"


def _native_key(sink: str, candidate: dict, norm: str) -> str:
    """Derive the sink-native stable key (never a content blob)."""
    text = candidate.get("text") or ""
    ref = None
    m = FILED_RE.search(text)
    if m:
        ref = m.group(0)
    if sink == "kanban":
        # A comm that already lives on card X is an upsert of X, never a fork.
        # source_id shape from harvester: "<card-slug>#comms[<i>]" -- key on the
        # parent card id so all comms from one card collapse to one proposal.
        if candidate.get("source") == "card-comms":
            card_id = str(candidate.get("source_id") or "").split("#", 1)[0].strip()
            if card_id:
                return card_id
        return ref or _hash(candidate.get("source"), candidate.get("source_id"), norm)
    if sink == "lesson":
        return _slug(text)
    if sink == "oc-note":
        return _slug(text) or _hash(candidate.get("source_id"))
    if sink in ("ssot", "kb"):
        if ref and ("/" in ref or ref.startswith("docs/")):
            return ref
        return _slug(text)
    if sink == "evidence":
        return candidate.get("source_id") or ref or _hash(norm)
    return _hash(candidate.get("source"), candidate.get("source_id"), norm)


def route(candidate: dict, run_id: str = RUN_ID) -> dict:
    """Return one proposal dict for a candidate. Pure -- no I/O, no writes."""
    text = candidate.get("text") or ""
    norm = _norm(text)
    scores = []
    for rank, (name, sink, action, base, keywords) in enumerate(RULES):
        hits = sum(1 for kw in keywords if kw in norm)
        if hits:
            score = base + min(0.14, 0.04 * (hits - 1)) - rank * 0.002
            scores.append((score, -rank, name, sink, action))
    if scores:
        _, _, name, sink, action = max(scores)
        confidence = round(min(0.99, max(scores)[0]), 2)
    else:
        # No rule matched -> index as a pointer link, never auto-create a sink
        # entry from an unclassifiable string (avoids forking noise).
        name, sink, action, confidence = "unclassified", "oc-note", "link", 0.45

    already = bool(FILED_RE.search(text))
    if already:
        action = "link" if action == "create" else action
    if candidate.get("already_filed"):
        action = "skip"

    # Kanban candidate sourced from a card comm: the parent card already
    # exists, so this is a link/upsert of that card, not a new-card create.
    from_card = (sink == "kanban"
                 and candidate.get("source") == "card-comms"
                 and "#" in str(candidate.get("source_id") or ""))
    if from_card:
        action = "link"
        already = True

    # Phase D baseline guard: scheduled-producer focus-inbox artifacts and
    # dispatch outcomes are already durable in their own surface. Keep the
    # pointer as evidence on the existing artifact instead of creating a
    # duplicate card. Genuinely uncaptured focus-inbox items (e.g.
    # "wiki-login-polish") are still eligible for a card.
    filed_artifact = (
        (candidate.get("source") == "focus-inbox"
         and _is_producer_focus(candidate.get("source_id")))
        or candidate.get("source") == "dispatch-outcome"
    )
    if sink == "kanban" and action == "create" and filed_artifact:
        name = name + "+filed-artifact"
        sink, action = "evidence", "link"
        already = True

    native = _native_key(sink, candidate, norm)
    return {
        "run_id": run_id,
        "matrix_version": MATRIX_VERSION,
        "source": candidate.get("source") or "unknown",
        "source_id": candidate.get("source_id") or "unknown",
        "as_of": candidate.get("as_of") or time.strftime("%Y-%m-%d"),
        "text_excerpt": text[:200],
        "proposed_sink": sink,
        "sink_key_type": SINK_KEYS[sink],
        "dedupe_key": f"{sink}:{native}",
        "action": action,
        "confidence": confidence,
        "rule": name,
        "already_filed": already or bool(candidate.get("already_filed")),
    }


def self_test() -> int:
    cases = [
        ({"text": "Explain how the board-api write door works", "source": "card-comms", "source_id": "c1"}, "lesson"),
        ({"text": "Landed as cea237f72d on origin/master, verified", "source": "card-comms", "source_id": "c2"}, "evidence"),
        ({"text": "Please wire the capture hooks on tony-dell next action", "source": "card-comms", "source_id": "c3"}, "kanban"),
        ({"text": "Runbook for Caddy HA subpath redirects", "source": "focus-inbox", "source_id": "f1"}, "kb"),
        ({"text": "Field ownership standard: humans own workflow fields", "source": "focus-inbox", "source_id": "f2"}, "ssot"),
        ({"text": "Where is the entry point for MCP focus lookup?", "source": "focus-inbox", "source_id": "f3"}, "oc-note"),
        ({"text": "status?", "source": "card-comms", "source_id": "c4"}, "none"),
    ]
    ok = 0
    for cand, expected in cases:
        got = route(cand, "self-test")["proposed_sink"]
        flag = "OK" if got == expected else "FAIL"
        print(f"[{flag}] {cand['text'][:38]!r} -> {got} (expected {expected})")
        ok += got == expected
    # Regression: a kanban-routed comm from an existing card must upsert that
    # card (link + parent-card key), never propose a new card.
    reg = route({"text": "Please wire the capture hooks on tony-dell next action",
                 "source": "card-comms",
                 "source_id": "ada-capture-hooks#comms[4]"}, "self-test")
    good = (reg["proposed_sink"] == "kanban" and reg["action"] == "link"
            and reg["dedupe_key"] == "kanban:ada-capture-hooks"
            and reg["already_filed"] is True)
    print(f"[{'OK' if good else 'FAIL'}] card-comm kanban regression -> "
          f"{reg['action']} {reg['dedupe_key']}")
    ok += good
    # Phase D guards: producer artifacts are pointers, not new cards; FILED_RE
    # must not treat "card spec" or an 8-digit date as an existing reference.
    extra = [
        ({"text": "job-fail: bad on testbox - please fix next action",
          "source": "focus-inbox", "source_id": "2026-10-27-143740-job-fail-bad-on-testbox"},
         "evidence", "link", True),
        ({"text": "Please fix the wiki login next action",
          "source": "focus-inbox", "source_id": "wiki-login-polish"},
         "kanban", "create", False),
        ({"text": "Please fix card spec next action",
          "source": "focus-inbox", "source_id": "f4"},
         "kanban", "create", False),
        ({"text": "Please fix 20261119 next action",
          "source": "focus-inbox", "source_id": "f5"},
         "kanban", "create", False),
        ({"text": "# Dispatch outcome — follow-up, please wire next action",
          "source": "dispatch-outcome", "source_id": "dispatch-outcome-20261120-172937-goal"},
         "evidence", "link", True),
    ]
    for cand, exp_sink, exp_action, exp_filed in extra:
        r = route(cand, "self-test")
        good = (r["proposed_sink"] == exp_sink and r["action"] == exp_action
                and r["already_filed"] == exp_filed)
        flag = "OK" if good else "FAIL"
        print(f"[{flag}] {cand['source_id'][:34]!r} -> "
              f"{r['proposed_sink']}/{r['action']} filed={r['already_filed']}")
        ok += good
    total = len(cases) + 1 + len(extra)
    print(f"self-test: {ok}/{total} passed")
    return 0 if ok == total else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text")
    ap.add_argument("--source", default="cli")
    ap.add_argument("--source-id")
    ap.add_argument("--as-of")
    ap.add_argument("--input", help="JSON file or '-' for stdin")
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.input:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        payload = json.loads(raw)
        candidates = payload if isinstance(payload, list) else [payload]
    elif args.text:
        candidates = [{"text": args.text, "source": args.source,
                       "source_id": args.source_id, "as_of": args.as_of}]
    else:
        ap.error("pass --text or --input (or --self-test)")

    out = [route(c, args.run_id) for c in candidates]
    print(json.dumps(out if len(out) > 1 else out[0], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
