#!/usr/bin/env python3
"""capture-event.py -- emit ONE normalized capture-router event (dry-run only).

Phase C.3 (OPS-1356): the /session-capture surfaces and the Devin SessionEnd
hook call this to emit router events per the Capture Router Contract
(docs/ssot/ssot.knowledge-capture.yml, C.1 spec / PR #218). The emitter:

  * builds the contract event envelope (event_id, event_type, as_of, source,
    actor, subject, summary, refs, dedupe_key, volatility, sink_hint, payload,
    evidence, provenance),
  * appends it to $CHABA_CAPTURE_OUT/events.jsonl (default
    ~/.local/share/chaba/capture — runtime spool, NOT a canonical sink),
  * dry-run routes the event through capture-router.py and records the
    proposal (target_sink/action/confidence/rule) inside the event and in
    $CHABA_CAPTURE_OUT/audit.jsonl,
  * NEVER writes to a canonical sink. Gated writes stay behind
    capture-apply.py (OPS-0024) once C.2/C.4 land proposals in the ledger.

Idempotency: dedupe_key is deterministic; re-emitting the same event is a
replay-safe noop+audit (no second event, no second handoff packet).

Guards (failures are loud: stderr + nonzero exit + audit record):
  * event_type/source allowlists from the contract
  * handoff events REQUIRE at least one --ref or --where-filed (no fake
    handoff packets without a filed artifact)
  * open_ask events REQUIRE at least one --open-ask
  * secret-shaped content is rejected BEFORE any content is persisted
    (the audit record carries metadata only, never the rejected payload)

Usage:
  capture-event.py --type handoff --source devin --session <id> \
      --subject <packet-id> --summary "..." \
      --ref <sink-ref> --where-filed "item -> sink/path" [--where-filed ...]
  capture-event.py --type focus_session --source devin --session <id> \
      --summary "Session <id> ended (reason: X)." --ref devin-session:<id>
  capture-event.py --self-test
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
import time
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("REPO") or HERE.parents[1])
OUT = Path(os.environ.get("CHABA_CAPTURE_OUT")
           or Path.home() / ".local/share/chaba/capture")
EVENTS_LOG = "events.jsonl"
AUDIT_LOG = "audit.jsonl"
MATRIX_VERSION = "ssot.knowledge-capture.yml@2026-11"
CONTRACT_REF = "ssot.knowledge-capture.yml#Capture Router Contract (C.1)"

EVENT_TYPES = {
    "discovery", "decision", "open_ask", "lesson",
    "outcome", "handoff", "focus_decision", "focus_session",
}
SOURCES = {"devin", "opencode", "ada-voice", "script", "manual"}
VOLATILITY = {"canonical", "branch", "live_runtime", "pointer"}

# Event types whose artifact already exists at emit time -> the dry-run
# router sees them as already-filed pointers, not create candidates.
FILED_TYPES = {"handoff", "outcome", "focus_session", "focus_decision"}

MAX_SUMMARY = 4000
MAX_REFS = 20
MAX_WHERE_FILED = 50
MAX_OPEN_ASKS = 20
MAX_PAYLOAD = 4000

# High-confidence secret shapes only — bare hex SHAs are refs, not secrets.
SECRET_RES = [
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|passwd|password|"
               r"access[_-]?token|auth[_-]?token|bearer)\b"
               r"\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
    re.compile(r"\b(?:sk|ghp|gho|ghu|ghs|ghr|xox[baprs]|aiza|ya29|hf)_"
               r"[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
]


def _slug(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", (text or "").strip().lower())[:max_words]
    return "-".join(words) or "untitled"


def _dedupe_key(event_type: str, source: str, session: str | None,
                subject: str | None, summary: str, refs: list[str],
                override: str | None) -> str:
    if override:
        return override
    if session:
        anchor = session
    elif subject:
        anchor = _slug(subject, 4)
    elif refs:
        anchor = _slug(refs[0], 4)
    else:
        anchor = "nosession"
    tail = _slug(subject or summary or (refs[0] if refs else "event"), 6)
    return f"{event_type}:{source}:{anchor}:{tail}"[:160]


def _scan_secrets(*texts: str) -> str | None:
    for text in texts:
        for rx in SECRET_RES:
            if rx.search(text or ""):
                return rx.pattern[:60]
    return None


def _load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            if isinstance(e, dict):
                out.append(e)
        except Exception:
            continue
    return out


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _audit(path: Path, record: dict) -> None:
    rec = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    rec.update(record)
    rec["dry_run"] = True
    _append_jsonl(path, rec)


def _router():
    """Import capture-router.py by path (hyphenated filename)."""
    spec = importlib.util.spec_from_file_location(
        "capture_router", HERE / "capture-router.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _route_dry_run(event: dict) -> dict:
    """Dry-run route via capture-router; returns proposal fields or error."""
    try:
        router = _router()
    except Exception as exc:
        return {"route_error": f"router import failed: {exc}"}
    parts = [event.get("summary") or ""]
    parts += event.get("refs") or []
    parts += event.get("where_filed") or []
    parts += event.get("open_asks") or []
    cand = {
        "text": "\n".join(p for p in parts if p)[:8000],
        "source": event.get("source") or "script",
        "source_id": event.get("dedupe_key"),
        "as_of": event.get("as_of"),
        "already_filed": event.get("event_type") in FILED_TYPES,
    }
    try:
        p = router.route(cand, run_id=time.strftime("%Y%m%dT%H%M%S"))
        return {
            "target_sink": p.get("proposed_sink"),
            "action": p.get("action"),
            "confidence": p.get("confidence"),
            "rule": p.get("rule"),
            "router_dedupe_key": p.get("dedupe_key"),
            "router_already_filed": p.get("already_filed"),
        }
    except Exception as exc:
        return {"route_error": f"router.route failed: {exc}"}


def _fail(msg: str, audit_path: Path, meta: dict, code: int = 2) -> int:
    print(f"capture-event: ERROR: {msg}", file=sys.stderr)
    try:
        _audit(audit_path, {**meta, "result": f"rejected:{msg.split(':', 1)[0]}",
                            "error": msg[:300]})
    except Exception:
        pass
    return code


def emit(args: argparse.Namespace) -> int:
    events_path = Path(args.out_dir).expanduser() / EVENTS_LOG
    audit_path = Path(args.out_dir).expanduser() / AUDIT_LOG
    meta = {
        "event_type": args.type, "source": args.source,
        "actor": args.actor or args.source, "session": args.session,
        "subject": args.subject, "dedupe_key": args.dedupe_key,
    }

    # --- guards (loud, before anything is persisted) ---
    if args.type not in EVENT_TYPES:
        return _fail(f"event_type must be one of {sorted(EVENT_TYPES)}", audit_path, meta)
    if args.source not in SOURCES:
        return _fail(f"source must be one of {sorted(SOURCES)}", audit_path, meta)
    if args.volatility not in VOLATILITY:
        return _fail(f"volatility must be one of {sorted(VOLATILITY)}", audit_path, meta)
    summary = (args.summary or "").strip()
    if not summary:
        return _fail("summary is required", audit_path, meta)
    if len(summary) > MAX_SUMMARY:
        return _fail(f"summary exceeds {MAX_SUMMARY} chars", audit_path, meta)
    refs = [r.strip() for r in (args.ref or []) if r and r.strip()]
    if len(refs) > MAX_REFS:
        return _fail(f"too many --ref (max {MAX_REFS})", audit_path, meta)
    where_filed = [w.strip() for w in (args.where_filed or []) if w and w.strip()]
    if len(where_filed) > MAX_WHERE_FILED:
        return _fail(f"too many --where-filed (max {MAX_WHERE_FILED})", audit_path, meta)
    open_asks = [o.strip() for o in (args.open_ask or []) if o and o.strip()]
    if len(open_asks) > MAX_OPEN_ASKS:
        return _fail(f"too many --open-ask (max {MAX_OPEN_ASKS})", audit_path, meta)
    if args.payload_json:
        try:
            payload_extra = json.loads(args.payload_json)
            if not isinstance(payload_extra, dict):
                raise ValueError("payload must be a JSON object")
        except Exception as exc:
            return _fail(f"--payload-json invalid: {exc}", audit_path, meta)
        if len(args.payload_json) > MAX_PAYLOAD:
            return _fail(f"--payload-json exceeds {MAX_PAYLOAD} chars", audit_path, meta)
    else:
        payload_extra = {}
    if args.dedupe_key and not re.fullmatch(r"[a-z0-9][a-z0-9:._/+-]{2,160}", args.dedupe_key):
        return _fail("--dedupe-key must match [a-z0-9:._/+-] (2-160 chars)", audit_path, meta)
    if args.type == "handoff" and not (refs or where_filed):
        return _fail("handoff events require at least one --ref or --where-filed "
                     "(no fake handoff packets without a filed artifact)", audit_path, meta)
    if args.type == "open_ask" and not open_asks:
        return _fail("open_ask events require at least one --open-ask", audit_path, meta)

    secret_hit = _scan_secrets(summary, *refs, *where_filed, *open_asks,
                               args.payload_json or "")
    if secret_hit:
        # Metadata-only audit: never persist the rejected content anywhere.
        return _fail(f"secret-shaped content rejected ({secret_hit})", audit_path, meta)

    dedupe_key = _dedupe_key(args.type, args.source, args.session,
                             args.subject, summary, refs, args.dedupe_key)
    meta["dedupe_key"] = dedupe_key

    # --- idempotency: replay-safe noop+audit ---
    try:
        existing = _load_events(events_path)
    except Exception as exc:
        return _fail(f"cannot read events log: {exc}", audit_path, meta, code=3)
    if any(e.get("dedupe_key") == dedupe_key for e in existing):
        _audit(audit_path, {**meta, "result": "duplicate",
                            "dedupe_status": "duplicate"})
        print(json.dumps({"status": "duplicate", "dedupe_key": dedupe_key,
                          "audit": str(audit_path)}, ensure_ascii=False))
        return 0

    # --- build envelope (C.1 contract) ---
    as_of = args.as_of or dt.datetime.now().astimezone().isoformat(timespec="seconds")
    payload: dict[str, Any] = {}
    if where_filed:
        payload["where_filed"] = where_filed
    if open_asks:
        payload["open_asks"] = open_asks
    payload.update(payload_extra)
    event = {
        "event_id": f"evt-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "event_type": args.type,
        "as_of": as_of,
        "source": args.source,
        "actor": args.actor or args.source,
        "subject": args.subject,
        "session": args.session,
        "summary": summary,
        "refs": refs,
        "evidence": refs,
        "dedupe_key": dedupe_key,
        "volatility": args.volatility,
        "sink_hint": args.sink_hint,
        "payload": payload,
        "provenance": {
            "emitter": "capture-event.py",
            "contract": CONTRACT_REF,
            "matrix_version": MATRIX_VERSION,
        },
    }

    # --- dry-run route (advisory; never a sink write) ---
    route = _route_dry_run(event)
    event["route"] = route
    if route.get("route_error"):
        print(f"capture-event: WARNING: {route['route_error']}", file=sys.stderr)

    # --- persist event + audit (runtime spool only) ---
    try:
        _append_jsonl(events_path, event)
        _audit(audit_path, {
            **meta, "event_id": event["event_id"], "as_of": as_of,
            "target_sink": route.get("target_sink"),
            "action": route.get("action"),
            "confidence": route.get("confidence"),
            "rule": route.get("rule"),
            "dedupe_status": "new", "result": "emitted",
            "ref_written": None,
            **({"error": route["route_error"][:300]}
               if route.get("route_error") else {}),
        })
    except Exception as exc:
        print(f"capture-event: ERROR: cannot persist event: {exc}", file=sys.stderr)
        return 3

    print(json.dumps({
        "status": "emitted", "event_id": event["event_id"],
        "dedupe_key": dedupe_key, "event_type": args.type,
        "target_sink": route.get("target_sink"), "action": route.get("action"),
        "events_log": str(events_path), "audit_log": str(audit_path),
        "note": "dry-run only — no canonical sink was written",
    }, ensure_ascii=False))
    return 0


def self_test() -> int:
    import tempfile
    ok = total = 0

    def check(name: str, good: bool):
        nonlocal ok, total
        total += 1
        ok += bool(good)
        print(f"[{'OK' if good else 'FAIL'}] {name}")

    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        base = ["--out-dir", str(out)]

        def run(*extra):
            ns = build_parser().parse_args(list(extra) + base)
            return emit(ns)

        # 1. handoff with evidence -> emitted, envelope + where_filed preserved
        rc = run("--type", "handoff", "--source", "devin", "--session", "s1",
                 "--subject", "packet-1", "--summary", "Session handoff: router wiring",
                 "--ref", "docs/ssot/jobs/session-summary/x.yml",
                 "--where-filed", "packet -> opencode-note:n1",
                 "--where-filed", "outcome -> dispatch-outcome-20261125-x.md")
        events = _load_events(out / EVENTS_LOG)
        good = (rc == 0 and len(events) == 1
                and events[0]["event_type"] == "handoff"
                and events[0]["payload"]["where_filed"] ==
                ["packet -> opencode-note:n1",
                 "outcome -> dispatch-outcome-20261125-x.md"]
                and events[0]["dedupe_key"].startswith("handoff:devin:s1:"))
        check("handoff emit preserves where_filed verbatim", good)

        # 2. replay same emit -> duplicate, still one event, two audit lines
        rc2 = run("--type", "handoff", "--source", "devin", "--session", "s1",
                  "--subject", "packet-1", "--summary", "Session handoff: router wiring",
                  "--ref", "docs/ssot/jobs/session-summary/x.yml",
                  "--where-filed", "packet -> opencode-note:n1")
        events = _load_events(out / EVENTS_LOG)
        audits = [json.loads(l) for l in
                  (out / AUDIT_LOG).read_text().splitlines() if l.strip()]
        good = (rc2 == 0 and len(events) == 1
                and any(a.get("result") == "duplicate" for a in audits))
        check("replay is noop+audit (no duplicate handoff packet)", good)

        # 3. handoff without evidence -> rejected loudly, no event written
        before = len(_load_events(out / EVENTS_LOG))
        rc3 = run("--type", "handoff", "--source", "devin", "--session", "s2",
                  "--summary", "handoff with no filed artifact")
        good = (rc3 == 2 and len(_load_events(out / EVENTS_LOG)) == before)
        check("handoff without refs/where_filed refused (no fake events)", good)

        # 4. secret-shaped summary -> rejected, content nowhere persisted
        rc4 = run("--type", "discovery", "--source", "devin",
                  "--summary", "api_key=sk-ABCDEFGHIJKLMNOPQRSTUVWX noted")
        blob = (out / EVENTS_LOG).read_text() + (out / AUDIT_LOG).read_text()
        good = (rc4 == 2 and "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in blob)
        check("secret-shaped content rejected without persisting it", good)

        # 5. open_ask requires --open-ask
        rc5 = run("--type", "open_ask", "--source", "devin",
                  "--summary", "something is pending")
        check("open_ask without --open-ask refused", rc5 == 2)

        # 6. focus_session lifecycle event (hook shape) -> emitted
        rc6 = run("--type", "focus_session", "--source", "devin",
                  "--session", "sess-9", "--actor", "devin-session-end-hook",
                  "--summary", "Session sess-9 ended (reason: complete).",
                  "--ref", "devin-session:sess-9",
                  "--open-ask", "push branch X -> devin")
        ev6 = _load_events(out / EVENTS_LOG)
        good = (rc6 == 0 and ev6[-1]["event_type"] == "focus_session"
                and ev6[-1]["payload"]["open_asks"] == ["push branch X -> devin"])
        check("focus_session emit carries open asks", good)

        # 7. invalid type/source rejected
        check("bad event_type rejected",
              run("--type", "bogus", "--source", "devin", "--summary", "x") == 2)
        check("bad source rejected",
              run("--type", "discovery", "--source", "windsurf",
                  "--summary", "x") == 2)

        # 8. explicit dedupe-key override honoured + replay-safe
        rc8 = run("--type", "decision", "--source", "manual",
                  "--summary", "chose option B", "--dedupe-key", "decision:manual:abc")
        rc8b = run("--type", "decision", "--source", "manual",
                   "--summary", "chose option B differently",
                   "--dedupe-key", "decision:manual:abc")
        n = len(_load_events(out / EVENTS_LOG))
        # 3 real events so far: handoff(s1), focus_session(sess-9), decision(abc)
        check("--dedupe-key override dedupes across wording", rc8 == 0 and rc8b == 0 and n == 3)

        # 9. dry-run route recorded (target_sink present, no sink write)
        routed = [e for e in _load_events(out / EVENTS_LOG) if e.get("route")]
        check("every event carries a dry-run route block",
              len(routed) == len(_load_events(out / EVENTS_LOG)))

    print(f"self-test: {ok}/{total} passed")
    return 0 if ok == total else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", required=False,
                    help=f"event_type: {sorted(EVENT_TYPES)}")
    ap.add_argument("--source", required=False,
                    help=f"source: {sorted(SOURCES)}")
    ap.add_argument("--actor", help="actor (default: source)")
    ap.add_argument("--session", help="session id (dedupe anchor)")
    ap.add_argument("--subject", help="packet/topic id (dedupe tail when no session)")
    ap.add_argument("--summary", help="pointer-first one-paragraph summary")
    ap.add_argument("--ref", action="append", help="evidence ref (repeatable, max 20)")
    ap.add_argument("--where-filed", action="append",
                    help='"item -> sink/ID/path" verbatim (repeatable, max 50)')
    ap.add_argument("--open-ask", action="append",
                    help='open ask "text -> owner/options" (repeatable, max 20)')
    ap.add_argument("--as-of", help="ISO timestamp (default: now)")
    ap.add_argument("--volatility", default="pointer",
                    help=f"{sorted(VOLATILITY)} (default: pointer)")
    ap.add_argument("--sink-hint", help="optional sink hint (advisory only)")
    ap.add_argument("--payload-json", help="extra small JSON object payload")
    ap.add_argument("--dedupe-key", help="explicit dedupe_key override")
    ap.add_argument("--out-dir", default=str(OUT),
                    help="capture runtime dir (default: $CHABA_CAPTURE_OUT or ~/.local/share/chaba/capture)")
    ap.add_argument("--self-test", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        return self_test()
    if not args.type or not args.source:
        build_parser().error("--type and --source are required (or --self-test)")
    return emit(args)


if __name__ == "__main__":
    sys.exit(main())
