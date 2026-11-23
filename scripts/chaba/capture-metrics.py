#!/usr/bin/env python3
"""Phase D baseline metrics for the knowledge-capture pipeline (read-only).

Reports the four Phase D signals from docs/ssot/ssot.knowledge-capture.yml
(repeat-ask/miss rate, stale-pointer incidents, time-to-find) plus the
matrix-precision evidence used to tune the routing matrix.

Posture: READ-ONLY. Reads the capture ledger and canonical SSOT files; never
writes to a canonical sink. Optional --out writes a local report artifact only.

Signals with no durable source are reported as `unmeasurable` with a concrete
proposal for where the source should live. A proxy is labelled `proxy`, never
presented as a measured incident count.

Usage:
  python3 scripts/chaba/capture-metrics.py
  python3 scripts/chaba/capture-metrics.py --out ~/.local/share/chaba/capture/metrics-baseline.md
  python3 scripts/chaba/capture-metrics.py --self-test
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = Path.home() / ".local/share/chaba/capture/capture-ledger.yml"
REPEAT_ASKS = REPO / "docs/ssot/ssot.repeat-asks.yml"
CAPTURE_SSOT = REPO / "docs/ssot/ssot.knowledge-capture.yml"
AS_OF = dt.date.today().isoformat()

# Producer artifact shapes in focus-inbox. These entries already have a
# durable home (focus-inbox); re-cardfing them would flood the board.
PRODUCER_PATTERNS = (
    re.compile(r"job-fail-"),
    re.compile(r"-report-watch-"),
    re.compile(r"kanban-cards-"),
    re.compile(r"^handoff-"),
    re.compile(r"-audit-"),
)

POINTER_SINKS = {"ssot", "kb", "oc-note"}
MISS_INSTRUMENTED_SINCE = "2026-11-23"
POINTER_LOG = Path.home() / ".local/share/chaba/capture/pointer-incidents.yml"
INFO_FIND_AUDIT_ROOT = Path.home() / ".cache/devin/info-find"


def is_producer_artifact(source_id: str) -> bool:
    return any(p.search(str(source_id or "")) for p in PRODUCER_PATTERNS)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    data = _load_yaml(path)
    return list(data.get("entries") or [])


def _staleness_days(last: str | None) -> int | None:
    if not last:
        return None
    try:
        then = dt.date.fromisoformat(last[:10])
    except ValueError:
        return None
    return (dt.date.today() - then).days


def repeat_ask_signal(repo: Path = REPO) -> dict[str, Any]:
    """Measured from the canonical repeat-ask register."""
    data = _load_yaml(repo / "docs/ssot/ssot.repeat-asks.yml")
    topics = list(data.get("topics") or [])
    history = [h for t in topics for h in (t.get("history") or [])]
    dates = sorted({str(h.get("at") or "")[:10] for h in history if h.get("at")})
    span = 0
    if len(dates) >= 2:
        span = max(1, (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days)
    last = dates[-1] if dates else None
    return {
        "status": "measured",
        "source": "docs/ssot/ssot.repeat-asks.yml",
        "as_of": last,
        "topics": len(topics),
        "total_asks": sum(int(t.get("count") or 0) for t in topics),
        "open_topics": sum(1 for t in topics if str(t.get("status")) == "open"),
        "history_lines": len(history),
        "window_days": span,
        "asks_per_week": round(len(history) * 7 / span, 2) if span else None,
        "stale_days": _staleness_days(last),
        "refresh": "python3 scripts/chaba/capture-metrics.py (re-reads the register)",
    }


def miss_signal(repo: Path = REPO) -> dict[str, Any]:
    """Measured from the `misses:` block of the repeat-ask register.

    The block was instrumented 2026-11-23. Older register revisions without
    it fall back to `unmeasurable` rather than guessing a count.
    """
    source = "docs/ssot/ssot.repeat-asks.yml -> misses[]"
    data = _load_yaml(repo / "docs/ssot/ssot.repeat-asks.yml")
    if "misses" not in data:
        return {
            "status": "unmeasurable",
            "source": "AGENTS.md lesson-capture duty -> ssot.repeat-asks.yml (no miss field)",
            "as_of": AS_OF,
            "proposal": (
                "Add a `misses:` block to ssot.repeat-asks.yml; append via "
                "scripts/chaba/miss-add.py on every reply-only lesson/answer."
            ),
            "owner": "session-capture duty",
        }
    misses = [m for m in (data.get("misses") or []) if isinstance(m, dict)]
    dates = sorted({str(m.get("at") or "")[:10] for m in misses if m.get("at")})
    span = 0
    if len(dates) >= 2:
        span = max(1, (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days)
    return {
        "status": "measured",
        "source": source,
        "as_of": dates[-1] if dates else MISS_INSTRUMENTED_SINCE,
        "count": len(misses),
        "by_location": dict(collections.Counter(m.get("location") for m in misses)),
        "by_topic": dict(collections.Counter(m.get("topic") for m in misses)),
        "by_sink": dict(collections.Counter(m.get("should_have_been") for m in misses)),
        "window_days": span,
        "misses_per_week": round(len(misses) * 7 / span, 2) if span else None,
        "first_miss": dates[0] if dates else None,
        "instrumented_since": MISS_INSTRUMENTED_SINCE,
        "note": (
            "Counts begin at instrumentation 2026-11-23; an empty log is 0 "
            "measured misses so far, not evidence that none occurred."
        ),
        "refresh": "append via scripts/chaba/miss-add.py, then re-run this report",
    }


def stale_pointer_signal(entries: list[dict[str, Any]], max_age_days: int = 30,
                         log: Path = POINTER_LOG) -> dict[str, Any]:
    """Measured from the local stale-pointer log when instrumented.

    Falls back to the pre-instrumentation proxy (old-as_of pointer candidates)
    when no log exists. The proxy is never presented as recorded incidents.
    """
    candidates = []
    for e in entries:
        if e.get("proposed_sink") not in POINTER_SINKS:
            continue
        age = _staleness_days(str(e.get("as_of") or "")[:10])
        if age is not None and age > max_age_days:
            candidates.append(e)
    proxy_count = len(candidates)
    proxy = {
        "status": "proxy",
        "source": f"capture ledger: pointer-sink candidates older than {max_age_days}d",
        "as_of": AS_OF,
        "count": proxy_count,
        "by_sink": dict(collections.Counter(e.get("proposed_sink") for e in candidates)),
        "caveat": "Capture candidates for review; NOT recorded incidents. No incident log exists.",
        "proposal": (
            "Record incidents via `python3 scripts/chaba/pointer-stale-add.py "
            "--pointer-ref <ref> --canonical-ref <ref>`; the local log is "
            "~/.local/share/chaba/capture/pointer-incidents.yml."
        ),
        "owner": "info-find / session-capture",
    }
    if not log.exists():
        return proxy

    incidents = [i for i in (_load_yaml(log).get("incidents") or [])
                 if isinstance(i, dict)]
    by_pointer = dict(collections.Counter(i.get("pointer_ref") for i in incidents))
    dates = sorted({str(i.get("found_at") or "")[:10]
                    for i in incidents if i.get("found_at")})
    return {
        "status": "measured",
        "source": str(log),
        "as_of": dates[-1] if dates else "2026-11-23",
        "count": len(incidents),
        "by_pointer": by_pointer,
        "repeat_pointers": {k: v for k, v in by_pointer.items() if v >= 3},
        "by_fix": dict(collections.Counter(i.get("fix") for i in incidents)),
        "proxy_candidates": proxy_count,
        "promotion_threshold": "3+ hits on one pointer_ref -> card (not enforced)",
        "refresh": "python3 scripts/chaba/pointer-stale-add.py --pointer-ref ... --canonical-ref ...",
    }


def _audit_runs(root: Path) -> list[dict[str, Any]]:
    """Read info_find.py run audits (local cache, one ndjson per session)."""
    runs: list[dict[str, Any]] = []
    if not root.exists():
        return runs
    for path in root.rglob("audit.ndjson"):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if '"kind"' not in line:
                    continue
                rec = json.loads(line)
                if rec.get("kind") == "run":
                    runs.append(rec)
        except (OSError, ValueError):
            continue  # one corrupt/removed audit must not break the report
    return runs


def time_to_find_signal(root: Path = INFO_FIND_AUDIT_ROOT) -> dict[str, Any]:
    """Measured from info_find.py's per-session audit (local-only telemetry)."""
    runs = [r for r in _audit_runs(root) if "total_elapsed_ms" in r]
    if not runs:
        return {
            "status": "unmeasurable",
            "source": f"no info_find run audits with total_elapsed_ms under {root}",
            "as_of": AS_OF,
            "proposal": (
                "Run `python3 scripts/devnest/info_find.py run --query '...'` to "
                "write audit.ndjson; the run record now carries total_elapsed_ms, "
                "elapsed_by_source, source_sequence and resolved_ref."
            ),
            "owner": "info-find skill",
        }
    elapsed = sorted(int(r["total_elapsed_ms"]) for r in runs)
    hops = [len(r.get("source_sequence") or []) for r in runs]
    resolved = sum(1 for r in runs if r.get("resolved_ref"))
    per_source: dict[str, list[int]] = collections.defaultdict(list)
    for r in runs:
        for src, ms in (r.get("elapsed_by_source") or {}).items():
            per_source[str(src)].append(int(ms))
    return {
        "status": "measured",
        "source": f"info_find.py audit.ndjson under {root}",
        "as_of": max(str(r.get("t") or "")[:10] for r in runs),
        "count": len(runs),
        "median_elapsed_ms": int(statistics.median(elapsed)),
        "mean_elapsed_ms": round(sum(elapsed) / len(elapsed), 1),
        "max_elapsed_ms": elapsed[-1],
        "resolved_pct": round(100 * resolved / len(runs), 1),
        "mean_source_hops": round(sum(hops) / len(hops), 2),
        "mean_elapsed_by_source_ms": {
            s: round(sum(v) / len(v), 1) for s, v in sorted(per_source.items())},
        "caveat": (
            "Local cache telemetry: clearing ~/.cache/devin/info-find resets the "
            "sample. Covers info_find source time only, not agent-tool merge time."
        ),
        "refresh": "python3 scripts/devnest/info_find.py run --query '...'",
    }


def matrix_precision(entries: list[dict[str, Any]]) -> dict[str, Any]:
    creates = [e for e in entries if e.get("action") == "create"]
    kanban_creates = [e for e in creates if e.get("proposed_sink") == "kanban"]
    by_source = dict(collections.Counter(e.get("source") for e in creates))
    filed = [
        e for e in kanban_creates
        if e.get("source") == "dispatch-outcome"
        or (e.get("source") == "focus-inbox"
            and is_producer_artifact(str(e.get("source_id") or "")))
    ]
    filed_breakdown = dict(collections.Counter(
        "dispatch-outcome" if e.get("source") == "dispatch-outcome"
        else next(
            (label for pat, label in zip(
                PRODUCER_PATTERNS,
                ("job-fail", "report-watch", "kanban-cards", "handoff", "audit"),
            ) if pat.search(str(e.get("source_id") or ""))),
            "other",
        )
        for e in filed
    ))
    useful = len(kanban_creates) - len(filed)
    return {
        "status": "measured",
        "source": "capture ledger (proposal actions)",
        "as_of": AS_OF,
        "creates_total": len(creates),
        "creates_by_source": by_source,
        "kanban_creates": len(kanban_creates),
        "filed_artifact_creates": len(filed),
        "filed_breakdown": filed_breakdown,
        "actionable_creates": useful,
        "precision_pct": round(100 * useful / len(kanban_creates), 1) if kanban_creates else None,
        "tuning": (
            "Gate kanban auto-create on source: focus-inbox producer artifacts "
            "and dispatch outcomes route to an evidence pointer on the existing "
            "artifact instead of a new card."
        ),
    }


def render(entries: list[dict[str, Any]], ledger: Path) -> str:
    signals = [
        ("Repeat-ask rate", repeat_ask_signal()),
        ("Miss rate", miss_signal()),
        ("Stale-pointer incidents", stale_pointer_signal(entries)),
        ("Time-to-find", time_to_find_signal()),
    ]
    out = [
        "# Phase D capture metrics — baseline",
        "",
        f"- as_of: {AS_OF}",
        f"- ledger: `{ledger}` ({len(entries)} entries)",
        "- posture: read-only; unmeasurable signals are labelled, not guessed",
        "",
        "| Signal | Status | Value | Source |",
        "|---|---|---|---|",
    ]
    for label, s in signals:
        value = ""
        for key in ("total_asks", "count", "asks_per_week", "misses_per_week",
                    "median_elapsed_ms", "resolved_pct", "mean_source_hops",
                    "stale_days"):
            if key in s and s[key] is not None:
                value += f"{key}={s[key]} "
        value = value.strip() or s["status"]
        out.append(f"| {label} | {s['status']} | {value} | `{s['source']}` |")

    out += ["", "## Signal detail", ""]
    for label, s in signals:
        out.append(f"### {label}")
        out.append("")
        for k, v in s.items():
            if k == "refresh":
                continue
            out.append(f"- {k}: {v}")
        out.append("")

    p = matrix_precision(entries)
    out += [
        "## Matrix precision (tuning evidence)",
        "",
        f"- ledger creates: {p['creates_total']} ({p['creates_by_source']})",
        f"- kanban creates: {p['kanban_creates']}",
        f"- already-filed artifacts among them: {p['filed_artifact_creates']} ({p['filed_breakdown']})",
        f"- actionable creates: {p['actionable_creates']}",
        f"- precision: **{p['precision_pct']}%**",
        "",
        f"Tuning: {p['tuning']}",
        "",
        "## Promotion thresholds (proposed, not enforced)",
        "",
        "- never auto-create a kanban card from a focus-inbox producer artifact",
        "- `link`/`skip` are safe; `create` requires a non-producer source or explicit approval",
        "- `--apply` remains a separate gated decision — this report does not enable it",
        "",
    ]
    return "\n".join(out)


def self_test() -> int:
    assert is_producer_artifact("2026-10-27-143740-job-fail-bad-on-testbox")
    assert is_producer_artifact("2026-10-07-174905-report-watch-goal-rot-x")
    assert is_producer_artifact("2026-10-10-0318-kanban-cards-foo-ssot-optimization")
    assert is_producer_artifact("handoff-devin-handoff-voice-enrollment-fix")
    assert not is_producer_artifact("wiki-login-polish")
    entries = [
        {"source": "focus-inbox", "source_id": "2026-11-01-100000-job-fail-bad-on-testbox",
         "action": "create", "proposed_sink": "kanban", "as_of": "2026-11-01"},
        {"source": "dispatch-outcome", "source_id": "dispatch-outcome-20261120-172937-goal",
         "action": "create", "proposed_sink": "kanban", "as_of": "2026-11-20"},
        {"source": "focus-inbox", "source_id": "wiki-login-polish",
         "action": "create", "proposed_sink": "kanban", "as_of": "2026-11-01"},
    ]
    p = matrix_precision(entries)
    assert p["kanban_creates"] == 3 and p["filed_artifact_creates"] == 2, p
    assert p["precision_pct"] == 33.3, p
    # Explicit absent paths: the self-test must not depend on local telemetry
    # files created by a real run on this host.
    assert stale_pointer_signal(
        entries, max_age_days=0,
        log=Path(tempfile.gettempdir()) / "capture-metrics-no-such-pointer-log.yml"
    )["status"] == "proxy"
    assert time_to_find_signal(
        Path(tempfile.gettempdir()) / "capture-metrics-no-such-audit-root"
    )["status"] == "unmeasurable"
    with tempfile.TemporaryDirectory() as d:
        ssot = Path(d) / "docs/ssot"
        ssot.mkdir(parents=True)
        reg = ssot / "ssot.repeat-asks.yml"
        reg.write_text(
            "topics: []\nmisses:\n"
            "  - {topic: some-topic, at: '2026-11-23', location: chat, "
            "should_have_been: 'lesson:some-slug', evidence: msg-ref-1}\n"
            "  - {topic: some-topic, at: '2026-11-24', location: voice, "
            "should_have_been: 'lesson:some-slug', evidence: msg-ref-2}\n",
            encoding="utf-8",
        )
        ms = miss_signal(Path(d))
        assert ms["status"] == "measured", ms
        assert ms["count"] == 2, ms
        assert ms["by_location"] == {"chat": 1, "voice": 1}, ms
        assert ms["misses_per_week"] == 14.0, ms
        assert ms["instrumented_since"] == MISS_INSTRUMENTED_SINCE
        reg.write_text("topics: []\n", encoding="utf-8")
        assert miss_signal(Path(d))["status"] == "unmeasurable"

    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "pointer-incidents.yml"
        assert stale_pointer_signal(entries, log=log)["status"] == "proxy"
        log.write_text(
            "incidents:\n"
            "  - {pointer_ref: docs/ssot/a.yml, canonical_ref: docs/ssot/b.yml, found_at: '2026-11-23'}\n"
            "  - {pointer_ref: docs/ssot/a.yml, canonical_ref: docs/ssot/c.yml, found_at: '2026-11-23'}\n"
            "  - {pointer_ref: docs/ssot/a.yml, canonical_ref: docs/ssot/d.yml, found_at: '2026-11-23'}\n"
            "  - {pointer_ref: docs/kb/x.md, canonical_ref: docs/kb/y.md, found_at: '2026-11-23'}\n",
            encoding="utf-8",
        )
        sp = stale_pointer_signal(entries, log=log)
        assert sp["status"] == "measured" and sp["count"] == 4, sp
        assert "docs/ssot/a.yml" in sp["repeat_pointers"], sp

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        audit = root / "session/audit.ndjson"
        audit.parent.mkdir(parents=True)
        audit.write_text("\n".join(json.dumps(r) for r in [
            {"kind": "run", "t": "2026-11-23T10:00:00+00:00", "total_elapsed_ms": 100,
             "resolved_ref": "docs/ssot/a.yml", "source_sequence": ["mddb", "ssot"],
             "elapsed_by_source": {"mddb": 80, "ssot": 20}},
            {"kind": "run", "t": "2026-11-23T11:00:00+00:00", "total_elapsed_ms": 200,
             "resolved_ref": None, "source_sequence": ["ssot"],
             "elapsed_by_source": {"ssot": 200}},
        ]) + "\n", encoding="utf-8")
        tf = time_to_find_signal(root)
        assert tf["status"] == "measured" and tf["count"] == 2, tf
        assert tf["median_elapsed_ms"] == 150, tf
        assert tf["resolved_pct"] == 50.0, tf
        assert time_to_find_signal(root / "missing")["status"] == "unmeasurable"
    print("self-test: 21/21 passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--out", type=Path, help="write the report to a local file")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.ledger.exists():
        print(f"error: ledger not found: {args.ledger}", file=sys.stderr)
        return 2
    entries = _load_ledger(args.ledger)
    report = render(entries, args.ledger)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"report: {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
