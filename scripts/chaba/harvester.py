#!/usr/bin/env python3
"""harvester.py -- Phase C capture harvester (READ-ONLY, on-demand, deterministic).

Scans the three approved source surfaces for durable capture candidates,
routes each through capture-router.py, and emits:
  1. a human-review proposal report (Markdown), and
  2. an append-only ledger (YAML) keyed by run_id + sink-native dedupe_key.

It NEVER writes to a canonical sink: no SSOT edits, no board-api/board-cli
mutations, no /lesson, no OC knowledge note, no docs/kb, no evidence surface.
There is no --apply in this slice by design (OPS-0016 approved 2026-11-23).

Approved sources (only these three):
  1. card comms from:tony  -- ops verbs filtered, substantive text kept
  2. docs/ssot/focus-inbox/*.yml (top level; processed/ + archived/ excluded)
  3. dispatch-outcome-*.md  -- repo root and docs tree

Dedupe: sink-native stable key from the router. An append-only ledger makes
repeat runs report "already proposed" instead of forking a new proposal.
Upsert-in-place by dedupe_key; never fork.

Usage:
    harvester.py                       # scan all, write report + ledger
    harvester.py --source card-comms   # one surface (repeatable)
    harvester.py --limit 25            # cap candidates per surface (smoke)
    harvester.py --out-dir DIR         # override output dir
    harvester.py --stdout              # print proposals, write nothing
    harvester.py --self-test           # deterministic checks, no scan
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("harvester: PyYAML required\n")
    raise

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("REPO") or HERE.parents[1])

# capture-router.py has a hyphen in its name, so import it by path.
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("capture_router", HERE / "capture-router.py")
_router = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_router)
MATRIX_VERSION, route = _router.MATRIX_VERSION, _router.route

RUN_ID = time.strftime("%Y%m%dT%H%M%S")
DEFAULT_OUT = Path(os.environ.get("CHABA_CAPTURE_OUT")
                   or (Path.home() / ".local/share/chaba/capture"))
CARDS_DIR = REPO / "docs/ssot/kanban/cards"
INBOX_DIR = REPO / "docs/ssot/focus-inbox"
LEDGER = "capture-ledger.yml"

# Ops ceremony from tony comms -- never a durable capture candidate.
OPS_RE = re.compile(
    r"^\s*(?:claimed|queued|moved\b|closed\b|done\b|approve[ds]?\b|lgtm\b|"
    r"ack\b|ok\b|thanks\b|status\?|next\?|continue\b|proceed\b|"
    r"card captured|auto[- ]resolved|closed by)\b",
    re.IGNORECASE,
)
MIN_LEN = 40


def _candidate(source, source_id, text, as_of="", already_filed=False):
    return {
        "source": source, "source_id": str(source_id), "text": text.strip(),
        "as_of": as_of, "already_filed": already_filed,
    }


def scan_card_comms(limit=None):
    out = []
    for path in sorted(CARDS_DIR.glob("*.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for i, c in enumerate(doc.get("comms") or []):
            if not isinstance(c, dict) or str(c.get("from", "")).lower() != "tony":
                continue
            text = str(c.get("text") or "")
            if len(text) < MIN_LEN or OPS_RE.match(text):
                continue
            out.append(_candidate(
                "card-comms", f"{path.stem}#comms[{i}]", text,
                str(c.get("at") or "")))
            if limit and len(out) >= limit:
                return out
    return out


def scan_focus_inbox(limit=None):
    out = []
    for path in sorted(INBOX_DIR.glob("*.yml")):  # top level only
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        focus = doc.get("focus") if isinstance(doc.get("focus"), dict) else {}
        text = " ".join(filter(None, [doc.get("title"),
                                      focus.get("text") or doc.get("subtitle")]))
        status = str(focus.get("status") or doc.get("status") or "draft").lower()
        already = status in ("processed", "archived", "done", "superseded")
        if len(text) < MIN_LEN:
            continue
        out.append(_candidate("focus-inbox", path.stem, text,
                              path.stem[:10], already))
        if limit and len(out) >= limit:
            break
    return out


def scan_dispatch_outcomes(limit=None):
    out = []
    paths = sorted(REPO.glob("dispatch-outcome-*.md"))
    paths += sorted((REPO / "docs").rglob("dispatch-outcome-*.md"))
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")[:4000]
        except Exception:
            continue
        headline = next((ln for ln in text.splitlines() if ln.startswith("# ")), path.stem)
        # Not pre-marked filed: let the router index these as evidence links
        # or surface lesson/SSOT candidates hiding inside them.
        out.append(_candidate("dispatch-outcome", path.stem,
                              f"{headline}\n{text[:1200]}", path.stem[16:24], False))
        if limit and len(out) >= limit:
            break
    return out


SCANNERS = {
    "card-comms": scan_card_comms,
    "focus-inbox": scan_focus_inbox,
    "dispatch-outcome": scan_dispatch_outcomes,
}


def load_ledger(path: Path):
    if not path.exists():
        return []
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [e for e in doc.get("entries", []) if isinstance(e, dict)]
    except Exception:
        return []


def dedupe_key_exists(entries, key):
    return any(e.get("dedupe_key") == key for e in entries)


def render_report(proposals, counts, ledger_total, out_dir):
    by_sink = Counter(p["proposed_sink"] for p in proposals)
    by_source = Counter(p["source"] for p in proposals)
    lines = [
        f"# Phase C capture proposal report — {RUN_ID}", "",
        f"- matrix: `{MATRIX_VERSION}`",
        f"- proposals: **{len(proposals)}** (new: "
        f"**{sum(1 for p in proposals if not p.get('duplicate'))}**, "
        f"already-proposed: **{sum(1 for p in proposals if p.get('duplicate'))}**)",
        f"- ledger entries to date: {ledger_total}",
        f"- scanned: " + ", ".join(f"{k}={v}" for k, v in counts.items()),
        f"- by sink: " + (", ".join(f"{k}={v}" for k, v in by_sink.items()) or "none"),
        f"- by source: " + (", ".join(f"{k}={v}" for k, v in by_source.items()) or "none"),
        "", "> READ-ONLY: nothing was written to any canonical sink. "
        "Review before any future --apply gate.", "",
        "| sink | action | dedupe_key | confidence | source_id | excerpt |",
        "|---|---|---|---|---|---|",
    ]
    for p in proposals:
        excerpt = p["text_excerpt"].replace("|", "\\|").replace("\n", " ")[:90]
        dup = " **[dup]**" if p.get("duplicate") else ""
        lines.append(
            f"| `{p['proposed_sink']}` | {p['action']}{dup} | "
            f"`{p['dedupe_key']}` | {p['confidence']} | "
            f"{p['source_id']} | {excerpt} |")
    path = out_dir / f"capture-proposal-{RUN_ID}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(args):
    sources = args.source or list(SCANNERS)
    out_dir = Path(args.out_dir).expanduser()
    ledger_path = out_dir / LEDGER
    ledger = load_ledger(ledger_path)
    known = {e.get("dedupe_key") for e in ledger}

    candidates, counts = [], {}
    for source in sources:
        fn = SCANNERS.get(source)
        if not fn:
            sys.stderr.write(f"harvester: unknown source {source!r}\n")
            return 2
        found = fn(args.limit)
        counts[source] = len(found)
        candidates.extend(found)

    proposals = []
    for cand in candidates:
        p = route(cand, RUN_ID)
        p["duplicate"] = p["dedupe_key"] in known
        if not p["duplicate"]:
            known.add(p["dedupe_key"])
        proposals.append(p)

    if args.stdout:
        import json
        print(json.dumps(proposals, indent=2, ensure_ascii=False))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    report = render_report(proposals, counts, len(ledger), out_dir)
    new_entries = [
        {k: p[k] for k in ("run_id", "dedupe_key", "proposed_sink", "action",
                           "source", "source_id", "as_of", "confidence")}
        for p in proposals if not p["duplicate"]
    ]
    if new_entries:
        entries = ledger + new_entries
        ledger_path.write_text(
            yaml.safe_dump({"matrix_version": MATRIX_VERSION, "entries": entries},
                           allow_unicode=True, sort_keys=False),
            encoding="utf-8")

    print(f"run {RUN_ID}: {len(proposals)} proposals "
          f"({sum(1 for p in proposals if not p['duplicate'])} new, "
          f"{sum(1 for p in proposals if p['duplicate'])} already proposed)")
    print(f"report: {report}")
    print(f"ledger: {ledger_path}")
    print("READ-ONLY: no canonical sink was written.")
    return 0


def self_test():
    checks = [
        (scan_focus_inbox, "focus-inbox"),
        (scan_card_comms, "card-comms"),
        (scan_dispatch_outcomes, "dispatch-outcome"),
    ]
    ok = 0
    for fn, name in checks:
        found = fn(2)
        good = all(c["source"] == name and c["text"] for c in found)
        print(f"[{'OK' if good else 'FAIL'}] {name}: {len(found)} sample candidates")
        ok += good
    p = route(_candidate("selftest", "x", "Explain how capture routing works"), "selftest")
    good = p["proposed_sink"] == "lesson" and p["action"] in ("create", "link")
    print(f"[{'OK' if good else 'FAIL'}] route -> {p['proposed_sink']}/{p['action']}")
    ok += good
    print(f"self-test: {ok}/{len(checks)+1} passed")
    return 0 if ok == len(checks) + 1 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=list(SCANNERS), action="append")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--stdout", action="store_true", help="print proposals, write nothing")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    return self_test() if args.self_test else run(args)


if __name__ == "__main__":
    sys.exit(main())
