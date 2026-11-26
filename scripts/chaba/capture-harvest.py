#!/usr/bin/env python3
"""capture-harvest.py -- bounded harvester/index-refresh (Phase C.4).

Implements the "Harvester/index-refresh contract" from the Phase C.1
Capture Router Contract (docs/ssot/ssot.knowledge-capture.yml, PR #218):
a bounded, idempotent, read-mostly scan of approved capture sources that
emits normalized events plus pointer/index refresh artifacts.

Sources (stream -> normalized events):
  1. card-comms      -- card comms from:tony (ops verbs filtered; reuses
                        scripts/chaba/harvester.py scanners)
  2. focus-inbox     -- docs/ssot/focus-inbox/*.yml (top level only)
  3. dispatch-outcome-- dispatch-outcome-*.md in repo root + docs tree

Check sources (findings -> events only on violation):
  4. pointer-index   -- path:/file: refs inside ssot.index.yml,
                        ssot.procedures-index.yml, ssot.focus.current.yml
                        sources[] must resolve inside the repo
  5. focus-parity    -- ssot.focus.sessions.yml / ssot.focus.decisions.yml
                        required fields, append-only date order, and
                        session decision ids present in
                        ssot.technical-decisions.yml

Posture: READ-MOSTLY + LOCAL ARTIFACTS ONLY. Never writes a canonical
sink (no SSOT edits, no board-api, no /lesson, no OC notes, no docs/kb).
The only writes are the job's own artifacts under --out-dir:
  events.jsonl      append-only normalized events (dedupe_key unique)
  audit.jsonl       append-only audit records (contract shape)
  index.json        pointer/index refresh artifact -- upsert by dedupe_key
  checkpoint.json   per-source resume cursors
  report-<run>.md   human summary

Idempotency: event_id is a deterministic hash of dedupe_key (replay-safe);
index entries upsert in place (first_seen kept, last_seen refreshed);
checkpoint cursor bounds rescans; --full + dedupe still cannot fork.

Dry-run is the DEFAULT: nothing is written unless --write is passed.
--since/--limit bound the scan; --source repeats for one surface.

Usage:
    capture-harvest.py                     # dry-run summary, writes nothing
    capture-harvest.py --write             # persist artifacts to out-dir
    capture-harvest.py --stdout            # also print events JSON
    capture-harvest.py --source card-comms --limit 50 --since 2026-11-01
    capture-harvest.py --full              # ignore checkpoint cursors
    capture-harvest.py --self-test         # deterministic checks
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("capture-harvest: PyYAML required\n")
    raise

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("REPO") or HERE.parents[1])

sys.path.insert(0, str(HERE))
import harvester as _harv  # noqa: E402  (approved-source scanners)

ENVELOPE_VERSION = "capture-harvest/1"
MATRIX_VERSION = _harv.MATRIX_VERSION
DEFAULT_OUT = Path(os.environ.get("CHABA_CAPTURE_HARVEST_OUT")
                   or "reports/session-capture")

# dedupe_keys already emitted/indexed this process (populated in run()).
seen_keys: set = set()

VOLATILITY = "pointer"

# Pointer-index files whose path:/file: refs must resolve in the repo.
INDEX_POINTER_FILES = [
    "docs/ssot/ssot.index.yml",
    "docs/ssot/ssot.procedures-index.yml",
]
FOCUS_CURRENT = "docs/ssot/ssot.focus.current.yml"
FOCUS_SESSIONS = "docs/ssot/ssot.focus.sessions.yml"
FOCUS_DECISIONS = "docs/ssot/ssot.focus.decisions.yml"
TECH_DECISIONS = "docs/ssot/decisions/ssot.technical-decisions.yml"

SUMMARY_MAX = 240

# v0 deterministic event_type classifier for card comms (the C.2 router
# owns sink routing; this only labels the envelope).
DECISION_RE = re.compile(
    r"\b(decided|decision\b|approved|approval|going with|chose|choice is|"
    r"verdict|ruling)\b", re.I)
ASK_RE = re.compile(
    r"(\?|\bplease\b|\bneed\b|\bneeds\b|follow[- ]?up|\bcan you\b|"
    r"\bshould we\b|\brequest\b|\btodo\b|\bfix\b|\bwire\b)", re.I)
LESSON_RE = re.compile(
    r"\b(lesson|for next time|remember this|educate|explainer|tutorial)\b",
    re.I)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha(*parts) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()


def _slug(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", (text or "").strip().lower().split("\n")[0])
    return "-".join(words[:max_words]) or "untitled"


def _one_line(text: str, limit: int = SUMMARY_MAX) -> str:
    flat = re.sub(r"\s+", " ", (text or "").strip())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _as_of_date(value) -> str:
    """Normalize a timestamp-ish string to YYYY-MM-DD, else ''."""
    s = str(value or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"(\d{4})(\d{2})(\d{2})", s)  # compact YYYYMMDD...
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


# ---------- stream scanners (yield normalized candidate dicts) ----------

def scan_dispatch_outcomes(repo: Path):
    """Local variant of harvester.scan_dispatch_outcomes: source_id is the
    repo-relative path so same-named files under docs/ cannot collide on
    the dedupe key."""
    out = []
    paths = sorted(repo.glob("dispatch-outcome-*.md"))
    docs = repo / "docs"
    if docs.is_dir():
        paths += sorted(docs.rglob("dispatch-outcome-*.md"))
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")[:4000]
        except Exception:
            continue
        headline = next((ln for ln in text.splitlines()
                         if ln.startswith("# ")), path.stem)
        m = re.match(r"dispatch-outcome-(\d{4})(\d{2})(\d{2})-", path.stem)
        as_of = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
        out.append({
            "source": "dispatch-outcome",
            "source_id": str(path.relative_to(repo)),
            "text": f"{headline}\n{text[:1200]}",
            "as_of": as_of,
            "already_filed": False,
        })
    return out


def scan_streams(sources, repo: Path):
    """Yield candidates in deterministic order. card-comms/focus-inbox reuse
    the OPS-0016 approved scanners; dispatch-outcome uses the local
    path-keyed variant above."""
    for source in sources:
        if source == "dispatch-outcome":
            cands = scan_dispatch_outcomes(repo)
        else:
            fn = _harv.SCANNERS.get(source)
            if fn is None:
                continue
            cands = fn(None)  # full ordered scan; bounds applied later
        for cand in cands:
            yield {
                "source": source,
                "source_id": cand["source_id"],
                "text": cand["text"],
                "as_of": cand.get("as_of") or "",
                "already_filed": bool(cand.get("already_filed")),
            }


def classify_event_type(source: str, text: str, already_filed: bool) -> str:
    if source == "dispatch-outcome":
        return "outcome"
    if source == "focus-inbox":
        return "discovery" if already_filed else "open_ask"
    # card-comms: v0 keyword classifier
    if LESSON_RE.search(text):
        return "lesson"
    if DECISION_RE.search(text):
        return "decision"
    if ASK_RE.search(text):
        return "open_ask"
    return "discovery"


def actor_for(source: str, source_id: str, repo: Path) -> str:
    if source == "card-comms":
        # comms were pre-filtered to from:tony by the scanner
        return "tony"
    return "script"


def subject_for(source: str, source_id: str) -> str:
    sid = str(source_id)
    if "#" in sid:
        return sid.split("#", 1)[0]
    if "/" in sid:  # dispatch-outcome rel path -> basename
        return Path(sid).name
    return sid


def make_event(cand: dict, run_id: str, repo: Path) -> dict:
    dedupe_key = f"{cand['source']}:{cand['source_id']}"
    event_type = classify_event_type(cand["source"], cand["text"],
                                     cand.get("already_filed"))
    if cand["source"] == "dispatch-outcome":
        ref = str(cand["source_id"])  # already repo-relative path
    else:
        ref = {
            "card-comms": f"docs/ssot/kanban/cards/{subject_for(cand['source'], cand['source_id'])}.yml",
            "focus-inbox": f"docs/ssot/focus-inbox/{cand['source_id']}.yml",
        }.get(cand["source"], subject_for(cand["source"], cand["source_id"]))
    event_id = "evt-" + _sha(ENVELOPE_VERSION, dedupe_key)[:16]
    return {
        "event_id": event_id,
        "event_type": event_type,
        "as_of": _as_of_date(cand.get("as_of")) or str(cand.get("as_of") or "")[:10],
        "source": cand["source"],
        "source_id": str(cand["source_id"]),
        "actor": actor_for(cand["source"], cand["source_id"], repo),
        "subject": subject_for(cand["source"], cand["source_id"]),
        "summary": _one_line(cand["text"]),
        "refs": [ref],
        "dedupe_key": dedupe_key,
        "volatility": VOLATILITY,
        "sink_hint": None,
        "evidence": [ref],
        "provenance": {"run_id": run_id, "scanner": cand["source"],
                       "envelope": ENVELOPE_VERSION},
    }


# ---------- check sources (findings only on violation) ----------

def _load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _load_yaml_checked(path: Path, check: str, findings: list):
    """Like _load_yaml but records missing/unparseable-file findings."""
    if not path.exists():
        findings.append({"check": check, "rule": "missing-file",
                         "severity": "warn", "ref": str(path),
                         "detail": f"required file missing: {path}"})
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        findings.append({"check": check, "rule": "unparseable",
                         "severity": "warn", "ref": str(path),
                         "detail": f"yaml parse failed: {exc}"})
        return {}


def _iter_index_refs(doc) -> list[str]:
    """Collect repo-relative path:/file: refs from an index-shaped doc."""
    refs = []
    for sec in doc.get("sections") or []:
        for item in sec.get("items") or []:
            if isinstance(item, dict):
                p = item.get("path")
                if p:
                    refs.append(str(p))
    idx = doc.get("index")
    if isinstance(idx, list):
        for item in idx:
            if isinstance(item, dict) and item.get("file"):
                refs.append(str(item["file"]))
            elif isinstance(item, dict) and item.get("path"):
                refs.append(str(item["path"]))
    return refs


PATH_TOKEN_RE = re.compile(
    r"[\w][\w./-]*\.(?:yml|yaml|md|py|sh|json|txt)")


def _resolve_candidates(repo: Path, ref: str) -> list[Path]:
    """Resolution guesses for an index ref: exact, then docs/ssot/ and
    docs/-relative (procedures-index mixes both styles)."""
    ref = ref.strip().strip("`'")
    return [repo / ref, repo / "docs/ssot" / ref, repo / "docs" / ref]


def _ref_missing_tokens(repo: Path, ref: str) -> list[str]:
    """Return path-like tokens inside ref that resolve nowhere.

    Index files mix styles: exact repo paths, compound 'a + b' refs, and
    'AGENTS.md duties'-style label+path strings. A ref is healthy when
    every path-like token it carries resolves under one of the candidate
    roots; refs with no tokens are label-only and pass.
    """
    ref = ref.strip().strip("`")
    if any(p.exists() for p in _resolve_candidates(repo, ref)):
        return []
    tokens = PATH_TOKEN_RE.findall(ref)
    if not tokens:
        return []  # label-only ref, nothing to resolve
    missing = []
    for tok in tokens:
        tok = tok.strip("`'")
        if not any(p.exists() for p in _resolve_candidates(repo, tok)):
            missing.append(tok)
    return missing


def check_pointer_indexes(repo: Path):
    """Yield findings for index path:/file: refs that do not resolve."""
    findings = []
    seen = set()

    def add(f):
        key = (f["check"], f["rule"], f["ref"])
        if key not in seen:
            seen.add(key)
            findings.append(f)

    for rel in INDEX_POINTER_FILES:
        path = repo / rel
        if not path.exists():
            add({
                "check": "pointer-index", "rule": "missing-index-file",
                "severity": "warn", "ref": rel,
                "detail": f"index file itself missing: {rel}",
            })
            continue
        doc = _load_yaml_checked(path, "pointer-index", findings)
        for ref in _iter_index_refs(doc):
            for tok in _ref_missing_tokens(repo, ref):
                add({
                    "check": "pointer-index", "rule": "dangling-ref",
                    "severity": "warn", "ref": tok,
                    "detail": f"{rel} ref {ref!r} -> missing {tok}",
                })
    # focus.current sources[] are leaf pointers -- existence only, they are
    # not indexes themselves.
    focus = _load_yaml_checked(repo / FOCUS_CURRENT, "pointer-index", findings)
    for src in focus.get("sources") or []:
        if isinstance(src, dict) and src.get("file"):
            rel = str(src["file"])
            if not (repo / rel).exists():
                add({
                    "check": "pointer-index", "rule": "dangling-source",
                    "severity": "warn", "ref": rel,
                    "detail": f"{FOCUS_CURRENT} sources[] -> missing {rel}",
                })
    return findings


def _session_entries(doc) -> list[dict]:
    out = []
    for i, e in enumerate(doc.get("sessions") or []):
        if isinstance(e, dict):
            out.append((i, e))
    return out


def _decision_entries(doc) -> list[dict]:
    out = []
    for sec in doc.get("sections") or []:
        for i, e in enumerate(sec.get("items") or []):
            if isinstance(e, dict):
                out.append((i, e))
    return out


def check_focus_parity(repo: Path):
    """Yield findings for focus-log schema/order/cross-ref violations."""
    findings = []
    sess_doc = _load_yaml_checked(repo / FOCUS_SESSIONS, "focus-parity", findings)
    dec_doc = _load_yaml_checked(repo / FOCUS_DECISIONS, "focus-parity", findings)

    prev = ""
    for i, e in _session_entries(sess_doc):
        d = str(e.get("date") or "")
        if not re.match(r"^\d{4}-\d{2}-\d{2}", d):
            findings.append({"check": "focus-parity", "rule": "session-date",
                             "severity": "warn", "ref": f"{FOCUS_SESSIONS}#sessions[{i}]",
                             "detail": f"session[{i}] missing ISO date"})
        elif prev and d < prev:
            findings.append({"check": "focus-parity", "rule": "session-order",
                             "severity": "warn", "ref": f"{FOCUS_SESSIONS}#sessions[{i}]",
                             "detail": f"session[{i}] date {d} before earlier {prev} (append-only violation?)"})
        if d:
            prev = d
        if not str(e.get("focus") or "").strip():
            findings.append({"check": "focus-parity", "rule": "session-focus",
                             "severity": "warn", "ref": f"{FOCUS_SESSIONS}#sessions[{i}]",
                             "detail": f"session[{i}] empty focus label"})

    prev = ""
    # Continuation/system rows legitimately carry request: '' (bare cues are
    # dropped upstream per the CUE_RE convention in tony-ideas-update.py).
    cue_actions = {"continue", "triage_backlog", "inbox", "status",
                   "recommend", "next"}
    for i, e in _decision_entries(dec_doc):
        ref = f"{FOCUS_DECISIONS}#items[{i}]"
        action = str(e.get("action") or "").strip().lower()
        for field in ("date", "request", "action", "reason"):
            if e.get(field) in (None, ""):
                if field == "request" and action in cue_actions:
                    continue
                findings.append({"check": "focus-parity", "rule": f"decision-{field}",
                                 "severity": "warn", "ref": ref,
                                 "detail": f"decision item[{i}] missing required '{field}'"})
        d = str(e.get("date") or "")
        if d and prev and d < prev:
            findings.append({"check": "focus-parity", "rule": "decision-order",
                             "severity": "warn", "ref": ref,
                             "detail": f"decision[{i}] date {d} before earlier {prev}"})
        if d:
            prev = d

    # Cross-ref: session decisions[].id must exist in technical-decisions.
    tech = _load_yaml_checked(repo / TECH_DECISIONS, "focus-parity", findings)
    tech_ids = {str(d.get("id")) for d in (tech.get("decisions") or [])
                if isinstance(d, dict)}
    for i, e in _session_entries(sess_doc):
        for j, dec in enumerate(e.get("decisions") or []):
            if not isinstance(dec, dict):
                continue
            did = str(dec.get("id") or "")
            if did and tech_ids and did not in tech_ids:
                findings.append({
                    "check": "focus-parity", "rule": "session-decision-ref",
                    "severity": "info", "ref": f"{FOCUS_SESSIONS}#sessions[{i}].decisions[{j}]",
                    "detail": f"session decision id '{did}' not in {TECH_DECISIONS}",
                })
    return findings


def finding_event(f: dict, run_id: str) -> dict:
    dedupe_key = f"check:{f['check']}:{f['rule']}:{f['ref']}"
    return {
        "event_id": "evt-" + _sha(ENVELOPE_VERSION, dedupe_key)[:16],
        "event_type": "open_ask" if f.get("severity") == "warn" else "discovery",
        "as_of": _now()[:10],
        "source": "check",
        "source_id": dedupe_key,
        "actor": "script",
        "subject": f"{f['check']}:{f['rule']}",
        "summary": _one_line(f["detail"]),
        "refs": [f["ref"]],
        "dedupe_key": dedupe_key,
        "volatility": VOLATILITY,
        "sink_hint": None,
        "evidence": [f["ref"]],
        "provenance": {"run_id": run_id, "scanner": f["check"],
                       "envelope": ENVELOPE_VERSION,
                       "check": {"id": f["check"], "rule": f["rule"],
                                 "severity": f.get("severity", "info")}},
    }


# ---------- checkpoint / dedupe / artifacts ----------

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_seen_events(path: Path) -> set:
    """dedupe_keys already appended to events.jsonl (bounded read)."""
    seen = set()
    if not path.exists():
        return seen
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                seen.add(json.loads(ln).get("dedupe_key"))
            except Exception:
                continue
    except Exception:
        pass
    seen.discard(None)
    return seen


def position_after(candidates, cursor):
    """Index of first candidate AFTER the cursor source_id, or 0."""
    if not cursor:
        return 0
    for i, c in enumerate(candidates):
        if c["source_id"] == cursor:
            return i + 1
    return 0  # cursor vanished (archived/edited) -> rescan; dedupe protects


def audit_record(run_id: str, mode: str, **kw) -> dict:
    rec = {"ts": _now(), "run_id": run_id, "mode": mode,
           "envelope": ENVELOPE_VERSION}
    rec.update(kw)
    return rec


def run(args, repo: Path = REPO):
    global seen_keys
    run_id = time.strftime("%Y%m%dT%H%M%S")
    out_dir = Path(args.out_dir).expanduser()
    write = bool(args.write)
    dry_run = not write

    # Dedupe universe: events already appended + index entries already
    # refreshed. Both are local artifacts, so a fresh out-dir simply starts
    # clean (dedupe then relies on the checkpoint cursor).
    seen_keys = load_seen_events(out_dir / "events.jsonl")
    idx_existing = load_json(out_dir / "index.json", {})
    seen_keys.update((idx_existing.get("entries") or {}).keys())

    sources = list(dict.fromkeys(
        args.source or ["card-comms", "focus-inbox", "dispatch-outcome"]))
    since = args.since or ""
    limit = args.limit

    # --- gather stream candidates per source (ordered) ---
    by_source = {}
    for source in sources:
        cands = [c for c in scan_streams([source], repo)]
        by_source[source] = cands

    ckpt_path = out_dir / "checkpoint.json"
    ckpt = load_json(ckpt_path, {}) if (write or ckpt_path.exists()) else {}
    stored_cursors = ckpt.get("sources") or {}
    resume_cursors = {} if args.full else stored_cursors

    events, per_source_stats = [], {}
    new_cursors = {}
    for source, cands in by_source.items():
        cursor = (resume_cursors.get(source) or {}).get("cursor")
        stored_cursor = (stored_cursors.get(source) or {}).get("cursor")
        start = position_after(cands, cursor) if cursor else 0
        todo = cands[start:]
        if since:
            todo = [c for c in todo if (_as_of_date(c.get("as_of")) or "9999") >= since]
        if limit:
            todo = todo[:limit]
        emitted = skipped = 0
        last_sid = cursor
        for cand in todo:
            last_sid = cand["source_id"]
            ev = make_event(cand, run_id, repo)
            dup = ev["dedupe_key"] in seen_keys
            ev["dedupe_status"] = "duplicate" if dup else "new"
            events.append(ev)
            if dup:
                skipped += 1
            else:
                emitted += 1
                seen_keys.add(ev["dedupe_key"])
        # Checkpoint never regresses: a --full/--since/--limit run that
        # scans an earlier prefix must not pull the cursor backwards.
        # Compare against the STORED cursor (resume cursor is None under
        # --full even though a cursor exists on disk).
        if last_sid is None:
            last_sid = stored_cursor
        if stored_cursor and last_sid != stored_cursor:
            ci = next((i for i, c in enumerate(cands)
                       if c["source_id"] == stored_cursor), -1)
            ni = next((i for i, c in enumerate(cands)
                       if c["source_id"] == last_sid), -1)
            if ci > ni:
                last_sid = stored_cursor
        new_cursors[source] = {"cursor": last_sid,
                               "scanned": len(todo), "emitted": emitted,
                               "dedupe_skipped": skipped,
                               "resumed_after": cursor}
        per_source_stats[source] = {"candidates": len(cands),
                                    "resumed_at": start, "todo": len(todo)}

    # --- checks (run every time; bounded) ---
    findings = []
    if not args.no_checks:
        findings = (check_pointer_indexes(repo) + check_focus_parity(repo))
    check_events = []
    for f in findings:
        ev = finding_event(f, run_id)
        dup = ev["dedupe_key"] in seen_keys
        ev["dedupe_status"] = "duplicate" if dup else "new"
        check_events.append(ev)
        if not dup:
            seen_keys.add(ev["dedupe_key"])

    all_events = events + check_events
    new_events = [e for e in all_events if e["dedupe_status"] == "new"]

    # --- artifacts (only with --write) ---
    artifacts = {}
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        ev_path = out_dir / "events.jsonl"
        with ev_path.open("a", encoding="utf-8") as fh:
            for e in new_events:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        artifacts["events"] = str(ev_path)

        idx_path = out_dir / "index.json"
        idx = load_json(idx_path, {})
        entries = idx.get("entries") or {}
        now = _now()
        for e in all_events:
            key = e["dedupe_key"]
            if key in entries:
                entries[key]["last_seen"] = now
                entries[key]["run_id"] = run_id
            else:
                entries[key] = {
                    "event_id": e["event_id"], "event_type": e["event_type"],
                    "source": e["source"], "source_id": e.get("source_id"),
                    "as_of": e.get("as_of"), "summary": e.get("summary"),
                    "refs": e.get("refs"), "dedupe_key": key,
                    "first_seen": now, "last_seen": now, "run_id": run_id,
                }
                if e.get("provenance", {}).get("check"):
                    entries[key]["check"] = e["provenance"]["check"]
        idx.update({"version": 1, "envelope": ENVELOPE_VERSION,
                    "matrix_version": MATRIX_VERSION,
                    "generated_at": now, "last_run_id": run_id,
                    "entries": entries})
        idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1,
                                       sort_keys=True) + "\n", encoding="utf-8")
        artifacts["index"] = str(idx_path)

        ckpt.update({"version": 1, "envelope": ENVELOPE_VERSION,
                     "last_run_id": run_id, "updated_at": now,
                     "sources": {**(ckpt.get("sources") or {}), **new_cursors}})
        ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=1,
                                        sort_keys=True) + "\n", encoding="utf-8")
        artifacts["checkpoint"] = str(ckpt_path)

        # audit.jsonl: one run record + one record per NEW event
        aud_path = out_dir / "audit.jsonl"
        with aud_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(audit_record(
                run_id, "write", action="run",
                result="ok", sources=sources, since=since, limit=limit,
                scanned=sum(s["todo"] for s in per_source_stats.values()),
                emitted=len(new_events),
                findings=len(findings)), ensure_ascii=False) + "\n")
            for e in new_events:
                fh.write(json.dumps(audit_record(
                    run_id, "write", event_id=e["event_id"],
                    dedupe_key=e["dedupe_key"], event_type=e["event_type"],
                    source=e["source"], actor=e["actor"], as_of=e["as_of"],
                    target_sink=None, action="index", result="ok",
                    ref_written=",".join(e.get("refs") or []),
                    dry_run=False), ensure_ascii=False) + "\n")
        artifacts["audit"] = str(aud_path)

        report = render_report(out_dir, run_id, all_events, new_events,
                               findings, per_source_stats, new_cursors,
                               dry_run, repo)
        artifacts["report"] = str(report)

    if args.stdout:
        print(json.dumps(all_events, indent=2, ensure_ascii=False))

    # --- console summary ---
    by_type = {}
    for e in all_events:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
    print(f"run {run_id}: {'WRITE' if write else 'DRY-RUN'} "
          f"{len(all_events)} events ({len(new_events)} new, "
          f"{len(all_events) - len(new_events)} dup), "
          f"{len(findings)} check findings")
    for s, st in per_source_stats.items():
        cs = new_cursors.get(s, {})
        print(f"  {s}: {st['candidates']} candidates, "
              f"{st['todo']} after cursor/since/limit -> "
              f"{cs.get('emitted', 0)} new, {cs.get('dedupe_skipped', 0)} dup")
    if findings:
        print(f"  checks: {len(findings)} findings "
              f"({sum(1 for f in findings if f['severity'] == 'warn')} warn)")
    for k, v in artifacts.items():
        print(f"  {k}: {v}")
    if dry_run:
        print("DRY-RUN: nothing written. Pass --write to persist artifacts.")
    return 0


def render_report(out_dir, run_id, all_events, new_events, findings, stats,
                  cursors, dry_run, repo):
    path = out_dir / f"report-{run_id}.md"
    lines = [
        f"# capture-harvest report — {run_id}", "",
        f"- mode: {'WRITE' if not dry_run else 'DRY-RUN'}",
        f"- matrix: `{MATRIX_VERSION}` envelope `{ENVELOPE_VERSION}`",
        f"- events: {len(all_events)} ({len(new_events)} new)",
        f"- check findings: {len(findings)}",
        "",
        "| source | candidates | todo | new | dup |",
        "|---|---|---|---|---|",
    ]
    for s, st in stats.items():
        cs = cursors.get(s, {})
        lines.append(f"| {s} | {st['candidates']} | {st['todo']} | "
                     f"{cs.get('emitted', 0)} | {cs.get('dedupe_skipped', 0)} |")
    if findings:
        lines += ["", "## Check findings", "",
                  "| check | rule | severity | ref |", "|---|---|---|---|"]
        for f in findings:
            lines.append(f"| {f['check']} | {f['rule']} | "
                         f"{f.get('severity', 'info')} | `{f['ref']}` |")
    lines += ["", "> READ-MOSTLY: no canonical sink was written. "
              "Artifacts are pointers/indices only.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def self_test() -> int:
    ok = 0
    total = 0

    def check(name, cond):
        nonlocal ok, total
        total += 1
        ok += bool(cond)
        print(f"[{'OK' if cond else 'FAIL'}] {name}")

    # envelope + idempotency
    cand = {"source": "card-comms", "source_id": "c1#comms[0]",
            "text": "Please wire the capture hooks next action",
            "as_of": "2026-11-25 09:00", "already_filed": False}
    e1 = make_event(cand, "t1", REPO)
    e2 = make_event(cand, "t2", REPO)
    check("event_id deterministic across runs", e1["event_id"] == e2["event_id"])
    check("dedupe_key stable", e1["dedupe_key"] == "card-comms:c1#comms[0]")
    check("ask comm -> open_ask", e1["event_type"] == "open_ask")
    check("envelope fields", all(k in e1 for k in
          ("event_id", "event_type", "as_of", "source", "actor", "subject",
           "summary", "refs", "dedupe_key", "volatility", "provenance")))

    cand2 = dict(cand, source="dispatch-outcome", source_id="dispatch-outcome-20261124-000000-x")
    check("dispatch-outcome -> outcome", make_event(cand2, "t", REPO)["event_type"] == "outcome")
    cand3 = dict(cand, source="focus-inbox", source_id="wiki-login-polish",
                 text="Please fix the wiki login next action", already_filed=False)
    check("fresh inbox -> open_ask", make_event(cand3, "t", REPO)["event_type"] == "open_ask")
    cand4 = dict(cand3, already_filed=True)
    check("processed inbox -> discovery", make_event(cand4, "t", REPO)["event_type"] == "discovery")
    cand5 = dict(cand, text="Decided: go with option b for the gate")
    check("decision comm -> decision", make_event(cand5, "t", REPO)["event_type"] == "decision")

    # cursor logic
    cands = [{"source_id": f"s{i}"} for i in range(5)]
    check("cursor resume skips processed", position_after(cands, "s2") == 3)
    check("missing cursor rescans safely", position_after(cands, "gone") == 0)
    check("empty cursor starts at 0", position_after(cands, "") == 0)

    # finding event dedupe
    f = {"check": "pointer-index", "rule": "dangling-ref", "severity": "warn",
         "ref": "docs/ssot/ssot.index.yml", "detail": "x -> missing y"}
    fe = finding_event(f, "t")
    check("warn finding -> open_ask", fe["event_type"] == "open_ask")
    check("finding dedupe_key", fe["dedupe_key"].startswith("check:pointer-index:"))

    # index/check extraction on inline docs
    doc = {"sections": [{"items": [{"label": "a", "path": "docs/ssot/x.yml"},
                                   {"label": "b", "text": "no path"}]}],
           "index": [{"file": "docs/ssot/y.yml"}, {"title": "z"}]}
    refs = _iter_index_refs(doc)
    check("index refs extracted", refs == ["docs/ssot/x.yml", "docs/ssot/y.yml"])

    # checkpoint round-trip in tempdir
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "checkpoint.json"
        p.write_text(json.dumps({"sources": {"card-comms": {"cursor": "a#comms[0]"}}}))
        loaded = load_json(p, {})
        check("checkpoint persists cursor", loaded["sources"]["card-comms"]["cursor"] == "a#comms[0]")

    print(f"self-test: {ok}/{total} passed")
    return 0 if ok == total else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["card-comms", "focus-inbox",
                                          "dispatch-outcome"], action="append")
    ap.add_argument("--since", help="YYYY-MM-DD lower bound on as_of")
    ap.add_argument("--limit", type=int, help="max stream candidates per source")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--write", action="store_true",
                    help="persist artifacts (default is dry-run: write nothing)")
    ap.add_argument("--full", action="store_true",
                    help="ignore checkpoint cursors (dedupe still protects)")
    ap.add_argument("--no-checks", action="store_true",
                    help="skip pointer-index/focus-parity checks")
    ap.add_argument("--stdout", action="store_true",
                    help="print normalized events JSON")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
