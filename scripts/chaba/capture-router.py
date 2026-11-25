#!/usr/bin/env python3
"""capture-router.py -- deterministic Knowledge Capture Matrix router.

Two modes:

1. PROPOSE (read-only lib/CLI): classify one capture candidate against the
   7-row Capture Matrix in docs/ssot/ssot.knowledge-capture.yml and emit a
   proposal with audit metadata:

       {source, source_id, as_of, proposed_sink, dedupe_key, action,
        confidence, rule, run_id}

   It NEVER writes to a canonical sink (SSOT, board-api, lesson store, OC
   knowledge, docs/kb, evidence surfaces). It only returns/emits the proposal.
   The companion harvester.py calls route() over scanned sources.

2. EVENTS (Phase C.2 consumer): read normalized C.1-contract events from
   events.jsonl spools (producers: capture-event.py hooks, capture-harvest.py),
   normalize each into a candidate, route() it, dedupe by event dedupe_key +
   router dedupe_key, and append audit records to router-audit.jsonl. New
   proposals are upserted into the runtime capture-ledger.yml so the gated
   writer capture-apply.py can pick up (kanban, create) keys.

   Dry-run is the ONLY posture: there is no --apply here and no sink write
   code path. Every audit record carries dry_run=true; the single
   write-approved pair (kanban/create) still goes through
   capture-apply.py --key <dedupe_key> --apply --confirm <key> -> board-api
   (OPS-0024). Runtime artifacts stay under --out-dir
   ($CHABA_CAPTURE_OUT, default ~/.local/share/chaba/capture).

Design: OPS-0016 Phase C + session-capture C.2 (OPS-1354); approved
2026-11-23/25 (propose-first; sink-native stable keys; upsert-in-place,
never fork). No model calls -- keyword scoring.

Usage:
    capture-router.py --text "..." --source card-comms --source-id X [--as-of ...]
    capture-router.py --input candidate.json          # keys = the --flags above
    echo '{"text":...}' | capture-router.py --input -
    capture-router.py --events events.jsonl [--events ...] [--events-dir DIR]
    capture-router.py --self-test                     # deterministic rule checks
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
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


# ---------------------------------------------------------------------------
# Phase C.2: normalized-event consumer (events.jsonl -> route -> dedupe -> audit)
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = Path(os.environ.get("CHABA_CAPTURE_OUT")
                   or Path.home() / ".local/share/chaba/capture")
DEFAULT_EVENT_PATHS = [
    DEFAULT_OUT / "events.jsonl",                    # capture-event.py spool
    HERE.parents[1] / "reports/session-capture/events.jsonl",  # capture-harvest
]
ROUTER_STATE = "router-state.json"
ROUTER_AUDIT = "router-audit.jsonl"
ROUTER_PROPOSALS = "router-proposals.jsonl"
LEDGER_NAME = "capture-ledger.yml"
EVENTS_ENVELOPE = "capture-router-events/1"
# The only sink/action pair with an approved write path (via capture-apply).
APPROVED_WRITE = {("kanban", "create")}
APPLY_HINT = "capture-apply.py --key {key} --apply --confirm {key}"

# Event types whose artifact already exists at emit time -> already-filed
# pointers, not create candidates. Mirrors capture-event.FILED_TYPES; the
# emitter module is imported lazily so this file stays standalone-importable.
FILED_EVENT_TYPES = {"handoff", "outcome", "focus_session", "focus_decision"}

_event_mod_cache: Any = None


def _event_mod():
    """Import capture-event.py by path for its contract constants/guards."""
    global _event_mod_cache
    if _event_mod_cache is None:
        try:
            spec = importlib.util.spec_from_file_location(
                "capture_event", HERE / "capture-event.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _event_mod_cache = mod
        except Exception:
            _event_mod_cache = False
    return _event_mod_cache or None


def _filed_event_types() -> set:
    mod = _event_mod()
    types = getattr(mod, "FILED_TYPES", None) if mod else None
    return set(types) if types else set(FILED_EVENT_TYPES)


def _scan_event_secrets(*texts: str) -> str | None:
    """Reuse the emitter's secret guard; metadata-only rejection upstream."""
    mod = _event_mod()
    scan = getattr(mod, "_scan_secrets", None) if mod else None
    if scan:
        return scan(*texts)
    return None


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_json_atomic(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cap-route-",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_router_state(path: Path) -> dict:
    doc = _load_json(path, {})
    if not isinstance(doc, dict):
        doc = {}
    doc.setdefault("version", 1)
    doc.setdefault("envelope", EVENTS_ENVELOPE)
    doc.setdefault("processed", {})    # event dedupe_key -> audit meta
    doc.setdefault("proposal_keys", {})  # router dedupe_key -> run_id
    return doc


def _load_ledger_keys(path: Path) -> set:
    """dedupe_keys already in capture-ledger.yml entries (best effort)."""
    try:
        import yaml
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return set()
    return {e.get("dedupe_key") for e in doc.get("entries") or []
            if isinstance(e, dict) and e.get("dedupe_key")}


def _load_ledger_doc(path: Path) -> dict:
    try:
        import yaml
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def merge_ledger(path: Path, new_entries: list[dict]) -> int:
    """Upsert proposal entries into capture-ledger.yml, preserving applied:.

    Runtime-local state only — never a canonical sink. Returns entries added.
    """
    if not new_entries:
        return 0
    import yaml
    doc = _load_ledger_doc(path)
    entries = [e for e in doc.get("entries") or [] if isinstance(e, dict)]
    known = {e.get("dedupe_key") for e in entries}
    added = 0
    for e in new_entries:
        if e.get("dedupe_key") in known:
            continue
        entries.append(e)
        known.add(e["dedupe_key"])
        added += 1
    if not added:
        return 0
    payload = {"matrix_version": MATRIX_VERSION, "entries": entries}
    if doc.get("applied"):
        payload["applied"] = doc["applied"]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cap-ledger-",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return added


def event_to_candidate(ev: dict) -> tuple[dict | None, str | None]:
    """Normalize one C.1-contract event into a route() candidate.

    Returns (candidate, None) or (None, reject_reason). Never persists the
    event payload — only fields the router scores on.
    """
    if not isinstance(ev, dict):
        return None, "event is not a JSON object"
    dedupe = ev.get("dedupe_key")
    if not isinstance(dedupe, str) or not dedupe.strip():
        return None, "missing dedupe_key"
    summary = str(ev.get("summary") or "")
    parts = [summary]
    parts += [str(r) for r in ev.get("refs") or [] if r]
    parts += [str(e) for e in ev.get("evidence") or [] if e]
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    parts += [str(w) for w in payload.get("where_filed") or [] if w]
    parts += [str(o) for o in payload.get("open_asks") or [] if o]
    cand = {
        "text": "\n".join(p for p in parts if p)[:8000],
        "source": str(ev.get("source") or "script"),
        "source_id": str(ev.get("source_id") or dedupe),
        "as_of": str(ev.get("as_of") or "")[:10],
        "already_filed": ev.get("event_type") in _filed_event_types(),
    }
    return cand, None


def _iter_events(paths: list[Path]):
    """Yield (path, lineno, dict|None, raw_line)."""
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            yield path, 0, None, f"__unreadable__:{exc}"
            continue
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield path, i, json.loads(line), line
            except Exception:
                yield path, i, None, line


def consume_events(event_paths: list[Path], out_dir: Path,
                   ledger_path: Path | None = None,
                   since: str = "", limit: int = 0,
                   run_id: str = RUN_ID) -> dict:
    """Route normalized events -> proposals + audit. Idempotent, dry-run only.

    Writes ONLY under out_dir (router-state.json, router-audit.jsonl,
    router-proposals.jsonl) plus an optional runtime-ledger upsert. No
    canonical sink is touched; sink writes stay behind capture-apply.py.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / ROUTER_STATE
    audit_path = out_dir / ROUTER_AUDIT
    proposals_path = out_dir / ROUTER_PROPOSALS
    state = load_router_state(state_path)
    processed = state["processed"]
    prop_keys = state["proposal_keys"]

    ledger_keys = _load_ledger_keys(ledger_path) if ledger_path else set()
    known_props = set(prop_keys) | set(ledger_keys)

    stats = {"events": 0, "new": 0, "duplicate": 0, "rejected": 0,
             "proposals_new": 0, "proposals_duplicate": 0, "errors": 0}
    new_entries: list[dict] = []
    seen_this_run: set = set()

    def audit(**kw):
        rec = {"ts": dt.datetime.now(dt.timezone.utc)
               .isoformat(timespec="seconds"),
               "run_id": run_id, "mode": "route", "envelope": EVENTS_ENVELOPE,
               "dry_run": True}
        rec.update(kw)
        _append_jsonl(audit_path, rec)

    audit(action="run", result="start",
          event_files=[str(p) for p in event_paths],
          since=since or None, limit=limit or None)

    for path, lineno, ev, raw in _iter_events(event_paths):
        if limit and stats["events"] >= limit:
            break
        if ev is None:
            stats["errors"] += 1
            audit(result="rejected:bad-json", source_file=str(path),
                  line=lineno,
                  detail=("unreadable file" if raw.startswith("__unreadable__:")
                          else "invalid JSON line")[:200])
            continue
        stats["events"] += 1
        dedupe = str(ev.get("dedupe_key") or "").strip()
        meta = {
            "event_id": ev.get("event_id"),
            "event_dedupe_key": dedupe or None,
            "event_type": ev.get("event_type"),
            "source": ev.get("source"),
            "actor": ev.get("actor"),
            "as_of": str(ev.get("as_of") or "")[:10],
            "source_file": str(path), "line": lineno,
        }
        if not dedupe:
            stats["rejected"] += 1
            audit(**meta, result="rejected:no-dedupe-key",
                  dedupe_status="rejected")
            continue
        if since and meta["as_of"] and meta["as_of"] < since:
            audit(**meta, result="skipped:before-since",
                  dedupe_status="skipped")
            continue
        if dedupe in processed or dedupe in seen_this_run:
            stats["duplicate"] += 1
            audit(**meta, result="duplicate", dedupe_status="duplicate")
            continue
        seen_this_run.add(dedupe)

        cand, why = event_to_candidate(ev)
        if cand is None:
            stats["rejected"] += 1
            processed[dedupe] = {"result": f"rejected:{why}",
                                 "run_id": run_id}
            audit(**meta, result=f"rejected:{why}",
                  dedupe_status="rejected")
            continue

        secret = _scan_event_secrets(cand["text"])
        if secret:
            # Metadata-only: never persist the rejected content.
            stats["rejected"] += 1
            processed[dedupe] = {"result": "rejected:secret",
                                 "run_id": run_id}
            audit(**meta, result="rejected:secret-shaped content",
                  dedupe_status="rejected")
            continue

        p = route(cand, run_id)
        rkey = p["dedupe_key"]
        approved = (p["proposed_sink"], p["action"]) in APPROVED_WRITE
        if rkey in known_props:
            stats["proposals_duplicate"] += 1
            status = "proposal-duplicate"
        else:
            stats["proposals_new"] += 1
            status = "new"
            known_props.add(rkey)
            prop_keys[rkey] = run_id
            entry = {k: p[k] for k in (
                "run_id", "dedupe_key", "proposed_sink", "action",
                "source", "source_id", "as_of", "confidence", "rule")}
            new_entries.append(entry)
            _append_jsonl(proposals_path, {
                "ts": dt.datetime.now(dt.timezone.utc)
                .isoformat(timespec="seconds"),
                "run_id": run_id, "event_dedupe_key": dedupe,
                "event_id": ev.get("event_id"), "proposal": p,
                "dry_run": True})
        stats["new"] += 1
        processed[dedupe] = {"result": status, "run_id": run_id,
                             "router_dedupe_key": rkey}
        audit(**meta, result=status, dedupe_status="new",
              target_sink=p["proposed_sink"], action=p["action"],
              confidence=p["confidence"], rule=p["rule"],
              router_dedupe_key=rkey,
              approved_write=approved,
              apply_path=(APPLY_HINT.format(key=rkey) if approved else None),
              sink_write="none")

    ledger_added = 0
    if ledger_path is not None:
        ledger_added = merge_ledger(ledger_path, new_entries)

    _write_json_atomic(state_path, state)
    audit(action="run", result="done", events=stats["events"],
          new=stats["new"], duplicate=stats["duplicate"],
          rejected=stats["rejected"], errors=stats["errors"],
          proposals_new=stats["proposals_new"],
          proposals_duplicate=stats["proposals_duplicate"],
          ledger_added=ledger_added)
    stats.update({"run_id": run_id, "ledger_added": ledger_added,
                  "state": str(state_path), "audit": str(audit_path),
                  "proposals": str(proposals_path),
                  "ledger": str(ledger_path) if ledger_path else None,
                  "note": "dry-run only — no canonical sink was written; "
                          "gated writes via capture-apply.py"})
    return stats


def _resolve_event_paths(args) -> list[Path]:
    paths: list[Path] = []
    for p in args.events or []:
        paths.append(Path(p).expanduser())
    for d in args.events_dir or []:
        d = Path(d).expanduser()
        if d.is_dir():
            paths += sorted(d.glob("events.jsonl"))
            paths += sorted(d.glob("*/events.jsonl"))
        elif d.is_file():
            paths.append(d)
    if not paths:
        paths = [p for p in DEFAULT_EVENT_PATHS if p.exists()]
    # de-dupe preserving order
    seen, out = set(), []
    for p in paths:
        rp = p.resolve() if p.exists() else p
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def self_test_events() -> int:
    import tempfile
    ok = total = 0

    def check(name: str, good: bool):
        nonlocal ok, total
        total += 1
        ok += bool(good)
        print(f"[{'OK' if good else 'FAIL'}] events: {name}")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        spool = root / "spool"
        spool.mkdir()
        ev_path = spool / "events.jsonl"
        events = [
            {"event_id": "evt-1", "event_type": "open_ask",
             "as_of": "2026-11-25", "source": "devin", "actor": "devin",
             "subject": "s1", "summary": "Please wire the capture hooks "
             "on tony-dell next action",
             "refs": [], "dedupe_key": "open_ask:devin:s1:wire",
             "volatility": "pointer", "payload": {}},
            {"event_id": "evt-2", "event_type": "handoff",
             "as_of": "2026-11-25", "source": "devin", "actor": "devin",
             "subject": "pkt", "summary": "Session handoff packet",
             "refs": ["docs/ssot/jobs/session-summary/x.yml"],
             "dedupe_key": "handoff:devin:s1:packet",
             "volatility": "pointer",
             "payload": {"where_filed": ["packet -> opencode-note:n1"]}},
            {"event_id": "evt-3", "event_type": "lesson",
             "as_of": "2026-11-25", "source": "manual", "actor": "tony",
             "subject": "exp", "summary": "Explain how dedupe keys work "
             "in the capture pipeline for next time",
             "refs": [], "dedupe_key": "lesson:manual:exp:dedupe",
             "volatility": "pointer", "payload": {}},
            {"event_id": "evt-4", "event_type": "discovery",
             "as_of": "2026-11-25", "source": "script", "actor": "script",
             "subject": "sec", "summary": "api_key=sk-ABCDEFGHIJKLMNOPQRSTUVWX",
             "refs": [], "dedupe_key": "discovery:script:sec:secret",
             "volatility": "pointer", "payload": {}},
        ]
        ev_path.write_text("\n".join(json.dumps(e) for e in events)
                           + "\nnot-json\n", encoding="utf-8")
        ledger = root / "capture-ledger.yml"
        ledger.write_text("matrix_version: test\nentries: []\n"
                          "applied:\n- dedupe_key: kanban:keep\n",
                          encoding="utf-8")

        s1 = consume_events([ev_path], spool, ledger_path=ledger,
                            run_id="t1")
        check("first run routes all valid events", s1["events"] == 4
              and s1["errors"] == 1 and s1["new"] == 3)
        check("secret event rejected without persisting content",
              s1["rejected"] == 1
              and "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in
              (spool / ROUTER_AUDIT).read_text()
              and "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in
              (spool / ROUTER_PROPOSALS).read_text())
        import yaml as _y
        led = _y.safe_load(ledger.read_text())
        check("ledger upsert preserves applied block",
              led.get("applied") == [{"dedupe_key": "kanban:keep"}]
              and len(led.get("entries") or []) >= 1)
        audit_lines = [json.loads(l) for l in
                       (spool / ROUTER_AUDIT).read_text().splitlines()
                       if l.strip()]
        check("audit JSONL records carry dry_run=true",
              audit_lines and all(a.get("dry_run") is True
                                  for a in audit_lines))

        # second run: fully idempotent
        s2 = consume_events([ev_path], spool, ledger_path=ledger,
                            run_id="t2")
        led2 = _y.safe_load(ledger.read_text())
        check("rerun is noop+audit (no new events/proposals/entries)",
              s2["new"] == 0 and s2["duplicate"] == 4
              and s2["proposals_new"] == 0
              and len(led2.get("entries") or []) ==
              len(led.get("entries") or []))

        # --since bound: old events are skipped, none routed
        s3 = consume_events([ev_path], spool, ledger_path=ledger,
                            since="2026-11-26", run_id="t3")
        check("--since filters old events", s3["new"] == 0)

    print(f"events self-test: {ok}/{total} passed")
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
    # --- Phase C.2 events mode ---
    ap.add_argument("--events", action="append",
                    help="events.jsonl file to consume (repeatable)")
    ap.add_argument("--events-dir", action="append",
                    help="dir containing events.jsonl (repeatable; "
                         "default: known spool + harvest paths that exist)")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT),
                    help="runtime artifact dir for state/audit/proposals/ledger")
    ap.add_argument("--ledger", default=None,
                    help="capture-ledger.yml path to upsert proposals into "
                         "(default: <out-dir>/capture-ledger.yml)")
    ap.add_argument("--no-ledger", action="store_true",
                    help="do not upsert proposals into the ledger")
    ap.add_argument("--since", default="",
                    help="only route events with as_of >= YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap events processed this run")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        rc1 = self_test()
        rc2 = self_test_events()
        return 0 if rc1 == 0 and rc2 == 0 else 1

    events_mode = bool(args.events or args.events_dir
                       or args.since or args.limit
                       or args.ledger or args.no_ledger
                       or args.out_dir != str(DEFAULT_OUT))
    if not (args.text or args.input) and not events_mode:
        # No propose input and no explicit events flags: still run events
        # mode over the default spool paths (the C.2 consumer's job).
        events_mode = True

    if events_mode and (args.text or args.input):
        ap.error("do not mix --text/--input with events mode")
    if events_mode:
        paths = _resolve_event_paths(args)
        if not paths:
            ap.error("no events.jsonl found (pass --events/--events-dir)")
        out_dir = Path(args.out_dir).expanduser()
        ledger_path = (None if args.no_ledger else
                       Path(args.ledger).expanduser() if args.ledger
                       else out_dir / LEDGER_NAME)
        stats = consume_events(paths, out_dir, ledger_path=ledger_path,
                               since=args.since, limit=args.limit,
                               run_id=args.run_id)
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return 0

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
