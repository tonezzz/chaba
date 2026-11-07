#!/usr/bin/env python3
"""backlog-audit — the standard backlog assessment pass.

Buckets every backlog card so a sweep (human or agent) never re-derives
the same triage. Buckets, in priority order:

  answered-idle    — an open request got an answer but nobody acted on
                     it. Sub-verdict by answer shape:
                       close     answer resolves the card (obsolete/
                                verified/keep-as-is)
                       queue     answer IS the spec/decision — card can
                                be spec'd + dispatched
                       circular  the picked option only re-asks a
                                question (meta option — no new info)
  done-candidate   — strong evidence the work already landed (title/id
                     twin in done/, or a merged dispatch branch whose
                     card id matches)
  obsolete-signal  — premise references a retired host/repo (idc01,
                     dell-served, :11023 parked MDDB...) or a sibling
                     done card supersedes it
  thin             — spec < MIN_SPEC chars and unenriched (the
                     backlog-spec-enrich lane drains these)
  valid            — spec'd, unanswered, genuinely waiting

Runs on the live-writer host (idc03): reads cards only — it never
mutates; the sweep decides per bucket.

Env:  CARD_DIR  card dir (default served checkout on idc03)
Usage: backlog-audit.py [--json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from pathlib import Path

import yaml

CARD_DIR = Path(os.environ.get(
    "CARD_DIR",
    os.path.expanduser("~/CascadeProjects/chaba-tony-dell/"
                       "docs/ssot/kanban/cards")))
MIN_SPEC = int(os.environ.get("ENRICH_MIN_SPEC", "80"))
MARKER = "backlog-spec-enrich"
# premises that died — extend as infra retires
RETIRED = ("idc01", "tony-dell:8787", ":11023", "mddb01",
           "ada-pi-pwa:8001", "chaba-kanban-sync")
META_OPT = re.compile(r"clarif|specify|ask the owner|which repos|"
                      r"which host|more context|define the", re.I)


def _load() -> tuple[dict[str, list], set[str]]:
    cols: dict[str, list] = {}
    done_ids: set[str] = set()
    for p in sorted(CARD_DIR.glob("*.yml")):
        try:
            c = yaml.safe_load(open(p))
        except Exception:
            continue
        if not isinstance(c, dict):
            continue
        col = c.get("column") or "backlog"
        if col == "done":
            done_ids.add(c.get("id") or p.stem)
            # also index done titles for dup sniffing
            done_ids.add(str(c.get("title") or "").lower()[:40])
        cols.setdefault(col, []).append((p, c))
    return cols, done_ids


def _answer_shape(ans: str) -> str:
    a = (ans or "").lower()
    if re.search(r"already|done it|obsolete|no longer|keep .*backlog|"
                 r"keep the epic|mostly right|verified|running on", a):
        return "close"
    if META_OPT.search(a):
        return "circular"
    if re.search(r"wait|hold|postpone|later|when .*reset", a):
        return "hold"
    return "queue"


VERIFIED = re.compile(r"verified|merged|deployed|landed|pushed|fixed",
                      re.I)
FAILED = re.compile(r"verified.?false|merge conflict|merge failed|"
                    r"gate fail|timed? ?out|crashed|killed", re.I)


def audit_review(cards: list[tuple[Path, dict]]) -> dict:
    """Review-column buckets: review means a dispatch finished and a
    human verdict is pending — find the ones the evidence already
    decides."""
    out: dict[str, list] = {k: [] for k in
                            ("done-candidate", "failed-signal",
                             "answered", "waiting-human")}
    for p, c in cards:
        cid = c.get("id") or p.stem
        comms = [str(m.get("text") or "") for m in (c.get("comms") or [])
                 if isinstance(m, dict)]
        tail = " ".join(comms[-3:])
        answered = [r for r in (c.get("requests") or [])
                    if isinstance(r, dict)
                    and r.get("status") == "answered" and r.get("answer")]
        if answered:
            out["answered"].append(cid)
            continue
        if FAILED.search(tail):
            out["failed-signal"].append(cid)
            continue
        if VERIFIED.search(tail):
            out["done-candidate"].append(cid)
            continue
        out["waiting-human"].append(cid)
    return out


def audit() -> dict:
    cols, done_ids = _load()
    out: dict[str, list] = {k: [] for k in
                            ("answered-close", "answered-queue",
                             "answered-circular", "answered-hold",
                             "done-candidate", "obsolete-signal",
                             "thin", "valid")}
    for p, c in cols.get("backlog", []):
        cid = c.get("id") or p.stem
        a = c.get("action") or {}
        if a.get("status") in ("queued", "running"):
            continue
        blob = " ".join(str(x) for x in
                        (c.get("title"), c.get("note"), c.get("spec")))
        comms = [m.get("text") or "" for m in (c.get("comms") or [])
                 if isinstance(m, dict)]
        enriched = any(MARKER in t for t in comms)
        answered = [r for r in (c.get("requests") or [])
                    if isinstance(r, dict) and r.get("status") == "answered"
                    and r.get("answer")]
        if answered:
            shape = _answer_shape(str(answered[-1].get("answer")))
            out[f"answered-{shape}"].append(cid)
            continue
        if cid in done_ids or str(c.get("title") or "").lower()[:40] \
                in done_ids:
            out["done-candidate"].append(cid)
            continue
        if any(tok in blob for tok in RETIRED):
            out["obsolete-signal"].append(cid)
            continue
        if len((c.get("spec") or "").strip()) < MIN_SPEC and not enriched:
            out["thin"].append(cid)
            continue
        out["valid"].append(cid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--column", default="backlog",
                    choices=("backlog", "review", "all"))
    args = ap.parse_args()
    cols, done_ids = _load()
    sections: dict[str, dict] = {}
    if args.column in ("backlog", "all"):
        sections["backlog"] = audit()
    if args.column in ("review", "all"):
        sections["review"] = audit_review(cols.get("review", []))
    if args.json:
        print(json.dumps(sections, indent=1))
        return 0
    for col, res in sections.items():
        total = sum(len(v) for v in res.values())
        print(f"{total} {col} cards assessed")
        for k, v in res.items():
            print(f"\n== {k} ({len(v)})")
            for cid in v:
                print(" ", cid)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
